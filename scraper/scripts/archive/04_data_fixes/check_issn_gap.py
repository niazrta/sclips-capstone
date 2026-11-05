import sys, os, json
sys.path.append(os.getcwd())
from scraper.cleaner import clean_issn, issn_check_char

with open("data/listing_snapshot.json", encoding="utf-8") as f:
    snap = json.load(f)

for field in ("e_issn", "p_issn"):
    odd = [(j["sinta_journal_id"], j[field]) for j in snap
           if j.get(field)
           and len(j[field].replace("-", "")) == 7
           and j[field].replace("-", "").isdigit()
           and issn_check_char(j[field].replace("-", "")) != "X"]
    print(field, len(odd), odd[:8])