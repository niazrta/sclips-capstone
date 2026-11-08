import sys
import os
import re
import json
import time
import gzip
import argparse
from collections import Counter
from datetime import datetime, timezone

sys.path.append(os.getcwd())

from sqlalchemy import text
from db.session import engine
from config import config
from scraper.sinta_scraper import (
    _safe_get,
    parse_listing_page,
    LIST_URL_TEMPLATE,
)


FIELD_COLUMNS = [
    "website",
    "editor_url",
    "google_scholar_url",
    "garuda_id",
    "cover_url",
    "rank_badge",
    "scopus_indexed",
    "garuda_indexed",
    "impact",
    "h5_index",
    "citations_5yr",
    "citations",
    "metrics_updated_at",
]

METRIC_FIELDS = [
    "impact",
    "h5_index",
    "citations_5yr",
    "citations",
]

KNOWN_STATS = {
    "Impact",
    "H5-index",
    "Citations 5yr",
    "Citations",
}

VALID_BADGES = {
    "S1", "S2", "S3", "S4", "S5", "S6", "NA"
}


def parse_number(text_value):
    """Mengubah angka pada format listing SINTA menjadi integer."""
    if not text_value:
        return None

    value = str(text_value).strip()

    if not re.fullmatch(
        r"\d{1,3}(\.\d{3})+(,\d+)?|\d+(,\d+)?",
        value
    ):
        return None

    return float(value.replace(".", "").replace(",", "."))


def extract_listing_metadata(html):
    """Membaca jumlah halaman dan total jurnal dari HTML listing."""
    pattern = (
        r"Page\s+[\d,.]+\s+of\s+([\d,.]+)"
        r"\s*\|\s*Total Records\s+([\d,.]+)"
    )

    match = re.search(pattern, html, re.IGNORECASE)

    if not match:
        return None, None

    total_pages = int(match.group(1).replace(".", "").replace(",", ""))
    total_records = int(match.group(2).replace(".", "").replace(",", ""))

    return total_pages, total_records


def fetch_page(page):
    html = _safe_get(LIST_URL_TEMPLATE.format(page=page))

    if html is None:
        return None, None

    return html, parse_listing_page(html)


def save_html(page, html):
    os.makedirs("data/raw_listing", exist_ok=True)

    path = f"data/raw_listing/page_{page}.html.gz"

    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(html)

    return path


def get_database_data():
    """Mengambil ID jurnal dan current_rank dari database."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, current_rank FROM journals")
        ).fetchall()

    return {
        int(row.id): row.current_rank
        for row in rows
    }


def build_audit(journals, database_data):
    """Menghitung hasil pemeriksaan data hasil scraping."""
    audit = {
        "null_fields": Counter(),
        "badge_counts": Counter(),
        "unknown_badges": Counter(),
        "unknown_stats": Counter(),
        "metric_parse_failures": Counter(),
        "ids_not_in_database": [],
        "rank_mismatches": [],
        "duplicate_ids": [],
    }

    seen_ids = set()

    for journal in journals:
        sinta_id = journal.get("sinta_journal_id")

        if sinta_id:
            try:
                journal_id = int(sinta_id)

                if journal_id in seen_ids:
                    audit["duplicate_ids"].append(journal_id)

                seen_ids.add(journal_id)

                if journal_id not in database_data:
                    audit["ids_not_in_database"].append(journal_id)

            except (ValueError, TypeError):
                audit["ids_not_in_database"].append(sinta_id)

        for field in FIELD_COLUMNS:
            if field == "metrics_updated_at":
                continue

            if journal.get(field) is None:
                audit["null_fields"][field] += 1

        badge = journal.get("rank_badge")

        if badge is None:
            audit["badge_counts"]["None"] += 1
        else:
            audit["badge_counts"][badge] += 1

            if badge not in VALID_BADGES:
                audit["unknown_badges"][badge] += 1

        raw_stats = journal.get("raw_stats") or {}

        for label in raw_stats:
            if label not in KNOWN_STATS:
                audit["unknown_stats"][label] += 1

        for field in METRIC_FIELDS:
            raw_label = {
                "impact": "Impact",
                "h5_index": "H5-index",
                "citations_5yr": "Citations 5yr",
                "citations": "Citations",
            }[field]

            raw_value = raw_stats.get(raw_label)

            if raw_value is not None and journal.get(field) is None:
                audit["metric_parse_failures"][field] += 1

        if sinta_id:
            try:
                journal_id = int(sinta_id)
                current_rank = database_data.get(journal_id)
                rank_badge = journal.get("rank_badge")

                if (
                    current_rank
                    and rank_badge
                    and current_rank.strip().upper()
                    != rank_badge.strip().upper()
                ):
                    audit["rank_mismatches"].append({
                        "id": journal_id,
                        "current_rank": current_rank,
                        "rank_badge": rank_badge,
                    })

            except (ValueError, TypeError, AttributeError):
                pass

    return audit


def sync_database(journals):
    """Memperbarui hanya 13 kolom tambahan."""
    updated = 0
    not_found = 0

    with engine.begin() as conn:
        for journal in journals:
            sinta_id = journal.get("sinta_journal_id")

            if not sinta_id:
                continue

            values = {
                key: journal.get(key)
                for key in FIELD_COLUMNS
                if key != "metrics_updated_at"
                and journal.get(key) is not None
            }

            if any(
                journal.get(field) is not None
                for field in METRIC_FIELDS
            ):
                values["metrics_updated_at"] = datetime.now(timezone.utc)

            if not values:
                continue

            assignments = ", ".join(
                f"{column} = :{column}"
                for column in values
            )

            values["journal_id"] = int(sinta_id)

            result = conn.execute(
                text(
                    f"""
                    UPDATE journals
                    SET {assignments}
                    WHERE id = :journal_id
                    """
                ),
                values,
            )

            if result.rowcount:
                updated += result.rowcount
            else:
                not_found += 1

    return updated, not_found


def print_audit(audit):
    print("\n===== AUDIT DATA =====")

    print("\nJumlah nilai kosong:")
    for field in FIELD_COLUMNS:
        if field != "metrics_updated_at":
            print(f"  {field:22}: {audit['null_fields'].get(field, 0)}")

    print("\nJumlah badge:")
    for badge, count in sorted(audit["badge_counts"].items()):
        print(f"  {badge:22}: {count}")

    print("\nBadge tidak dikenal:")
    print(dict(audit["unknown_badges"]))

    print("\nStatistik tidak dikenal:")
    print(dict(audit["unknown_stats"]))

    print("\nAngka gagal diparse:")
    print(dict(audit["metric_parse_failures"]))

    print("\nID tidak ditemukan di database:")
    print(len(audit["ids_not_in_database"]))

    print("\nID duplikat:")
    print(len(audit["duplicate_ids"]))

    print("\nMismatch current_rank dan rank_badge:")
    print(len(audit["rank_mismatches"]))

    for mismatch in audit["rank_mismatches"][:10]:
        print(
            f"  ID {mismatch['id']}: "
            f"current_rank={mismatch['current_rank']}, "
            f"rank_badge={mismatch['rank_badge']}"
        )

    if len(audit["rank_mismatches"]) > 10:
        print("  ... hanya 10 mismatch pertama yang ditampilkan.")


def main():
    parser = argparse.ArgumentParser(
        description="Scraping dan sinkronisasi field tambahan SINTA"
    )

    parser.add_argument("--scrape", action="store_true")
    parser.add_argument("--pages", type=int, default=None)
    parser.add_argument("--save-html", action="store_true")
    parser.add_argument("--apply", action="store_true")

    args = parser.parse_args()

    if not args.scrape:
        parser.error("Gunakan --scrape untuk mengambil data listing.")

    if args.pages is not None and args.pages < 1:
        parser.error("--pages minimal 1.")

    journals = []
    failed_pages = []
    html_bytes = 0

    os.makedirs("data", exist_ok=True)

    print("Memulai scraping listing SINTA...")

    first_html, first_items = fetch_page(1)

    if first_html is None or first_items is None:
        print("[GAGAL] Tidak dapat mengambil halaman pertama.")
        return

    detected_pages, expected_records = extract_listing_metadata(first_html)

    if detected_pages is None:
        print("[GAGAL] Metadata jumlah halaman tidak ditemukan.")
        return

    total_pages = args.pages or detected_pages

    print(f"Total halaman di SINTA : {detected_pages}")
    print(f"Total record di SINTA  : {expected_records}")
    print(f"Halaman yang diambil   : {total_pages}")

    if args.save_html:
        save_html(1, first_html)

    html_bytes += len(first_html.encode("utf-8"))
    journals.extend(first_items)

    print(f"[OK] Halaman 1/{total_pages}: {len(first_items)} jurnal")

    for page in range(2, total_pages + 1):
        time.sleep(config.SCRAPE_DELAY_SECONDS)

        html, items = fetch_page(page)

        if html is None or items is None:
            failed_pages.append(page)
            print(f"[GAGAL] Halaman {page}/{total_pages}")
            continue

        if args.save_html:
            save_html(page, html)

        html_bytes += len(html.encode("utf-8"))
        journals.extend(items)

        print(
            f"[OK] Halaman {page}/{total_pages}: "
            f"{len(items)} jurnal"
        )

    snapshot_path = "data/listing_snapshot_v2.json"

    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(journals, f, ensure_ascii=False, indent=2)

    print("\n===== HASIL SCRAPING =====")
    print(f"Jumlah halaman diminta : {total_pages}")
    print(f"Jumlah halaman berhasil: {total_pages - len(failed_pages)}")
    print(f"Jumlah jurnal terkumpul: {len(journals)}")
    print(f"Jumlah jurnal di SINTA : {expected_records}")
    print(f"Halaman gagal          : {failed_pages}")
    print(f"HTML mentah            : {html_bytes / (1024 * 1024):.2f} MB")
    print(
        "Estimasi HTML penuh   : "
        f"{(html_bytes / max(total_pages, 1) * detected_pages) / (1024 * 1024):.2f} MB"
    )
    print(f"Snapshot               : {snapshot_path}")

    database_data = get_database_data()
    audit = build_audit(journals, database_data)

    print_audit(audit)

    print("\n===== HASIL PEMERIKSAAN =====")

    checks = {
        "Semua halaman berhasil": len(failed_pages) == 0
        and total_pages == detected_pages,

        "Jumlah jurnal sesuai": len(journals) == expected_records,

        "Semua ID ditemukan di database": len(
            audit["ids_not_in_database"]
        ) == 0,

        "Tidak ada ID duplikat": len(audit["duplicate_ids"]) == 0,

        "Tidak ada angka gagal diparse": sum(
            audit["metric_parse_failures"].values()
        ) == 0,

        "Tidak ada unknown stats": len(audit["unknown_stats"]) == 0,

        "Semua badge valid": len(audit["unknown_badges"]) == 0
        and audit["badge_counts"].get("None", 0) == 0,
    }

    is_full_scrape = total_pages == detected_pages

    for label, passed in checks.items():
        if not is_full_scrape and label in (
            "Semua halaman berhasil",
            "Jumlah jurnal sesuai",
        ):
            print(f"[BELUM DINILAI] {label} (mode parsial)")
        else:
            print(f"[{'LULUS' if passed else 'GAGAL'}] {label}")

    all_passed = (
        is_full_scrape
        and all(checks.values())
    )

    if args.apply:
        if not all_passed:
            print("\n[DITOLAK] Audit belum lolos. Database tidak diubah.")
            return

        updated, not_found = sync_database(journals)

        print("\n===== HASIL SINKRONISASI DATABASE =====")
        print(f"Jurnal diperbarui : {updated}")
        print(f"ID tidak ditemukan: {not_found}")

    else:
        print("\nMODE DRY-RUN: database tidak diubah.")

        if all_passed:
            print("Audit lolos. Data siap dipertimbangkan untuk sinkronisasi.")
        else:
            print("Audit belum lolos. Periksa laporan sebelum sinkronisasi.")


if __name__ == "__main__":
    main()