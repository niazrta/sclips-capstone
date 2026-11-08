
import sys
import os
import json
import time

sys.path.append(os.getcwd())

from bs4 import BeautifulSoup
from sqlalchemy import text
from db.session import engine
from scripts.recover_missing import fetch_profile
from scraper.sinta_scraper import parse_detail_page


SNAPSHOT = "data/listing_snapshot_v2.json"


def main():
    with open(SNAPSHOT, encoding="utf-8") as f:
        rows = json.load(f)

    badge = {
        int(r["sinta_journal_id"]): r.get("rank_badge")
        for r in rows
        if r.get("sinta_journal_id")
    }

    with engine.connect() as conn:
        db = {
            row[0]: row[1]
            for row in conn.execute(
                text("SELECT id, current_rank FROM journals")
            )
        }

    ids = [
        jid for jid in badge
        if jid in db
        and (db[jid] or "NA") != (badge[jid] or "NA")
    ]

    print(f"Jumlah jurnal dengan perbedaan peringkat: {len(ids)}")
    print("\n===== PEMERIKSAAN PROFIL SINTA =====")

    for index, jid in enumerate(ids, 1):
        html, status = fetch_profile(jid)

        if not html:
            print(f"{jid} | FETCH: {status}")
            time.sleep(2)
            continue

        try:
            soup = BeautifulSoup(html, "html.parser")

            card_rank = None

            for card in soup.select(".stat-card .card-body"):
                label = card.select_one(".stat-text")

                if label and "creditation" in label.get_text(
                    " ", strip=True
                ).lower():
                    value = card.select_one(".stat-num")

                    if value:
                        card_rank = value.get_text(strip=True)

                    break

            detail = parse_detail_page(html)
            history = detail.get("accreditation_history", [])

            last_history = history[-1] if history else None

            print(
                f"{index}/{len(ids)} | ID {jid}"
                f" | DB: {db[jid]}"
                f" | Badge: {badge[jid]}"
                f" | Kartu profil: {card_rank}"
                f" | Riwayat terakhir: {last_history}"
            )

        except Exception as e:
            print(f"{jid} | ERROR: {e}")

        time.sleep(2)


if __name__ == "__main__":
    main()
