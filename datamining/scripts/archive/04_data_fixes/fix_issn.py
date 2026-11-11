import sys, os, json, argparse

sys.path.append(os.getcwd())

from db.session import SessionLocal
from db.models import Journal
from scraper.cleaner import clean_issn

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

with open("data/listing_snapshot.json", encoding="utf-8") as f:
    snap = json.load(f)

by_id = {
    int(j["sinta_journal_id"]): j
    for j in snap
    if j.get("sinta_journal_id")
}

stats = {
    k: 0 for k in (
        "e_terisi", "e_diubah", "e_jadi_kosong",
        "p_terisi", "p_diubah", "p_jadi_kosong"
    )
}

db = SessionLocal()

try:
    for row in db.query(Journal).all():
        j = by_id.get(row.id)

        if not j:
            continue

        for field, key in (("e_issn", "e"), ("p_issn", "p")):
            new = clean_issn(j.get(field))
            old = getattr(row, field)

            if new == old:
                continue

            if old is None:
                stats[key + "_terisi"] += 1
            elif new is None:
                stats[key + "_jadi_kosong"] += 1
            else:
                stats[key + "_diubah"] += 1

            setattr(row, field, new)

    for k, v in stats.items():
        print(f"{k:15}: {v}")

    if args.apply:
        db.commit()
        print("Tersimpan.")
    else:
        db.rollback()
        print("DRY-RUN: tidak ada yang diubah.")

finally:
    db.close()