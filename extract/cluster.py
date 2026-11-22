"""Group the many printed spellings of one firm (OCR noise, cut-off cells, wrapped cells).

cluster(names, qty) -> {index: canonical index}; index 0 (unread) is left alone.
"""
import re, difflib, collections as C

SUFFIX = ['TRADERS', 'TRADING', 'EXPORTS', 'EXPORT', 'IMPEX', 'SPICES', 'AGENCIES', 'AGENCY', 'ENTERPRISES', 'ENTERPRISE', 'COMPANY',
          'LIMITED', 'PRIVATE', 'PLANTATIONS', 'PLANTATION', 'ESTATE', 'ESTATES', 'INTERNATIONAL', 'INDUSTRIES', 'CORPORATION', 'MARKETING',
          'PRODUCTS', 'FOODS', 'MASALA', 'STORES', 'BROTHERS', 'SONS', 'GROUP', 'OVERSEAS', 'GLOBAL', 'CARDAMOM', 'CARDAMOMS', 'ELAICHI']
STOP_AFTER = set(SUFFIX) | {'PVT', 'LTD', 'CO', 'AND', 'LLP'}
HONOR = {'SRI', 'SREE', 'SHRI', 'SHREE', 'SIR', 'SAR', 'SER', 'SRE', 'SAZ', 'SAY', 'JSAY', 'ISE', 'ISER', 'SPY', 'SR', 'SRL', 'SRT', 'SRJ', 'MS', 'M', 'S', 'THE'}
GENERIC = {'CARDAMOM', 'TRADING', 'TRADERS', 'PROCESSING', 'MOHAMMED', 'MOHAMED', 'SPICES', 'GREEN', 'GOLDEN', 'ROYAL', 'NEW', 'SAI', 'SIVA', 'SHIVA', 'GANESH', 'MURUGAN', 'LAKSHMI', 'SRI', 'ESTATE'}
CANON = {'TRADING': 'TRADERS', 'EXPORT': 'EXPORTS', 'AGENCY': 'AGENCIES', 'ENTERPRISE': 'ENTERPRISES', 'PLANTATION': 'PLANTATIONS',
         'ESTATES': 'ESTATE', 'CARDAMOMS': 'CARDAMOM', 'PVT': 'PRIVATE', 'LTD': 'LIMITED', 'CO': 'COMPANY'}


def _suffix_of(tok):
    """A token that is a cut-off or garbled form of a business word (TRADI, EXPOR, TRADERE...)."""
    if tok in CANON: return CANON[tok]
    if tok in STOP_AFTER: return tok
    if len(tok) >= 4:
        for s in SUFFIX:
            if s.startswith(tok) or (len(tok) >= 6 and difflib.SequenceMatcher(None, tok, s).ratio() >= 0.8):
                return CANON.get(s, s)
    return None


def key(name):
    """(core, suffix): core = the firm's own words, honorifics and everything after the business word dropped."""
    t = re.sub(r"[^A-Z0-9 ]", " ", name.upper().replace('&', ' AND ')).split()
    while len(t) > 1 and t[0] in HONOR and not _suffix_of(t[1]):
        t = t[1:]
    core, suf = [], ''
    for i, w in enumerate(t):
        s = _suffix_of(w)
        if s and core:
            suf = s; break
        # a business word glued to the core: VREXPORTS, YOGAGANAPATHITRADERS
        m = next((x for x in SUFFIX if len(w) > len(x) + 1 and w.endswith(x)), None)
        if m and not core:
            core.append(w[:-len(m)]); suf = CANON.get(m, m); break
        core.append(w)
    c = ''.join(core)
    if c.startswith('SRI') and len(c) >= 9: c = c[3:]          # SRIYOGAGANAPATHI
    return c, suf


def cluster(names, qty):
    keys = {i: key(n) for i, n in enumerate(names) if i}
    par = {i: i for i in keys}
    def f(x):
        while par[x] != x: par[x] = par[par[x]]; x = par[x]
        return x
    def u(a, b):
        a, b = f(a), f(b)
        if a != b:
            if qty.get(a, 0) < qty.get(b, 0): a, b = b, a
            par[b] = a
    by = C.defaultdict(list)
    for i, (c, s) in keys.items():
        if len(c) >= 2: by[(c, s)].append(i)
    reps = {}
    for k, g in by.items():
        for x in g[1:]: u(g[0], x)
        reps[k] = g[0]
    items = sorted(reps.items(), key=lambda kv: kv[0][0])
    ok = lambda c: len(c) >= 5 and c not in GENERIC and c not in SUFFIX
    block = C.defaultdict(list)
    for (c, s_), i in items:
        if ok(c): block[c[:3]].append((c, s_, i))
    # 1. near-identical spellings with the same business word (YOGAGAMAPATHI / YOGAGANAPATHI TRADERS)
    for g in block.values():
        for a in range(len(g)):
            ca, sa, ia = g[a]
            for b in range(a + 1, len(g)):
                cb, sb, ib = g[b]
                if sa != sb: continue
                short, long_ = sorted((ca, cb), key=len)
                if abs(len(ca) - len(cb)) > max(2, 0.25 * len(long_)): continue
                need = 0.80 if len(short) >= 10 else 0.86 if len(short) >= 7 else 0.95
                sm = difflib.SequenceMatcher(None, ca, cb)
                if sm.real_quick_ratio() >= need and sm.quick_ratio() >= need and sm.ratio() >= need:
                    u(ia, ib)
    # 2. cut-off cells: a name of 7+ letters that starts exactly one longer firm's name
    roots = C.defaultdict(set)
    for (c, s_), i in items:
        if ok(c): roots[c].add(f(i))
        if s_ and len(c) >= 2: roots[c + s_].add(f(i))       # VR + EXPORTS = VREXPORTS, so VREXPOR can find it
    allk = sorted(roots)
    import bisect
    for (c, s_), i in items:
        if s_ or not ok(c) or len(c) < 7: continue   # only a name with no business word can be a cut-off one
        lo = bisect.bisect_right(allk, c); longer = set(roots[c])   # same words, with a business word
        while lo < len(allk) and allk[lo].startswith(c):
            longer |= {f(r) for r in roots[allk[lo]]}; lo += 1
        longer.discard(f(i))
        if len(longer) == 1:
            u(i, longer.pop())
    # 3. a garbled honorific (SAI, SNR, ISR, SRR before a long name): the name without it, when that long
    #    name is already known with the same business word
    bycore = C.defaultdict(list)
    for (c, s_), i in items:
        if ok(c): bycore[c[:3]].append((c, s_, i))
    for i, n in enumerate(names):
        if not i: continue
        t = re.sub(r"[^A-Z0-9 ]", " ", n.upper()).split()
        if len(t) < 2 or len(t[0]) > 3: continue
        c2, s2 = key(' '.join(t[1:]))
        if len(c2) < 8 or not ok(c2): continue
        for c, s_, j in bycore.get(c2[:3], []):
            if s_ != s2 or f(j) == f(i): continue
            if c == c2 or difflib.SequenceMatcher(None, c, c2).ratio() >= 0.9:
                u(j, i); break
    return {i: f(i) for i in keys}
