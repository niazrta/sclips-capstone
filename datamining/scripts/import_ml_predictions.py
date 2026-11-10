"""Impor hasil prediksi ML dari berkas (CSV atau xlsx sheet 1_Untuk_Data_Mining).

Tanpa --apply: simulasi, semua perubahan dibatalkan.
Kolom subject (asli SINTA) dijaga: bila hash-nya berubah, impor dibatalkan.
"""
import argparse
import os
import sys

sys.path.append(os.getcwd())

import pandas as pd
from sqlalchemy import text

from db.models import Journal
from db.session import SessionLocal
from sync.ml import save_predictions

SHEET = "1_Untuk_Data_Mining"
SUBJ_HASH = "SELECT md5(string_agg(COALESCE(subject,''), '|' ORDER BY id)) FROM journals"

ap = argparse.ArgumentParser()
ap.add_argument("file", help="CSV atau xlsx dari tim ML")
ap.add_argument("--apply", action="store_true")
a = ap.parse_args()

if a.file.lower().endswith((".xlsx", ".xls")):
    df = pd.read_excel(a.file, sheet_name=SHEET)
else:
    df = pd.read_csv(a.file, encoding="utf-8-sig")
df = df[df["journal_id"].notna()]
results = df.astype(object).where(df.notna(), None).to_dict("records")
print("Baris pada berkas:", len(results))

db = SessionLocal()
try:
    ids = {int(r["journal_id"]) for r in results}
    in_db = {i for (i,) in db.query(Journal.id).filter(Journal.id.in_(ids)).all()}
    print("ID tidak ada di database (dilewati):", len(ids - in_db), sorted(ids - in_db)[:10])
    before = db.execute(text(SUBJ_HASH)).scalar()
    nj, npub = save_predictions(db, [r for r in results if int(r["journal_id"]) in in_db])
    db.flush()
    after = db.execute(text(SUBJ_HASH)).scalar()
    print("Jurnal diberi prediksi :", nj)
    print("Penerbit diberi tipe   :", npub)
    print("Kolom subject tidak berubah:", before == after)
    if before != after:
        raise SystemExit("subject berubah, dibatalkan")
    if a.apply:
        db.commit()
        print("TERSIMPAN")
    else:
        db.rollback()
        print("SIMULASI: tidak ada yang diubah. Tambahkan --apply untuk menyimpan.")
except BaseException:
    db.rollback()
    raise
finally:
    db.close()
