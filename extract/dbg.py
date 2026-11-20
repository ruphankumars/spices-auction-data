import json, os, sys, math
import build_db as B
truth=json.load(open('truth_batch1.json'))
O=os.environ.get('O',"/home/claude/ocr1/out,/home/claude/ocr2/out,/home/claude/ocrm/out/passC,/home/claude/ocrm/out/passD,/home/claude/ocrm/out/passE")
for rid in sys.argv[1:]:
    rid=[k for k in truth if k.startswith(rid)][0]
    s=truth[rid][0]
    rows,cands,_wd=B.extract_report(",".join(os.path.join(o,rid) for o in O.split(',')), s['min'], s['max'])
    rows=[l for l in rows if s['min']-0.5<=l['r']<=s['max']+0.5]
    rows.sort(key=lambda r:(-r["full"],-r["score"],-r["votes"]))
    S=[];U=[]
    for r in rows:
        (S if r["score"]>=5 or (B.strong(r) and not any(B.clashes(r,k) for k in S)) else U).append(r)
    print(rid[:12],'S',len(S),round(sum(r['q'] for r in S),1),'U',len(U),round(sum(r['q'] for r in U),1),'need',round(s['sold']-sum(r['q'] for r in S),1), round(s['value']-sum(r['v'] for r in S),1))
    for u in U[:int(os.environ.get('N','12'))]:
        cl=[k for k in S if B.clashes(u,k)]
        print('    U',u['q'],u['r'],u['v'],'f',u['full'],'sc',u['score'],'vo',u['votes'],'|',u['line'][:60],'|| clash:',[(k['q'],k['r'],k['score'],k['votes']) for k in cl][:2])
