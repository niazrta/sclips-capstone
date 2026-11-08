import sys, os, json, re
sys.path.append(os.getcwd())
from sqlalchemy import text
from db.session import engine

d = json.load(open("data/listing_snapshot_v2.json", encoding="utf-8"))
rows = d["rows"] if isinstance(d, dict) else d
snap = {int(r["sinta_journal_id"]): r for r in rows}
with engine.connect() as c:
    db = {r[0]: (r[1], r[2]) for r in c.execute(text("SELECT id, e_issn, p_issn FROM journals"))}

for k, idx in (("e_issn", 0), ("p_issn", 1)):
    hit = []
    for i, vals in db.items():
        v = vals[idx]
        raw = re.sub(r"[^0-9Xx]", "", str(snap.get(i, {}).get(k) or ""))
        if v and v.upper().endswith("X") and len(raw) == 7 and raw.isdigit():
            hit.append((i, raw, v))
    print(k, "X ditambahkan oleh kode kita:", len(hit), hit[:10])