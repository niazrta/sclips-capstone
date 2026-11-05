from scripts.recover_missing import fetch_profile
from bs4 import BeautifulSoup

html, state = fetch_profile(2)

print("Status:", state)

if html:
    soup = BeautifulSoup(html, "html.parser")

    print("\nTITLE:")
    print(soup.title.get_text(strip=True) if soup.title else "Tidak ditemukan")

    print("\nHEADING:")
    for h in soup.find_all(["h1", "h2", "h3"]):
        print(h.get_text(" ", strip=True))

    print("\nTABLE:")
    for table in soup.find_all("table"):
        print(table.get("class"))
        print(table.get_text(" ", strip=True)[:500])