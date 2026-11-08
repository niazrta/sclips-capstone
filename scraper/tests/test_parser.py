import sys, os, gzip, glob
sys.path.append(os.getcwd())
from sqlalchemy import text
from db.session import engine
from scraper.sinta_scraper import parse_listing_page

parsed = {}
DIR = sys.argv[1] if len(sys.argv) > 1 else "data/raw_listing"
for path in glob.glob(os.path.join(DIR, "page_*.html.gz")):
    for r in parse_listing_page(gzip.open(path, "rt", encoding="utf-8").read()):
        parsed[r["sinta_journal_id"]] = r

with engine.connect() as c:
    db = {r[0]: r for r in c.execute(text(
        "SELECT j.id, j.name, j.e_issn, j.e_issn_status, j.p_issn, j.p_issn_status, "
        "j.sinta_affiliation_id, j.subject, p.name FROM journals j "
        "LEFT JOIN publishers p ON p.id = j.publisher_id"))}

print("Jurnal terbaca parser :", len(parsed))
print("ID di DB tapi tidak di parser:", sorted(set(db) - set(parsed)))
print("ID di parser tapi tidak di DB:", len(set(parsed) - set(db)))

fields = {"name": 1, "e_issn": 2, "e_issn_status": 3, "p_issn": 4, "p_issn_status": 5,
          "sinta_publisher_id": 6, "publisher_name": 8}
diff = {k: [] for k in fields}
subj_new, subj_lost = 0, 0
for i, r in parsed.items():
    if i not in db:
        continue
    for k, idx in fields.items():
        if r.get(k) != db[i][idx]:
            diff[k].append((i, db[i][idx], r.get(k)))
    if r.get("subject") != db[i][7]:
        subj_lost += 1 if r.get("subject") is None else 0
        subj_new += 0 if r.get("subject") is None else 1

for k, v in diff.items():
    print(f"Beda {k:20}: {len(v)}", v[:3])
print("Subject beda (parser punya nilai) :", subj_new)
print("Subject kosong di parser, ada di DB:", subj_lost)