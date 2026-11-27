"""The whole auction-report pipeline as one run, for a Render cron job (not GitHub Actions).

    python scripts/worker.py [hours]

1. restores the pipeline's state (data/index.json + data/batches) from Supabase Storage,
2. walks the Spices Board listing for new reports,
3. reads pending reports, newest first, a few chunks in parallel, saving the state after each,
4. publishes: lots.json / terminal.json to the public bucket, the batches into the tables,
5. reads the board's schedule circulars into the public bucket (schedule/<key>.txt).

Render keeps at most one run of a cron job going, so an hourly schedule runs back to
back while reports are pending and takes a few minutes a run after that.
Needs SUPABASE_URL and SUPABASE_SERVICE_KEY.

HELPER=1 (Ruphan's Mac, 27 Nov 2026): a second reader beside Render. It reads pending
reports OLDEST first, so the two meet only at the end, and uploads each finished batch
as pipeline/extra/<id>.tar.gz instead of the state; every reader merges those in before
it plans, and Render's state takes them in at its next save. The helper stops when only
a few chunks are left, so the two never read the same report.
"""
import concurrent.futures as cf
import glob, io, json, os, shutil, subprocess, sys, tarfile, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
H = {"apikey": KEY, **({} if KEY.startswith("sb_") else {"Authorization": f"Bearer {KEY}"})}
STATE = "pipeline/state.tar.gz"          # private bucket "pipeline"
PUBLIC = "public-data"                    # public bucket: lots.json, terminal.json, schedule/*.txt
HOURS = float(sys.argv[1]) if len(sys.argv) > 1 else 10.5
PER = int(os.environ.get("PER_CHUNK", "2"))
JOBS = int(os.environ.get("JOBS", str(max(1, (os.cpu_count() or 4) // 4))))
T0 = time.time()
HELPER = os.environ.get("HELPER") == "1"
EXTRA = "pipeline/extra"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def run(cmd, cwd=ROOT, **kw):
    return subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), **kw)


# ── Supabase Storage ──
def bucket(name, public):
    r = requests.post(f"{URL}/storage/v1/bucket", headers=H, json={"id": name, "name": name, "public": public}, timeout=30)
    if r.status_code >= 300 and "already exists" not in r.text.lower() and r.status_code != 409:
        log("bucket", name, r.status_code, r.text[:200])


def put(path, data, ctype):
    r = requests.post(f"{URL}/storage/v1/object/{path}", headers={**H, "Content-Type": ctype, "x-upsert": "true", "Cache-Control": "max-age=300"}, data=data, timeout=300)
    if r.status_code >= 300:
        raise RuntimeError(f"upload {path}: {r.status_code} {r.text[:200]}")


def restore():
    r = requests.get(f"{URL}/storage/v1/object/{STATE}", headers=H, timeout=300)
    if r.status_code != 200:
        log("no saved state yet: starting from the repository's copy")
        return
    shutil.rmtree(ROOT / "data" / "batches", ignore_errors=True)
    with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz") as t:
        t.extractall(ROOT, filter="data")
    log("state restored:", len(glob.glob(str(ROOT / "data/batches/*/"))), "batches")
    merge_extras()


def merge_extras():
    """Batches the other reader finished (pipeline/extra/*.tar.gz) that are not here yet."""
    r = requests.post(f"{URL}/storage/v1/object/list/pipeline", headers=H, json={"prefix": "extra/", "limit": 10000}, timeout=60)
    if r.status_code >= 300:
        return
    have = {os.path.basename(p.rstrip("/")) for p in glob.glob(str(ROOT / "data/batches/*/"))}
    got = 0
    for o in r.json():
        bid = o["name"].removesuffix(".tar.gz")
        if not o["name"].endswith(".tar.gz") or bid in have:
            continue
        g = requests.get(f"{URL}/storage/v1/object/{EXTRA}/{o['name']}", headers=H, timeout=120)
        if g.status_code == 200:
            with tarfile.open(fileobj=io.BytesIO(g.content), mode="r:gz") as t:
                t.extractall(ROOT, filter="data")
            got += 1
    if got:
        log("merged", got, "batches from the other reader")


def put_extra(bid):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        t.add(ROOT / "data/batches" / bid, arcname=f"data/batches/{bid}")
    put(f"{EXTRA}/{bid}.tar.gz", buf.getvalue(), "application/gzip")


def save():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for p in ["data/index.json", "data/index_partial.json", "data/batches"]:
            if (ROOT / p).exists():
                t.add(ROOT / p, arcname=p)
    put(STATE, buf.getvalue(), "application/gzip")
    log(f"state saved ({len(buf.getvalue()) >> 20} MB)")


# ── Reading ──
def refresh():
    """The helper's view of what Render has read since: its saved state laid over ours (nothing removed)."""
    r = requests.get(f"{URL}/storage/v1/object/{STATE}", headers=H, timeout=300)
    if r.status_code == 200:
        with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz") as t:
            t.extractall(ROOT, filter="data")


def plan(n):
    if HELPER:
        refresh()
    merge_extras()
    env = {**os.environ, "PLAN_ORDER": "oldest" if HELPER else "newest"}
    out = run([sys.executable, "scripts/plan.py", str(n), str(PER)], capture_output=True, text=True, env=env)
    log(out.stderr.strip())
    if HELPER:  # leave the last few to Render, which reads from the other end
        left = int((out.stderr.split("pending ")[1:] or ["0"])[0].split()[0])
        if left <= 8 * PER:
            log("helper: only", left, "left - Render finishes them")
            return []
    return [c["ns"] for c in json.loads(out.stdout.splitlines()[0])["include"]]


def chunk(ns, i):
    """One chunk in its own folder (run_chunk.sh works in ./work, ./outs, ./chunk.db)."""
    d = Path(f"/tmp/chunk{i}")
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    for x in ("scripts", "extract", "data"):
        (d / x).symlink_to(ROOT / x)
    env = {**os.environ, "GITHUB_WORKSPACE": str(ROOT)}
    r = run(["bash", "scripts/run_chunk.sh", ns], cwd=d, env=env, capture_output=True, text=True)
    shutil.rmtree(d, ignore_errors=True)
    return ns, (r.stdout + r.stderr)[-600:]


def read():
    """Chunks in parallel until the time budget: no new chunk once ~40 minutes are left."""
    budget = HOURS * 3600 - 40 * 60
    with cf.ThreadPoolExecutor(JOBS) as pool:
        running, slot = {}, 0
        while True:
            free = JOBS - len(running)
            if free and time.time() - T0 < budget:
                taken = set(running.values())
                for ns in [c for c in plan(JOBS * 2) if c not in taken][:free]:
                    slot += 1
                    running[pool.submit(chunk, ns, slot)] = ns
            if not running:
                return
            done, _ = cf.wait(running, return_when=cf.FIRST_COMPLETED)
            for f in done:
                ns, tail = f.result()
                del running[f]
                log("chunk", ns, "done:", tail.strip().splitlines()[-1:] if tail.strip() else "")
                if HELPER:
                    first, last = ns.split(",")[0], ns.split(",")[-1]
                    for bid in (f"n{first}-{last}r2", f"n{first}-{last}"):
                        if (ROOT / "data/batches" / bid / "reader_v2").exists():
                            put_extra(bid)
                            break
            if HELPER:
                continue
            save()
            if time.time() - LAST[0] > 2 * 3600:  # the app sees progress every two hours
                publish()


LAST = [0.0]


def publish():
    LAST[0] = time.time()
    run([sys.executable, "extract/terminal.py", "ALL", "data/terminal.json"], check=False)
    run([sys.executable, "scripts/load_supabase.py"], check=False)
    for f in ("lots.json", "terminal.json"):
        p = ROOT / "data" / f
        if p.exists():
            put(f"{PUBLIC}/{f}", p.read_bytes(), "application/json")
    log("published lots.json and terminal.json")


def schedule():
    run([sys.executable, "scripts/schedule_text.py"], check=False)
    for p in glob.glob(str(ROOT / "schedule" / "*.txt")):
        put(f"{PUBLIC}/schedule/{requests.utils.quote(os.path.basename(p))}", Path(p).read_bytes(), "text/plain; charset=utf-8")


def main():
    if not URL or not KEY:
        sys.exit("SUPABASE_URL and SUPABASE_SERVICE_KEY are needed")
    bucket("pipeline", False)
    bucket(PUBLIC, True)
    restore()
    if HELPER:
        read()
        log(f"helper finished in {(time.time() - T0) / 60:.0f} min")
        return
    try:
        schedule()
    except Exception as e:  # noqa: BLE001 - the schedule must not stop the reports
        log("schedule failed:", e)
    if not requests.head(f"{URL}/storage/v1/object/public/{PUBLIC}/lots.json", timeout=30).ok:
        publish()  # the first run: the app and the intel need the files before hours of reading
    before = len(glob.glob(str(ROOT / "data/batches/*/")))
    run([sys.executable, "scripts/index.py", "update", "15"], check=False)
    save()
    read()
    if len(glob.glob(str(ROOT / "data/batches/*/"))) > before:
        publish()
    log(f"finished in {(time.time() - T0) / 60:.0f} min")


if __name__ == "__main__":
    main()
