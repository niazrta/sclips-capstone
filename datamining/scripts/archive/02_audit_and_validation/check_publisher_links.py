import sys, os, json, re
from collections import Counter, defaultdict
sys.path.append(os.getcwd())
from scraper.cleaner import normalize_publisher_name

data = json.load(open("data/listing_snapshot_v2.json", encoding="utf-8"))
rows = data["rows"] if isinstance(data, dict) else data

no_id = [r for r in rows if not str(r.get("sinta_publisher_id") or "").isdigit()]
print("Jurnal di snapshot              :", len(rows))
print("Tanpa ID penerbit numerik       :", len(no_id))
print("Nilai mentah ID (5 teratas)     :", Counter(str(r.get("sinta_publisher_id")) for r in no_id).most_common(5))
print("Tanpa nama penerbit sama sekali :", sum(1 for r in rows if not r.get("publisher_name")))
print("Penerbit unik tanpa ID          :", len({r.get("publisher_name") for r in no_id}))

ids_by_name = defaultdict(set)
for r in rows:
    sid = str(r.get("sinta_publisher_id") or "")
    if r.get("publisher_name") and sid.isdigit():
        ids_by_name[normalize_publisher_name(r["publisher_name"])].add(sid)
merged = {n: s for n, s in ids_by_name.items() if len(s) > 1}
print("\nNama (setelah normalisasi) yang memuat >1 ID afiliasi:", len(merged))
for n, s in list(merged.items())[:5]:
    print("  ", n, sorted(s))