"""Build the Auction Terminal snapshot the Emperor Cardamom app reads.

    python3 terminal.py <dir1,dir2,...> <out.json> [reports_listed]

Each dir holds lots.csv and auctions.csv from export.py. Every lot is tagged:
house code, price band (bottom / middle / top third by rate inside its own
auction), slot (opening / middle / closing third of lots in sale order), and
premium (rate minus its auction's kg-weighted average).
"""
import csv, re, sys, json, datetime as D, collections as C

HOUSES = [('CPMCS', r'cardamom\s*planters.?\s*marketing|cpmcs'), ('CNS', r'climate\s*natural'), ('SSP', r'sugandhagiri'),
          ('SICOAP', r'south\s*indian\s*cardamom\s*online|sicoa'), ('KCPMC', r'kerala\s*cardamom'), ('GHCM', r'green\s*house'),
          ('SIGCL', r'south\s*indian\s*green|sigc'), ('CPA', r'cardamom\s*planters.?\s*assoc'), ('RNS', r'\brns\b'),
          ('IMCPC', r'idukki\s*mahila|imcp'), ('SIFEX', r'speciali?ty\s*indian'), ('CG', r'cardamom\s*growers'),
          ('ITCPC', r'traditional|itcpc'), ('HEADER', r'header'), ('MAS', r'\bmas\b'), ('SMTC', r'spice\s*more')]
GENERIC = {'', 'PRIVATE LIMITED', 'LIMITED', 'CARDAMOM', 'TRADERS', 'SPICES'}


def _mean(a):
    return round(sum(a) / len(a)) if a else 0


def _status(n_aucs, listed, aucs):
    import glob, os
    done = failed = 0
    for m in glob.glob('data/batches/*/manifest.json'):
        k = len(json.load(open(m)))
        if os.path.exists(os.path.join(os.path.dirname(m), 'failed.json')):
            failed += k
        else:
            done += k
    if os.path.exists('data/index.json'):
        listed = len(json.load(open('data/index.json')))
    exact = sum(1 for a in aucs if float(a.get('coverage_pct') or 0) >= 99.95)
    return dict(done=done or n_aucs, failed=failed, listed=int(listed) if listed else None, auctions=n_aucs, exact=exact)


def code(n):
    for c, r in HOUSES:
        if re.search(r, n, re.I):
            return c
    return re.sub(r'[^A-Z]', '', n.upper())[:6] or 'OTHER'


def mix(L, key, names):
    q = sum(x['q'] for x in L) or 1
    return [round(100 * sum(x['q'] for x in L if x[key] == n) / q) for n in names]


def main(dirs, out, listed=None):
    rows, aucs = [], []
    if dirs == 'ALL':
        import glob, os
        dirs = ','.join(sorted(os.path.dirname(f) for f in glob.glob('data/batches/*/lots.csv')))
    for d in dirs.split(','):
        rows += list(csv.DictReader(open(f'{d}/lots.csv')))
        aucs += list(csv.DictReader(open(f'{d}/auctions.csv')))
    for a in aucs:
        a['code'] = code(a['auctioneer'])
    for r in rows:
        r['q'], r['r'], r['v'] = float(r['qty_kg']), float(r['rate_rs']), float(r['value_rs'])
        r['code'] = code(r['auctioneer'])
        r['ln'] = int(re.sub(r'\D', '', r['lot_no']) or 0)
        r['buyer'] = r['buyer'].strip()
        r['seller'] = r['seller'].strip()
    by = C.defaultdict(list)
    for r in rows:
        by[r['auction_id']].append(r)
    for L in by.values():
        L.sort(key=lambda r: r['ln'])
        n = len(L)
        rs = sorted(x['r'] for x in L)
        t1, t2 = rs[n // 3], rs[2 * n // 3]
        avg = sum(x['v'] for x in L) / sum(x['q'] for x in L)
        for i, x in enumerate(L):
            x['pos'] = ('O', 'M', 'C')[min(2, i * 3 // n)]
            x['band'] = 'L' if x['r'] < t1 else ('H' if x['r'] >= t2 else 'M')
            x['prem'] = x['r'] - avg
            x['dec'] = min(9, i * 10 // n)
    tq = sum(r['q'] for r in rows)
    tv = sum(r['v'] for r in rows)
    mavg = tv / tq

    daily = C.defaultdict(lambda: [0.0, 0.0, 0.0, 1e9])
    for a in aucs:
        s = daily[a['date']]
        s[0] += float(a['sold_kg']); s[1] += float(a['value_rs'])
        s[2] = max(s[2], float(a['max_rs'] or 0)); s[3] = min(s[3], float(a['min_rs'] or 1e9))

    hs = C.defaultdict(lambda: dict(kg=0, v=0, arr=0, wd=0, n=0, buy=C.Counter()))
    for a in aucs:
        h = hs[a['code']]
        h['arr'] += float(a['arrivals_kg'] or 0); h['wd'] += float(a['withdrawn_kg'] or 0); h['n'] += 1
    for r in rows:
        h = hs[r['code']]
        h['kg'] += r['q']; h['v'] += r['v']; h['buy'][r['buyer']] += r['q']
    houses = sorted([dict(code=c, kg=round(h['kg']), share=round(100 * h['kg'] / tq, 1), avg=round(h['v'] / h['kg']),
                          vs=round(h['v'] / h['kg'] - mavg), wd=round(100 * h['wd'] / h['arr'], 1) if h['arr'] else 0,
                          buyers=len(h['buy']), top3=round(100 * sum(x for _, x in h['buy'].most_common(3)) / h['kg']),
                          auctions=h['n']) for c, h in hs.items() if h['kg']], key=lambda x: -x['kg'])
    codes = [h['code'] for h in houses]

    bs = C.defaultdict(list)
    for r in rows:
        if r['buyer'] not in GENERIC:
            bs[r['buyer']].append(r)

    def buyer(name, L):
        q = sum(x['q'] for x in L); v = sum(x['v'] for x in L)
        wd = C.Counter()
        for x in L:
            wd[D.date.fromisoformat(x['date']).weekday()] += x['q']
        per = []
        for c in sorted({x['code'] for x in L}, key=lambda c: -sum(x['q'] for x in L if x['code'] == c)):
            M = [x for x in L if x['code'] == c]
            mq = sum(x['q'] for x in M)
            per.append(dict(code=c, kg=round(mq), avg=round(sum(x['v'] for x in M) / mq), band=mix(M, 'band', 'LMH'), pos=mix(M, 'pos', 'OMC')))
        return dict(name=name, kg=round(q), value=round(v), avg=round(v / q), prem=round(sum(x['prem'] * x['q'] for x in L) / q),
                    lots=len(L), share=round(100 * q / tq, 2), band=mix(L, 'band', 'LMH'), pos=mix(L, 'pos', 'OMC'),
                    wd=[round(wd.get(i, 0)) for i in range(7)], houses=per)

    top = sorted(bs, key=lambda b: -sum(x['q'] for x in bs[b]))
    buyers = [buyer(b, bs[b]) for b in top[:40]]
    matrix = [[b] + [round(sum(x['q'] for x in bs[b] if x['code'] == c)) for c in codes] for b in top[:12]]

    ladder = C.Counter()
    for r in rows:
        ladder[int(r['r'] // 100) * 100] += r['q']
    curve = {c: [_mean([x["prem"] for x in rows if x["code"] == c and x["dec"] == d]) for d in range(10)] for c in codes[:6]}

    ss = C.defaultdict(list)
    for r in rows:
        if r['seller'] not in GENERIC:
            ss[r['seller']].append(r)
    sellers = []
    for s in sorted(ss, key=lambda s: -sum(x['q'] for x in ss[s]))[:15]:
        L = ss[s]; q = sum(x['q'] for x in L)
        sellers.append(dict(name=s, kg=round(q), lots=len(L), prem=round(sum(x['prem'] * x['q'] for x in L) / q),
                            high=mix(L, 'band', 'H')[0], buyers=len({x['buyer'] for x in L}), houses=len({x['code'] for x in L}),
                            top=C.Counter(x['buyer'] for x in L).most_common(1)[0][0]))
    both = sorted([dict(name=n, bought=round(sum(x['q'] for x in bs[n])), sold=round(sum(x['q'] for x in ss[n]))) for n in set(bs) & set(ss)],
                  key=lambda x: -(x['bought'] + x['sold']))[:8]
    bq = sorted((sum(x['q'] for x in L) for L in bs.values()), reverse=True)
    lead = C.Counter()
    for L in by.values():
        m = max(L, key=lambda x: x['r'])
        if m['buyer'] not in GENERIC:
            lead[m['buyer']] += 1
    odd = sorted([x for x in rows if x['prem'] > 700 or x['prem'] < -900], key=lambda x: -abs(x['prem']))
    big = max(by, key=lambda k: len(by[k])); R = by[big]

    snap = dict(
        built=D.datetime.now(D.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        status=_status(len(aucs), listed, aucs),
        kpi=dict(reports=len(aucs), lots=len(rows), kg=round(tq), value=round(tv), avg=round(mavg, 1),
                 buyers=len(bs), sellers=len(ss), houses=len(codes), first=min(a['date'] for a in aucs), last=max(a['date'] for a in aucs)),
        daily=[dict(date=k, kg=round(v[0]), avg=round(v[1] / v[0], 1), hi=v[2], lo=v[3]) for k, v in sorted(daily.items()) if v[0]],
        houses=houses, buyers=buyers, matrix=dict(houses=codes, rows=matrix),
        ladder=[[k, round(v)] for k, v in sorted(ladder.items())], curve=curve, sellers=sellers, both=both,
        conc=dict(top5=round(100 * sum(bq[:5]) / tq, 1), top10=round(100 * sum(bq[:10]) / tq, 1), top20=round(100 * sum(bq[:20]) / tq, 1)),
        leaders=lead.most_common(6),
        odd=dict(n=len(odd), ex=[dict(code=x['code'], date=x['date'], lot=x['lot_no'], buyer=x['buyer'], rate=round(x['r']), prem=round(x['prem'])) for x in odd[:6]]),
        replay=dict(code=R[0]['code'], date=R[0]['date'], avg=round(sum(x['v'] for x in R) / sum(x['q'] for x in R)), rates=[round(x['r']) for x in R]),
    )
    json.dump(snap, open(out, 'w'), separators=(',', ':'))
    print(out, len(json.dumps(snap)), 'bytes', len(aucs), 'reports', len(rows), 'lots')


if __name__ == '__main__':
    main(*sys.argv[1:4])
