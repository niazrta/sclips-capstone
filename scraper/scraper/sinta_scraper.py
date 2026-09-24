import re
import time
import requests
from bs4 import BeautifulSoup
from config import config
from utils.logger import get_logger

logger = get_logger("sinta_scraper")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
}

LIST_URL_TEMPLATE = f"{config.SINTA_BASE_URL}/journals?page={{page}}"
REQUEST_TIMEOUT = 15

session = requests.Session()
session.headers.update(HEADERS)


def _safe_get(url: str):
    """Request dengan timeout + graceful degradation. Return None kalau gagal."""
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.Timeout:
        logger.warning(f"Timeout saat akses {url}")
    except requests.exceptions.HTTPError as e:
        logger.warning(f"HTTP error {e} saat akses {url}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"Request gagal untuk {url}: {e}")
    return None


def parse_listing_page(html: str) -> list[dict]:
    """Ekstrak semua jurnal dari satu halaman listing."""
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("div.list-item.row.mt-3")
    results = []

    for item in items:
        try:
            name_tag = item.select_one("div.affil-name > a")
            name = name_tag.text.strip() if name_tag else None
            profile_url = name_tag["href"] if name_tag and name_tag.has_attr("href") else None
            sinta_journal_id = profile_url.rstrip("/").split("/")[-1] if profile_url else None

            loc_tag = item.select_one("div.affil-loc > a")
            publisher_name = loc_tag.text.strip() if loc_tag else None
            publisher_url = loc_tag["href"] if loc_tag and loc_tag.has_attr("href") else None
            sinta_publisher_id = publisher_url.rstrip("/").split("/")[-1] if publisher_url else None

            profile_id_div = item.select_one("div.profile-id")
            profile_id_text = profile_id_div.text if profile_id_div else ""

            subject_match = re.search(
                r"Subject Area\s*:\s*(.*?)\s*(?:P-ISSN|E-ISSN|$)",
                profile_id_text, re.IGNORECASE | re.DOTALL
            )
            subject = subject_match.group(1).strip() if subject_match else None

            p_issn_match = re.search(r"P-ISSN\s*:\s*([\d-]+)", profile_id_text)
            e_issn_match = re.search(r"E-ISSN\s*:\s*([\d-]+)", profile_id_text)
            p_issn = p_issn_match.group(1) if p_issn_match else None
            e_issn = e_issn_match.group(1) if e_issn_match else None

            if not name or not profile_url:
                logger.warning("Item listing dilewati: nama/URL profil tidak ditemukan")
                continue

            results.append({
                "name": name,
                "sinta_url": profile_url,
                "sinta_journal_id": sinta_journal_id,
                "publisher_name": publisher_name,
                "sinta_publisher_id": sinta_publisher_id,
                "subject": subject,
                "p_issn": p_issn,
                "e_issn": e_issn,
            })
        except Exception as e:
            logger.error(f"Gagal parsing satu item listing: {e}")
            continue

    return results


def parse_detail_page(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    detail = {
        "current_rank": None,
        "website": None,
        "accreditation_year_start": None,
        "accreditation_year_end": None,
        "accreditation_history": [],  # [{"year": 2024, "rank": "S3"}, ...]
    }

    # --- Website ---
    try:
        for a in soup.find_all("a"):
            if a.get_text(strip=True) == "Website" and a.has_attr("href"):
                detail["website"] = a["href"]
                break
    except Exception as e:
        logger.warning(f"Gagal ambil website: {e}")

    # --- Tabel akreditasi: gabungkan kolom tahun dengan kolom rank per index ---
    try:
        table = soup.select_one("table.table-borderless")
        if table:
            rows = table.select("tr")
            if len(rows) >= 2:
                year_cells = rows[0].select("td")
                rank_cells = rows[-1].select("td")  # baris data (terakhir kalau >1 baris)

                years = []
                for yc in year_cells:
                    txt = yc.get_text(strip=True)
                    years.append(int(txt) if txt.isdigit() else None)

                history = []
                for i, rc in enumerate(rank_cells):
                    if i >= len(years) or years[i] is None:
                        continue
                    title = rc.get("title", "")
                    match = re.search(r"Sinta\s*(\d)", title, re.IGNORECASE)
                    if match:
                        history.append({"year": years[i], "rank": f"S{match.group(1)}"})

                detail["accreditation_history"] = history
                if history:
                    detail["current_rank"] = history[-1]["rank"]  # tahun terakhir = current
                    detail["accreditation_year_start"] = history[0]["year"]
                    detail["accreditation_year_end"] = history[-1]["year"]
    except Exception as e:
        logger.warning(f"Gagal ambil accreditation table: {e}")

    return detail


def scrape_listing(max_pages: int | None = None) -> list[dict]:
    """Scrape semua halaman listing. max_pages=None berarti sampai halaman kosong."""
    all_journals = []
    page = 1

    while True:
        if max_pages and page > max_pages:
            break

        url = LIST_URL_TEMPLATE.format(page=page)
        logger.info(f"Scraping listing halaman {page}: {url}")
        html = _safe_get(url)

        if html is None:
            logger.error(f"Gagal ambil halaman {page}, berhenti di sini")
            break

        journals = parse_listing_page(html)
        if not journals:
            logger.info(f"Halaman {page} kosong, scraping listing selesai")
            break

        all_journals.extend(journals)
        page += 1
        time.sleep(config.SCRAPE_DELAY_SECONDS)

    logger.info(f"Total jurnal dari listing: {len(all_journals)}")
    return all_journals


def enrich_with_detail(journals: list[dict]) -> list[dict]:
    """Deep crawl ke tiap halaman profil jurnal untuk data detail."""
    enriched = []
    for i, journal in enumerate(journals, 1):
        try:
            logger.info(f"[{i}/{len(journals)}] Detail: {journal['name']}")
            html = _safe_get(journal["sinta_url"])
            if html is None:
                logger.warning(f"Skip detail untuk {journal['name']} (gagal fetch)")
                enriched.append(journal)
                continue

            detail = parse_detail_page(html)
            journal.update(detail)
            enriched.append(journal)
        except Exception as e:
            logger.error(f"Error tak terduga di jurnal {journal.get('name')}: {e}")
            enriched.append(journal)
        finally:
            time.sleep(config.SCRAPE_DELAY_SECONDS)

    return enriched


def run_full_scrape(max_pages: int | None = None) -> list[dict]:
    listing = scrape_listing(max_pages=max_pages)
    return enrich_with_detail(listing)