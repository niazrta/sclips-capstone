import sys, os, re, json, csv, time
sys.path.append(os.getcwd())

from sqlalchemy import text
from db.session import engine
from config import config
from utils.logger import get_logger
from scraper.sinta_scraper import _safe_get, parse_listing_page, LIST_URL_TEMPLATE

logger = get_logger("audit_listing")


def to_int(s):
    return int(s.replace(".", "").replace(",", ""))


def read_totals(html):
    total = re.search(r"Total Records\s*([\d.,]+)", html)
    pages = re.search(r"Page\s+\d+\s+of\s+([\d.,]+)", html)
    return (to_int(total.group(1)) if total else None,
            to_int(pages.group(1)) if pages else None)


def fetch_page(page):
    html = _safe_get(LIST_URL_TEMPLATE.format(page=page))
    if html is None:
        return None
    return parse_listing_page(html)


def main():
    first_html = _safe_get(LIST_URL_TEMPLATE.format(page=1))
    if first_html is None:
        raise SystemExit("Halaman 1 gagal diambil")
    site_total, total_pages = read_totals(first_html)
    logger.info(f"SINTA melaporkan: {site_total} jurnal, {total_pages} halaman")
    if not total_pages:
        raise SystemExit("Jumlah halaman tidak terbaca, cek pola teks pagination")

    journals, failed = [], []
    for page in range(1, total_pages + 1):
        items = fetch_page(page)
        if items is None:
            failed.append(page)
        else:
            journals.extend(items)
        if page % 100 == 0:
            logger.info(f"Halaman {page}/{total_pages}, terkumpul {len(journals)}, gagal {len(failed)}")
        time.sleep(config.SCRAPE_DELAY_SECONDS)

    # ulangi halaman yang gagal
    still_failed = []
    for page in failed:
        time.sleep(5)
        items = fetch_page(page)
        if items is None:
            still_failed.append(page)
        else:
            journals.extend(items)
    logger.info(f"Halaman gagal permanen: {still_failed}")

    os.makedirs("data", exist_ok=True)
    with open("data/listing_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(journals, f, ensure_ascii=False)

    site_ids = {}
    for j in journals:
        if j.get("sinta_journal_id"):
            site_ids[int(j["sinta_journal_id"])] = j
    with engine.connect() as conn:
        db_ids = {r[0] for r in conn.execute(text("SELECT id FROM journals"))}

    missing = sorted(set(site_ids) - db_ids)
    extra = sorted(db_ids - set(site_ids))

    with open("data/missing_in_db.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["sinta_id", "name", "publisher_name"])
        for i in missing:
            w.writerow([i, site_ids[i]["name"], site_ids[i]["publisher_name"]])

    print("\n===== HASIL AUDIT =====")
    print(f"Total di SINTA (header)     : {site_total}")
    print(f"Baris listing terkumpul     : {len(journals)}")
    print(f"ID unik di listing          : {len(site_ids)}")
    print(f"Jurnal di database          : {len(db_ids)}")
    print(f"ADA di SINTA, TIDAK di DB   : {len(missing)}")
    print(f"ADA di DB, TIDAK di listing : {len(extra)}")
    print(f"Halaman gagal permanen      : {still_failed}")
    print(f"Contoh ID hilang            : {missing[:10]}")


if __name__ == "__main__":
    main()