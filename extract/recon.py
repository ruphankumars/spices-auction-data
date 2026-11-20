import sqlite3,sys; c=sqlite3.connect(sys.argv[1])
T=S=0
for aid,sold,val,st in c.execute("select auction_id,sold_kg,value_rs,summary_source from auctions").fetchall():
    q,v,n=c.execute("select sum(qty_kg),sum(value_rs),count(*) from lots where auction_id=?",(aid,)).fetchone()
    T+=sold; S+=min(q,sold)
    print(f"{aid[:26]:26s} {st:6s} lots={n:4d} kg {100*q/sold:6.2f}%  dq={q-sold:9.1f} dv={v-val:13.1f}")
print(f"overall {100*S/T:.2f}%")
