from db.session import SessionLocal
from db.upsert import backfill_subject
from scraper.sinta_scraper import scrape_listing
from utils.logger import get_logger
from config import config
import time

logger = get_logger("backfill_subject")


def run_backfill():
    db = SessionLocal()
    updated_count = 0
    total_with_subject = 0

    try:
        logger.info("Scraping ulang listing untuk mengambil subject...")

        listing = scrape_listing(max_pages=1)

        logger.info(
            f"Listing selesai: {len(listing)} jurnal. "
            "Mulai backfill subject..."
        )

        for i, item in enumerate(listing, 1):
            try:
                subject = item.get("subject")
                sinta_url = item.get("sinta_url")

                if subject:
                    total_with_subject += 1

                if backfill_subject(
                    db,
                    sinta_url,
                    subject,
                ):
                    updated_count += 1
                    db.commit()

                if i % 200 == 0:
                    logger.info(
                        f"Progress: {i}/{len(listing)}, "
                        f"updated: {updated_count}"
                    )

            except Exception as e:
                db.rollback()

                logger.error(
                    f"Gagal backfill {item.get('name')}: {e}"
                )

        logger.info(
            f"Backfill selesai. "
            f"Total subject ditemukan: {total_with_subject}, "
            f"total ter-update: {updated_count}"
        )

    finally:
        db.close()


if __name__ == "__main__":
    run_backfill()