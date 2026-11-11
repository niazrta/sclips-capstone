from scripts.recover_missing import fetch_profile
from scraper.sinta_scraper import parse_detail_page

ids = [26, 5383, 7937, 10104, 10240, 10699]

for jid in ids:
    html, state = fetch_profile(jid)

    print(f"\nID: {jid}")
    print(f"Status: {state}")

    if html:
        data = parse_detail_page(html)

        print("Rank:", data["current_rank"])
        print("History:", data["accreditation_history"])