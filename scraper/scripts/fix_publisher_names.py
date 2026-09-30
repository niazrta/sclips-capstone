import sys
import os
sys.path.append(os.getcwd())

from db.session import SessionLocal
from db.models import Publisher
from scraper.cleaner import normalize_publisher_name
from utils.logger import get_logger

logger = get_logger("fix_publisher_names")


def run_fix():
    db = SessionLocal()
    updated_count = 0
    try:
        publishers = db.query(Publisher).all()
        logger.info(f"Total publisher di database: {len(publishers)}")

        for pub in publishers:
            new_name = normalize_publisher_name(pub.raw_name or pub.name)
            if new_name and new_name != pub.name:
                logger.info(f"'{pub.name}' -> '{new_name}'")
                pub.name = new_name
                updated_count += 1

        db.commit()
        logger.info(f"Selesai. Total nama diperbaiki: {updated_count}")
    finally:
        db.close()


if __name__ == "__main__":
    run_fix()