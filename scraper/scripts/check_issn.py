import sys, os, json
from collections import Counter
sys.path.append(os.getcwd())
from scraper.cleaner import clean_issn

with open("data/listing_snapshot.json", encoding="utf-8") as f:
    snap = json.load(f)

for field in ("p_issn", "e_issn"):
    raw = [j.get(field) for j in snap]
    present = [r for r in raw if r]
    valid = [r for r in present if clean_issn(r)]
    seven = [r for r in present if len(r.replace("-", "")) == 7]
    other = [r for r in present if not clean_issn(r) and r not in seven]
    print(f"\n{field}: kosong {len(raw)-len(present)} | terisi {len(present)} | valid {len(valid)} | 7 digit {len(seven)} | tidak valid lain {len(other)}")
    print("  contoh 7 digit:", seven[:5])
    print("  contoh lain   :", Counter(other).most_common(5))