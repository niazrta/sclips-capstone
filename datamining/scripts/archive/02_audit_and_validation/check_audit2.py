import sys, os, json
sys.path.append(os.getcwd())
from collections import defaultdict
from sqlalchemy import text
from db.session import engine
from scraper.cleaner import clean_issn

with open("data/listing_snapshot.json", encoding="utf-8") as f:
    snap = json.load(f)
by_id = {int(j["sinta_journal_id"]): j for j in snap if j.get("sinta_journal_id")}

with engine.connect() as conn:
    rows = conn.execute(text("SELECT id, name FROM journals")).fetchall()
db = {r[0]: r[1] for r in rows}

groups = defaultdict(list)
for i, j in by_id.items():
    e = clean_issn(j.get("e_issn"))
    if e:
        groups[e].append(i)
dups = {e: ids for e, ids in groups.items() if len(ids) > 1}
print("e-ISSN yang dipakai >1 jurnal di SINTA:", len(dups))

missing_e = [i for i in by_id if i not in db and clean_issn(by_id[i].get("e_issn"))]
explained = [i for i in missing_e if len(groups[clean_issn(by_id[i]["e_issn"])]) > 1]
print("Hilang ber-e-ISSN:", len(missing_e), "| e-ISSN dipakai jurnal lain:", len(explained))
for i in missing_e:
    if i not in explained:
        print("  belum terjelaskan:", i, by_id[i]["name"], by_id[i].get("e_issn"))

print("\nBaris nama beda (DB vs SINTA):")
for i in sorted(db):
    if i in by_id and (db[i] or "").strip() != by_id[i]["name"].strip():
        print(f"  {i}\n    DB   : {db[i]}\n    SINTA: {by_id[i]['name']}")