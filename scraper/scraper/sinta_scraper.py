import re
import time
import requests
from bs4 import BeautifulSoup
from config import config
from utils.logger import get_logger
from scraper.cleaner import collapse_spaces, classify_issn

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


def parse_id_number(s):
    """Format Indonesia: '14.902' -> 14902.0 ; '104,00' -> 104.0 ; selain itu None."""
    s = (s or "").strip()

    if not re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?|\d+(,\d+)?", s):
        return None

    return float(s.replace(".", "").replace(",", "."))


_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200e\u200f\u202a\u202b\u202c\u202d\u202e\ufeff"))


def _link(v):
    """Penanda 'tidak ada' dari SINTA dibaca kosong. Spasi di tepi dibuang, isi tidak diubah."""
    v = (v or "").translate(_INVISIBLE).strip()
    if v in ("", "#", "#!", "-") or v.endswith("/img/journal/"):
        return None
    return v


def parse_listing_extras(item) -> dict:
    """Ekstrak field tambahan dari item listing SINTA."""
    out = {"garuda_id": None}

    # URL Google Scholar, Website, dan Editor URL
    links = {
        a.get_text(strip=True): a["href"]
        for a in item.select("div.affil-abbrev a[href]")
    }

    out["google_scholar_url"] = _link(links.get("Google Scholar"))
    out["website"] = _link(links.get("Website"))
    out["editor_url"] = _link(links.get("Editor URL"))

    # Garuda ID
    for a in item.select("a[href]"):
        m = re.search(r"garuda\.[^/]+/journal/view/(\d+)", a["href"])
        if m:
            out["garuda_id"] = int(m.group(1))
            break

    # Status indeksasi
    out["garuda_indexed"] = item.select_one("span.garuda-indexed") is not None
    out["scopus_indexed"] = item.select_one("span.scopus-indexed") is not None

    # Rank badge
    acc = item.select_one("span.num-stat.accredited")
    m = re.match(r"(S[1-6]|NA)\b", acc.get_text(" ", strip=True)) if acc else None
    out["rank_badge"] = m.group(1) if m else None

    # Cover URL
    img = item.select_one("img.journal-cover")
    out["cover_url"] = _link(img.get("src")) if img else None

    # Metrik jurnal
    raw = {}

    for num in item.select("div.pr-num"):
        lab = num.find_next_sibling("div", class_="pr-txt")
        if lab:
            raw[lab.get_text(strip=True)] = num.get_text(strip=True)

    out["impact"] = parse_id_number(raw.get("Impact"))

    for label, key in (
        ("H5-index", "h5_index"),
        ("Citations 5yr", "citations_5yr"),
        ("Citations", "citations"),
    ):
        v = parse_id_number(raw.get(label))
        out[key] = int(v) if v is not None else None

    out["raw_stats"] = raw

    return out


def _safe_get(url: str, max_retries: int = 3):
    """Request dengan timeout + retry + graceful degradation."""
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout percobaan {attempt}/{max_retries} untuk {url}")
        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP error {e} percobaan {attempt}/{max_retries} untuk {url}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"Request gagal percobaan {attempt}/{max_retries} untuk {url}: {e}")

        if attempt < max_retries:
            time.sleep(3)

    logger.error(f"Gagal ambil {url} setelah {max_retries} percobaan")
    return None


ISSN_PATTERNS = {
    "p": r"P-ISSN\s*:\s*(.*?)\s*(?:\||E-ISSN|Subject Area|$)",
    "e": r"E-ISSN\s*:\s*(.*?)\s*(?:\||P-ISSN|Subject Area|$)",
}


def _id_from(href):
    """ID angka dari tautan .../profile/{id}. Tidak bergantung pada nama domain."""
    m = re.search(r"/profile/(\d+)", href or "")
    return int(m.group(1)) if m else None


def parse_listing_page(html: str) -> list[dict]:
    """Ekstrak semua jurnal dari satu halaman listing, apa adanya dari SINTA."""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for item in soup.select("div.list-item.row.mt-3"):
        try:
            name_tag = item.select_one("div.affil-name > a")
            journal_id = _id_from(name_tag.get("href")) if name_tag else None
            name = collapse_spaces(name_tag.get_text()) if name_tag else None
            if not name or journal_id is None:
                logger.warning("Item listing dilewati: nama atau ID jurnal tidak terbaca")
                continue

            loc_tag = item.select_one("div.affil-loc > a")
            publisher_name = collapse_spaces(loc_tag.get_text()) if loc_tag else None
            affiliation_id = _id_from(loc_tag.get("href")) if loc_tag else None

            pid = item.select_one("div.profile-id")
            text_ = " ".join(pid.get_text(" ").split()) if pid else ""

            m = re.search(r"Subject Area\s*:\s*(.*?)\s*(?:P-ISSN|E-ISSN|$)", text_, re.I)
            subject = (m.group(1).strip() or None) if m else None

            issn = {}
            for key, pat in ISSN_PATTERNS.items():
                mm = re.search(pat, text_, re.I)
                value, status = classify_issn(mm.group(1) if mm else "")
                issn[f"{key}_issn"], issn[f"{key}_issn_status"] = value, status

            results.append({
                "sinta_journal_id": journal_id,
                "name": name,
                "publisher_name": publisher_name,
                "sinta_publisher_id": affiliation_id,
                "subject": subject,
                **issn,
                **parse_listing_extras(item),
            })
        except Exception as e:
            logger.error(f"Gagal parsing satu item listing: {e}")
            continue

    return results


def parse_detail_page(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    # Penanda halaman profil jurnal (dari HTML profil yang sudah kita inspeksi)
    if soup.select_one("div.meta-profile") is None or soup.select_one("h3") is None:
        raise ValueError("Halaman bukan profil jurnal: penanda profil tidak ditemukan")

    detail = {
        "current_rank": None,
        "website": None,
        "accreditation_year_start": None,
        "accreditation_year_end": None,
        "accreditation_history": [],  # [{"year": 2024, "rank": "S3"}, ...]
    }

    # --- Website ---
    for a in soup.find_all("a"):
        if a.get_text(strip=True) == "Website" and a.has_attr("href"):
            detail["website"] = a["href"]
            break

    # --- Tabel akreditasi (opsional: jurnal baru bisa belum punya) ---
    table = soup.select_one("table.table-borderless")
    if table is None:
        return detail  # profil sah, riwayat kosong

    rows = table.select("tr")
    if len(rows) < 2:
        raise ValueError("Struktur tabel akreditasi tidak sesuai")

    years = []
    for yc in rows[0].select("td"):
        txt = yc.get_text(strip=True)
        years.append(int(txt) if txt.isdigit() else None)

    history = []
    for i, rc in enumerate(rows[-1].select("td")):
        if i >= len(years) or years[i] is None:
            continue
        match = re.search(r"Sinta\s*(\d)", rc.get("title", ""), re.IGNORECASE)
        if match:
            history.append({"year": years[i], "rank": f"S{match.group(1)}"})

    if history:
        detail["accreditation_history"] = history
        detail["current_rank"] = history[-1]["rank"]
        detail["accreditation_year_start"] = history[0]["year"]
        detail["accreditation_year_end"] = history[-1]["year"]

    return detail


def scrape_listing(max_pages: int | None = None) -> list[dict]:
    """Scrape semua halaman listing. max_pages=None berarti sampai halaman kosong.
    Catatan: akan diganti oleh engine.py (belum ada pelacakan halaman gagal)."""
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
    """Deep crawl ke halaman profil. Akan diganti oleh engine.py.
    URL dirakit dari SINTA_BASE_URL dan ID (kunci sinta_url sudah tidak ada)."""
    enriched = []
    for i, journal in enumerate(journals, 1):
        try:
            logger.info(f"[{i}/{len(journals)}] Detail: {journal['name']}")
            html = _safe_get(f"{config.SINTA_BASE_URL}/journals/profile/{journal['sinta_journal_id']}")
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