import sys, os, re, json
sys.path.append(os.getcwd())
from sqlalchemy import text
from db.session import engine

d = json.load(open("data/listing_snapshot_v2.json", encoding="utf-8"))
rows = d["rows"] if isinstance(d, dict) else d
snap = {int(r["sinta_journal_id"]): r["name"] for r in rows}
with engine.connect() as c:
    db = {r[0]: r[1] for r in c.execute(text("SELECT id, name FROM journals"))}

diff = [(i, db[i], snap[i]) for i in db if i in snap and db[i] != snap[i]]
print("Nama beda (DB vs snapshot 3 Nov):", len(diff))
for i, a, b in diff[:40]:
    print(f"  {i}\n    DB   : {a!r}\n    SINTA: {b!r}")

ws = [i for i, n in snap.items() if re.search(r"\s{2,}|[\r\n\t]", n)]
print("\nNama di SINTA dengan spasi ganda/baris baru:", len(ws), ws[:10])
moj = [i for i, n in snap.items() if re.search(r"[ÃÂâ]", n)]
print("Nama dengan pola mojibake di SINTA:", len(moj))