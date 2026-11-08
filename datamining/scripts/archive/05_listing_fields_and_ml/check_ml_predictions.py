import sys, os
sys.path.append(os.getcwd())
import pandas as pd
from sqlalchemy import text
from db.session import engine

df = pd.read_csv(sys.argv[1], encoding="utf-8-sig")
print("Baris:", len(df), "| ID unik:", df["journal_id"].nunique())
print("Kolom:", list(df.columns))
print("\nKosong per kolom:")
print(df.isna().sum().to_string())

with engine.connect() as c:
    j = pd.read_sql(text("SELECT id, subject, publisher_id, is_active, status FROM journals"), c)

csv_ids, db_ids = set(df["journal_id"]), set(j["id"])
active = set(j.loc[j["is_active"] & (j["status"] == "active"), "id"])
print("\nID di CSV tapi tidak di DB       :", len(csv_ids - db_ids))
print("Jurnal aktif yang tidak di CSV   :", len(active - csv_ids))

for col in df.columns:
    if col != "journal_id" and df[col].nunique() <= 40:
        print(f"\n{col}:")
        print(df[col].value_counts(dropna=False).to_string())

m = df.merge(j, left_on="journal_id", right_on="id")
if "predicted_publisher_type" in df.columns:
    inc = m.groupby("publisher_id")["predicted_publisher_type"].nunique()
    print("\nPenerbit dengan >1 tipe :", int((inc > 1).sum()))
    odd = m[m["publisher_id"].isna() | (m["publisher_id"] == 73)]
    print("Jurnal tanpa penerbit / 'Unknown':", len(odd))
    print(odd[["journal_id", "publisher_id", "predicted_publisher_type"]].to_string(index=False))

blank = m[m["subject"].isna()]
print("\nSubject kosong di DB:", len(blank))
for col in [c for c in df.columns if c.startswith("predicted_subject")]:
    print(f"  {col}: terisi {int(blank[col].notna().sum())}")