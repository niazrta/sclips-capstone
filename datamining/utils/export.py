import sys, os
sys.path.append(os.getcwd())

import pandas as pd
from datetime import datetime
from db.session import engine
from utils.logger import get_logger

logger = get_logger("export")

EXPORT_QUERY = """
    SELECT j.id AS journal_id,
           j.name AS journal_title,
           p.name AS publisher_name_raw,
           p.name AS publisher_name_clean,
           j.subject,
           p.type AS publisher_type,
           p.id AS publisher_id,
           p.sinta_publisher_id
    FROM journals j
    LEFT JOIN publishers p ON j.publisher_id = p.id
    WHERE j.is_active = true AND j.status = 'active'
    ORDER BY j.id
"""


def export_all():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("exports", exist_ok=True)

    df = pd.read_sql(EXPORT_QUERY, engine)
    path = f"exports/journals_export_{ts}.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")

    idmap = pd.read_sql("SELECT old_id, sinta_id FROM journal_id_map ORDER BY old_id", engine)
    map_path = f"exports/journal_id_map_{ts}.csv"
    idmap.to_csv(map_path, index=False, encoding="utf-8-sig")

    print("File      :", path)
    print("Peta ID   :", map_path)
    print("Baris     :", len(df), "| ID unik:", df["journal_id"].nunique())
    print("subject terisi:", int(df["subject"].notna().sum()), "| kosong:", int(df["subject"].isna().sum()))
    print("publisher_type terisi:", int(df["publisher_type"].notna().sum()))
    print("nama penerbit kosong:", int(df["publisher_name_clean"].isna().sum()))
    print("tanpa sinta_publisher_id:", int(df["sinta_publisher_id"].isna().sum()))


if __name__ == "__main__":
    export_all()