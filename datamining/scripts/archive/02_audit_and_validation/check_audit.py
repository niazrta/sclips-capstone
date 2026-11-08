import sys, os, json
sys.path.append(os.getcwd())

from sqlalchemy import text
from config import config
from db.session import engine
from scraper.cleaner import clean_issn

with open("data/listing_snapshot.json", encoding="utf-8") as f:
    snap = json.load(f)

by_id = {int(j["sinta_journal_id"]): j for j in snap if j.get("sinta_journal_id")}
no_eissn = {i for i, j in by_id.items() if not clean_issn(j.get("e_issn"))}

with engine.connect() as conn:
    rows = conn.execute(text("SELECT id, name FROM journals")).fetchall()
db_names = {r[0]: r[1] for r in rows}

missing = set(by_id) - set(db_names)
extra = sorted(set(db_names) - set(by_id))
missing_with_eissn = sorted(i for i in missing if i not in no_eissn)

# baris yang namanya beda dari SINTA = kandidat baris campuran (tertimpa)
mismatch = sorted(i for i in db_names
                  if i in by_id and (db_names[i] or "").strip() != by_id[i]["name"].strip())

print("Jurnal di SINTA tanpa e-ISSN valid     :", len(no_eissn))
print("Jurnal hilang di DB                    :", len(missing))
print("  - yang tanpa e-ISSN                  :", len(missing) - len(missing_with_eissn))
print("  - yang PUNYA e-ISSN                  :", len(missing_with_eissn), missing_with_eissn[:10])
print("Baris DB dengan nama beda dari SINTA   :", len(mismatch), mismatch[:10])
print("\nID di DB tapi tidak di listing:")
for i in extra:
    print(f"  {i} | {db_names[i]} | {config.SINTA_BASE_URL}/journals/profile/{i}")