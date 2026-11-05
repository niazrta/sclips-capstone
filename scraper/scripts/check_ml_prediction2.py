import sys, os
sys.path.append(os.getcwd())
import pandas as pd
from sqlalchemy import text
from db.session import engine

df = pd.read_csv(sys.argv[1], encoding="utf-8-sig").rename(columns={"publisher_id": "ml_publisher_id"})
with engine.connect() as c:
    j = pd.read_sql(text("SELECT id, subject, publisher_id FROM journals"), c)
m = df.merge(j, left_on="journal_id", right_on="id")

diff = (m["ml_publisher_id"].fillna(-1) != m["publisher_id"].fillna(-1)).sum()
print("publisher_id di CSV beda dari DB:", int(diff))
inc = m.groupby("publisher_id")["predicted_publisher_type"].nunique()
print("Penerbit dengan >1 tipe          :", int((inc > 1).sum()))
odd = m[m["publisher_id"].isna() | (m["publisher_id"] == 73)]
print("Jurnal tanpa penerbit / Unknown  :", len(odd))
print(odd[["journal_id", "publisher_id", "predicted_publisher_type"]].to_string(index=False))
print("predicted_subject == predicted_subject_scopus di semua baris:",
      bool((m["predicted_subject"] == m["predicted_subject_scopus"]).all()))

lab = m[m["subject"].notna()].copy()
true = lab["subject"].apply(lambda s: sorted(x.strip() for x in s.split(",")))
single = [p in t for p, t in zip(lab["predicted_subject_sinta"], true)]
multi = [sorted(x.strip() for x in str(p).split(",")) == t
         for p, t in zip(lab["predicted_subject_sinta_multilabel"], true)]
print("\nJurnal yang subject SINTA-nya ada:", len(lab))
print("  label tunggal masuk dalam subject SINTA:", round(sum(single) / len(lab) * 100, 1), "%")
print("  multilabel sama persis dengan SINTA    :", round(sum(multi) / len(lab) * 100, 1), "%")
print("\nConfidence:")
print(df[["scopus_confidence_score", "publisher_classification_confidence"]].describe().round(3).to_string())