import sys
import os
sys.path.append(os.getcwd())

import pandas as pd
from db.session import SessionLocal
from db.models import Journal, Publisher
from utils.logger import get_logger

logger = get_logger("import_predictions")


def run_import(csv_path: str):
    db = SessionLocal()
    updated_journals = 0
    updated_publishers = 0

    try:
        df = pd.read_csv(csv_path)
        required_cols = {"journal_id"}
        if not required_cols.issubset(df.columns):
            raise ValueError(f"CSV harus punya kolom: {required_cols}")

        for _, row in df.iterrows():
            journal = db.query(Journal).filter(Journal.id == row["journal_id"]).first()
            if not journal:
                logger.warning(f"journal_id {row['journal_id']} tidak ditemukan, dilewati")
                continue

            if "predicted_subject" in df.columns and pd.notna(row.get("predicted_subject")):
                journal.subject = row["predicted_subject"]
                updated_journals += 1

            if "predicted_publisher_type" in df.columns and pd.notna(row.get("predicted_publisher_type")):
                if journal.publisher_id:
                    publisher = db.query(Publisher).filter(Publisher.id == journal.publisher_id).first()
                    if publisher and not publisher.type:
                        publisher.type = row["predicted_publisher_type"]
                        updated_publishers += 1

        db.commit()
        logger.info(f"Import selesai. Journal ter-update: {updated_journals}, Publisher ter-update: {updated_publishers}")

    except Exception as e:
        db.rollback()
        logger.error(f"Import gagal: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Cara pakai: python scripts/import_predictions.py path/ke/hasil_prediksi.csv")
        sys.exit(1)
    run_import(sys.argv[1])