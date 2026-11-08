import sys, os, argparse
sys.path.append(os.getcwd())
from datetime import datetime, timezone
import pandas as pd
from sqlalchemy import text
from db.session import engine

ap = argparse.ArgumentParser()
ap.add_argument("csv")
ap.add_argument("--apply", action="store_true")
a = ap.parse_args()

UNKNOWN_PUBLISHER = 73  # penerbit palsu "Unknown", tidak diberi tipe
df = pd.read_csv(a.csv, encoding="utf-8-sig")
now = datetime.now(timezone.utc)

jrows = [{"id": int(r.journal_id), "s1": r.predicted_subject_sinta,
          "s2": r.predicted_subject_sinta_multilabel, "s3": r.predicted_subject_scopus,
          "s4": r.predicted_subject_scopus_27, "c": float(r.scopus_confidence_score), "ts": now}
         for r in df.itertuples()]

pub = df[df["publisher_id"].notna() & df["predicted_publisher_type"].notna()
         & (df["publisher_id"] != UNKNOWN_PUBLISHER)]
skipped = df[df["publisher_id"].notna() & df["predicted_publisher_type"].isna()]
print("Punya penerbit tapi tanpa tipe dari ML (dilewati):", len(skipped), sorted(skipped["journal_id"])[:10])
prows = [{"id": int(i), "t": g["predicted_publisher_type"].iloc[0],
          "sz": g["publisher_size"].iloc[0],
          "c": float(g["publisher_classification_confidence"].iloc[0])}
         for i, g in pub.groupby("publisher_id")]

SUBJ_HASH = "SELECT md5(string_agg(COALESCE(subject,''), '|' ORDER BY id)) FROM journals"

conn = engine.connect()
tx = conn.begin()
try:
    before = conn.execute(text(SUBJ_HASH)).scalar()
    conn.execute(text("""UPDATE journals SET predicted_subject_sinta=:s1,
        predicted_subject_sinta_multilabel=:s2, predicted_subject_scopus=:s3,
        predicted_subject_scopus_27=:s4, scopus_confidence=:c, predictions_updated_at=:ts
        WHERE id=:id"""), jrows)
    conn.execute(text("""UPDATE publishers SET type=:t, publisher_size=:sz, type_confidence=:c
        WHERE id=:id"""), prows)
    after = conn.execute(text(SUBJ_HASH)).scalar()

    q = lambda s: conn.execute(text(s)).scalar()
    print("Jurnal diberi prediksi        :", q("SELECT COUNT(*) FROM journals WHERE predicted_subject_sinta IS NOT NULL"))
    print("Penerbit diberi tipe          :", q("SELECT COUNT(*) FROM publishers WHERE type IS NOT NULL"))
    print("Penerbit 73 punya tipe        :", q("SELECT COUNT(*) FROM publishers WHERE id = 73 AND type IS NOT NULL"))
    print("Jurnal tanpa penerbit + tipe  :", q("SELECT COUNT(*) FROM journals j JOIN publishers p ON p.id=j.publisher_id WHERE p.type IS NOT NULL AND j.publisher_id = 73"))
    print("Kolom subject tidak berubah   :", before == after)
    for r in conn.execute(text("SELECT subject_source, COUNT(*) FROM journals_public GROUP BY 1 ORDER BY 1")):
        print("  view", r[0], r[1])

    if before != after:
        raise SystemExit("subject berubah, dibatalkan")
    if a.apply:
        tx.commit()
        print("TERSIMPAN")
    else:
        tx.rollback()
        print("DRY-RUN: tidak ada yang diubah. Tambahkan --apply untuk menyimpan.")
except BaseException:
    tx.rollback()
    raise
finally:
    conn.close()