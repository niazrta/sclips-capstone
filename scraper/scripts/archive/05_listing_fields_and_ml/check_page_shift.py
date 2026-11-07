import sys, os, json
sys.path.append(os.getcwd())

def load(p):
    d = json.load(open(p, encoding="utf-8"))
    rows = d["rows"] if isinstance(d, dict) else d
    return [int(r["sinta_journal_id"]) for r in rows], rows

a_ids, _ = load("data/listing_snapshot.json")
b_ids, b_rows = load("data/listing_snapshot_v2.json")
pa = {j: i // 10 + 1 for i, j in enumerate(a_ids)}
pb = {j: i // 10 + 1 for i, j in enumerate(b_ids)}
common = set(pa) & set(pb)
moved = [j for j in common if pa[j] != pb[j]]
print("Jurnal di kedua snapshot:", len(common), "| pindah halaman:", len(moved))
print("Selisih halaman terbesar:", max((abs(pa[j] - pb[j]) for j in moved), default=0))

imp = [r.get("impact") for r in b_rows if r.get("impact") is not None]
inv = sum(1 for x, y in zip(imp, imp[1:]) if y > x)
print("Urutan impact menaik (pelanggaran urutan menurun):", inv, "dari", len(imp) - 1)