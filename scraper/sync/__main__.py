import argparse

from sync import engine

ap = argparse.ArgumentParser(prog="python -m sync")
ap.add_argument("--scope", choices=["update"], required=True)  # new dan full menyusul
ap.add_argument("--apply", action="store_true")
ap.add_argument("--offline", action="store_true", help="sama dengan --from-dir data/raw_listing, hanya dry-run")
ap.add_argument("--from-dir", default=None, help="baca listing dari salinan (umur maksimal 24 jam bila --apply)")
ap.add_argument("--save-dir", default=None, help="simpan listing yang dibaca ke folder ini")
ap.add_argument("--limit", type=int, default=None, help="hanya terapkan N jurnal pertama (uji)")
ap.add_argument("--ids", default=None, help="hanya terapkan jurnal ber-ID ini, pisah koma (uji)")
a = ap.parse_args()

if a.apply and a.offline:
    ap.error("--offline hanya boleh dry-run")
from_dir = a.from_dir or ("data/raw_listing" if a.offline else None)
ids = {int(x) for x in a.ids.split(",")} if a.ids else None
engine.run_update(apply=a.apply, from_dir=from_dir, save_dir=a.save_dir, limit=a.limit, ids=ids)