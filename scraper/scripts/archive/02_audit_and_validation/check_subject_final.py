import sys
import os
import json

sys.path.append(os.getcwd())

from sqlalchemy import text
from db.session import engine

with open("data/listing_snapshot_v2.json", encoding="utf-8") as f:
    rows = json.load(f)

sv = {
    int(j["sinta_journal_id"]): (j.get("subject") or None)
    for j in rows
}

with engine.connect() as c:
    db = {
        r[0]: r[1]
        for r in c.execute(
            text("SELECT id, subject FROM journals")
        )
    }

both = [i for i in db if i in sv]
db_only_ids = sorted(set(db) - set(sv))
snapshot_only_ids = sorted(set(sv) - set(db))

print("ID hanya di DB:", len(db_only_ids), db_only_ids[:20])
print("ID hanya di snapshot:", len(snapshot_only_ids), snapshot_only_ids[:20])
snap_has = [i for i in both if sv[i]]
diff = [i for i in snap_has if db[i] != sv[i]]
db_only = [i for i in both if not sv[i] and db[i]]
empty = [i for i in both if not sv[i] and not db[i]]

print("Dibandingkan:", len(both), "| SINTA punya subject:", len(snap_has))
print("Beda dari DB:", len(diff), diff[:10])
print("SINTA kosong, DB punya:", len(db_only), db_only[:10])
print("Kosong di keduanya:", len(empty))