import sys, os, json
from collections import defaultdict
sys.path.append(os.getcwd())
from sqlalchemy import text
from db.session import engine

d = json.load(open("data/listing_snapshot_v2.json", encoding="utf-8"))
rows = d["rows"] if isinstance(d, dict) else d

with engine.connect() as c:
    pid = {r[0]: r[1] for r in c.execute(text(
        "SELECT j.id, p.sinta_publisher_id FROM journals j LEFT JOIN publishers p ON p.id = j.publisher_id"))}

def has_id(r):
    return str(r.get("sinta_publisher_id") or "").isdigit()

hashed = [r for r in rows if r.get("publisher_name") and not has_id(r)]
got = [r for r in hashed if pid.get(int(r["sinta_journal_id"])) is not None]
print("Bernama penerbit tapi tautan '#!'   :", len(hashed))
print("  ...yang di DB punya ID penerbit   :", len(got))
print("  contoh:", [(r["sinta_journal_id"], r["publisher_name"], pid[int(r["sinta_journal_id"])]) for r in got[:5]])

names = defaultdict(int)
for r in rows:
    if str(r.get("sinta_publisher_id")) == "9":
        names[r["publisher_name"]] += 1
print("\nNama mentah di bawah ID 9:", len(names))
for n, k in sorted(names.items(), key=lambda x: -x[1])[:5]:
    print("  ", k, "|", n)

print("\nJurnal bernama UGM, tautan bukan 384:")
for r in rows:
    if r.get("publisher_name") == "Universitas Gadjah Mada" and str(r.get("sinta_publisher_id")) in ("8151", "8174"):
        print("  ", r["sinta_journal_id"], "|", r["name"], "| tautan:", r["sinta_publisher_id"])