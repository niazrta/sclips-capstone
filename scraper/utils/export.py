import sys
import os
sys.path.append(os.getcwd())

import pandas as pd
from datetime import datetime
from db.session import engine
from utils.logger import get_logger

logger = get_logger("export")

EXPORT_QUERY = """
    SELECT
        j.id AS journal_id,
        j.name AS journal_title,
        p.raw_name AS publisher_name_raw,
        p.name AS publisher_name_clean,
        j.subject,
        p.type AS publisher_type
    FROM journals j
    LEFT JOIN publishers p ON j.publisher_id = p.id
    WHERE j.is_active = true
"""

def export_journals_to_csv(output_path: str | None = None) -> str:
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"exports/journals_export_{timestamp}.csv"

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    df = pd.read_sql(EXPORT_QUERY, engine)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")

    logger.info(f"Export selesai: {len(df)} baris -> {output_path}")
    return output_path


if __name__ == "__main__":
    path = export_journals_to_csv()
    print(f"CSV tersimpan di: {path}")