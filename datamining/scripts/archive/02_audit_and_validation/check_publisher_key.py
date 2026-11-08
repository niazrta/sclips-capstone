import json
from collections import defaultdict

d = json.load(open("data/listing_snapshot_v2.json", encoding="utf-8"))
rows = d["rows"] if isinstance(d, dict) else d


def sid(r):
    s = str(r.get("sinta_publisher_id") or "")
    return s if s.isdigit() else None


named = [r for r in rows if r.get("publisher_name")]
raw = {r["publisher_name"] for r in named}
loose = {" ".join(n.split()).casefold() for n in raw}
print("Jurnal bernama penerbit                 :", len(named))
print("Nama mentah unik (persis)               :", len(raw))
print("Nama unik (abaikan besar-kecil/spasi)   :", len(loose))

ids_by_raw, raws_by_id = defaultdict(set), defaultdict(set)
for r in named:
    i = sid(r)
    if i:
        ids_by_raw[r["publisher_name"]].add(i)
        raws_by_id[i].add(r["publisher_name"])
no_id = {r["publisher_name"] for r in named if not sid(r)}
print("ID afiliasi unik                        :", len(raws_by_id))
print("Nama mentah dengan >1 ID                :", sum(len(v) > 1 for v in ids_by_raw.values()))
print("ID dengan >1 nama mentah                :", sum(len(v) > 1 for v in raws_by_id.values()))
print("Nama mentah tanpa ID                    :", len(no_id))
print("  ...yang juga dipakai jurnal ber-ID    :", len(no_id & set(ids_by_raw)))
for n, v in [(n, v) for n, v in ids_by_raw.items() if len(v) > 1][:5]:
    print("  contoh:", n, sorted(v))