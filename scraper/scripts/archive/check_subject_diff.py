import sys, os, json
sys.path.append(os.getcwd())
from sqlalchemy import text
from db.session import engine

with open("data/listing_snapshot.json", encoding="utf-8") as f:
    snap = json.load(f)
by_id = {int(j["sinta_journal_id"]): j for j in snap if j.get("sinta_journal_id")}

with engine.connect() as conn:
    db = {r[0]: r[1] for r in conn.execute(text("SELECT id, subject FROM journals"))}

diff = [(i, db[i], by_id[i]["subject"]) for i in db
        if i in by_id and by_id[i].get("subject") and db[i] != by_id[i]["subject"]]
old_null = [d for d in diff if not d[1]]
old_text = [d for d in diff if d[1]]
only_space = [d for d in old_text if " ".join(d[1].split()) == " ".join(d[2].split())]

print("Total beda               :", len(diff))
print("DB kosong, SINTA ada     :", len(old_null))
print("DB ada isi, isinya beda  :", len(old_text), "| beda cuma spasi:", len(only_space))
for i, o, n in old_text[:8]:
    print(f"\n{i}\n  DB   : {o}\n  SINTA: {n}")