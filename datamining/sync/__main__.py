import argparse

from sync import engine

ap = argparse.ArgumentParser(prog="python -m sync",
                             description="Sinkronisasi data jurnal dari SINTA. Tanpa --apply hanya simulasi.")
ap.add_argument("--scope", choices=["update", "full"], required=True,
                help="update: perbarui jurnal yang sudah ada | full: update + jurnal baru + jurnal yang hilang")
ap.add_argument("--apply", action="store_true", help="simpan perubahan ke database")
ap.add_argument("--offline", action="store_true", help="sama dengan --from-dir data/raw_listing, hanya simulasi")
ap.add_argument("--from-dir", default=None, help="baca listing dari salinan")
ap.add_argument("--max-age-hours", type=float, default=24, help="umur maksimal salinan listing bila --apply")
ap.add_argument("--save-dir", default=None, help="simpan listing yang dibaca ke folder ini")
ap.add_argument("--limit", type=int, default=None, help="update: hanya terapkan N jurnal pertama (uji)")
ap.add_argument("--ids", default=None, help="update: hanya jurnal ber-ID ini, pisah koma (satu ID = update per jurnal)")
ap.add_argument("--profile", action="store_true",
                help="update per jurnal lewat halaman profil saja (cepat); wajib dengan --ids")
a = ap.parse_args()

if a.apply and a.offline:
    ap.error("--offline hanya boleh simulasi")
if a.scope != "update" and (a.limit or a.ids):
    ap.error("--limit dan --ids hanya untuk --scope update")
if a.profile and (not a.ids or a.offline or a.from_dir):
    ap.error("--profile wajib dengan --ids dan tidak bisa offline")
from_dir = a.from_dir or ("data/raw_listing" if a.offline else None)
ids = {int(x) for x in a.ids.split(",")} if a.ids else None

engine.run(a.scope, apply=a.apply, from_dir=from_dir, save_dir=a.save_dir, limit=a.limit, ids=ids,
           max_age_hours=a.max_age_hours, source="profile" if a.profile else None)
