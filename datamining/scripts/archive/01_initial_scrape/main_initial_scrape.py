import time
from datetime import datetime, timezone

from db.session import SessionLocal
from db.models import ScrapingLog, ScrapingStatus, JournalRankHistory
from db.upsert import upsert_publisher, upsert_journal, flag_missing_journals
from scraper.sinta_scraper import (
    scrape_listing,
    _safe_get,
    parse_detail_page,
)
from scraper.cleaner import normalize_publisher_name, clean_issn
from utils.logger import get_logger
from config import config

logger = get_logger("main")


def run_scraping(max_pages: int | None = None):
    db = SessionLocal()

    log_entry = ScrapingLog(
        started_at=datetime.now(timezone.utc),
        status=ScrapingStatus.running,
    )

    db.add(log_entry)
    db.commit()
    db.refresh(log_entry)

    counters = {
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "flagged": 0,
    }

    found_urls = []

    try:
        # ==========================================
        # 1. SCRAPING LISTING
        # ==========================================
        logger.info("Mulai scraping listing...")

        listing = scrape_listing(max_pages=max_pages)
        total = len(listing)

        logger.info(
            f"Listing selesai: {total} jurnal. "
            "Mulai proses detail + simpan ke database satu per satu..."
        )

        # ==========================================
        # 2. PROSES DETAIL + SIMPAN PER JURNAL
        # ==========================================
        for i, item in enumerate(listing, 1):
            try:
                logger.info(
                    f"[{i}/{total}] Memproses: {item['name']}"
                )

                # ------------------------------------------
                # Ambil halaman detail jurnal
                # ------------------------------------------
                html = _safe_get(item["sinta_url"])

                if html:
                    detail = parse_detail_page(html)
                    item.update(detail)
                else:
                    logger.warning(
                        f"Gagal mengambil detail: {item['name']}"
                    )

                # ------------------------------------------
                # Bersihkan nama publisher
                # ------------------------------------------
                clean_publisher_name = normalize_publisher_name(
                    item.get("publisher_name") or ""
                )

                publisher = upsert_publisher(
                    db,
                    name=clean_publisher_name or "Unknown",
                    raw_name=item.get("publisher_name"),
                )

                # ------------------------------------------
                # Siapkan data jurnal
                # ------------------------------------------
                journal_data = {
                    "name": item["name"],
                    "e_issn": clean_issn(item.get("e_issn")),
                    "p_issn": clean_issn(item.get("p_issn")),
                    "sinta_url": item.get("sinta_url"),
                    "current_rank": item.get("current_rank"),
                    "publisher_id": publisher.id,
                    "subject": item.get("subject"),
                }

                # ------------------------------------------
                # Insert / update jurnal
                # ------------------------------------------
                journal, action = upsert_journal(
                    db,
                    journal_data,
                )

                counters[action] += 1

                found_urls.append(
                    item.get("sinta_url")
                )

                db.flush()

                # ------------------------------------------
                # Simpan riwayat akreditasi
                # ------------------------------------------
                for hist in item.get(
                    "accreditation_history", []
                ):
                    exists = (
                        db.query(JournalRankHistory)
                        .filter_by(
                            journal_id=journal.id,
                            accreditation_year=hist["year"],
                        )
                        .first()
                    )

                    if not exists:
                        db.add(
                            JournalRankHistory(
                                journal_id=journal.id,
                                sinta_rank=hist["rank"],
                                accreditation_year=hist["year"],
                            )
                        )

                # ------------------------------------------
                # COMMIT PER JURNAL
                # ------------------------------------------
                db.commit()

                logger.info(
                    f"[{i}/{total}] Berhasil disimpan "
                    f"({action}): {item['name']}"
                )

            except Exception as e:
                # Kalau satu jurnal gagal,
                # rollback hanya transaksi jurnal tersebut
                db.rollback()

                logger.error(
                    f"Gagal proses jurnal "
                    f"{item.get('name')}: {e}"
                )

                continue

            finally:
                # ------------------------------------------
                # DELAY ANTAR REQUEST
                # ------------------------------------------
                time.sleep(
                    config.SCRAPE_DELAY_SECONDS
                )

        # ==========================================
        # 3. FLAG JURNAL YANG SUDAH TIDAK DITEMUKAN
        # ==========================================
        logger.info(
            "Mengecek jurnal yang sudah tidak ditemukan..."
        )

        flagged_count = flag_missing_journals(
            db,
            found_urls,
        )

        counters["flagged"] = flagged_count

        db.commit()

        # ==========================================
        # 4. UPDATE LOG SCRAPING
        # ==========================================
        log_entry.status = ScrapingStatus.success
        log_entry.total_scraped = total
        log_entry.total_inserted = counters["inserted"]
        log_entry.total_updated = counters["updated"]
        log_entry.total_skipped = counters["skipped"]
        log_entry.total_flagged = counters["flagged"]
        log_entry.finished_at = datetime.now(timezone.utc)

        db.commit()

        logger.info(
            f"Selesai! {counters}"
        )

    # ==========================================
    # 5. KALAU USER TEKAN CTRL+C
    # ==========================================
    except KeyboardInterrupt:
        db.rollback()

        log_entry.status = ScrapingStatus.failed
        log_entry.error_message = (
            "Scraping dihentikan manual oleh user (Ctrl+C)"
        )
        log_entry.finished_at = datetime.now(timezone.utc)

        db.commit()

        logger.info(
            "Scraping dihentikan manual. "
            "Data jurnal yang sudah di-commit "
            "tetap tersimpan di database."
        )

    # ==========================================
    # 6. ERROR BESAR / TIDAK TERDUGA
    # ==========================================
    except Exception as e:
        db.rollback()

        log_entry.status = ScrapingStatus.failed
        log_entry.error_message = str(e)
        log_entry.finished_at = datetime.now(timezone.utc)

        db.commit()

        logger.error(
            f"Scraping gagal total: {e}"
        )

    finally:
        db.close()


if __name__ == "__main__":
    run_scraping(max_pages=None)