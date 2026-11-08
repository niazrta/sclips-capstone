import pandas as pd
old = pd.read_csv("data/ml/publishers_sebelum_impor.csv").rename(columns={"id": "publisher_id", "type": "old"})
new = pd.read_csv("data/ml/predictions_baru_7nov.csv", encoding="utf-8-sig")
new = new[new.predicted_publisher_type.notna()].groupby("publisher_id", as_index=False)["predicted_publisher_type"].first()
ch = pd.read_csv("data/ml/publisher_type_changes.csv")
m = new.merge(old[["publisher_id", "old"]], on="publisher_id", how="left")
diff = m[m.old.fillna("") != m.predicted_publisher_type]
print("Penerbit di CSV baru        :", len(new))
print("Tipe berbeda dari database  :", len(diff), "| dari kosong:", int(diff.old.isna().sum()))
print("Baris di file perubahan     :", len(ch))
a, b = set(diff.publisher_id), set(ch.publisher_id.dropna().astype(int))
print("Beda di database, tidak di file perubahan:", len(a - b), sorted(a - b)[:10])
print("Di file perubahan, tidak beda di database:", len(b - a), sorted(b - a)[:10])