import sys, os, time
sys.path.append(os.getcwd())

from sqlalchemy import text
from db.session import engine
from scripts.recover_missing import fetch_profile
from scraper.sinta_scraper import parse_detail_page

with engine.connect() as c:
    null_ids = [r[0] for r in c.execute(text(
        "SELECT id FROM journals WHERE current_rank IS NULL AND is_active ORDER BY id LIMIT 5"
    ))]

for jid in [2, 23, 36, 671] + null_ids:
    html, state = fetch_profile(jid)

    if html is None:
        print(jid, "FETCH", state)
    else:
        try:
            d = parse_detail_page(html)
            print(
                jid,
                "OK  rank:", d["current_rank"],
                "| riwayat:", len(d["accreditation_history"])
            )
        except Exception as e:
            print(jid, "ERROR:", e)

    time.sleep(2)


from config import config
from scraper.sinta_scraper import session, REQUEST_TIMEOUT

home = session.get(
    config.SINTA_BASE_URL,
    timeout=REQUEST_TIMEOUT
).text

try:
    parse_detail_page(home)
    print("HOME: lolos (SALAH, validasi terlalu longgar)")
except Exception as e:
    print("HOME: ditolak (benar):", e)