import sys, os, re
sys.path.append(os.getcwd())
from bs4 import BeautifulSoup
from config import config
from scraper.sinta_scraper import _safe_get, LIST_URL_TEMPLATE

os.makedirs("data/inventory", exist_ok=True)
IDS = [671, 693, 6784, 74, 115]  # S1 lokal, internasional, S3, tanpa riwayat, ISSN berawalan P


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


pages, links = {}, {}
for jid in IDS:
    html = _safe_get(f"{config.SINTA_BASE_URL}/journals/profile/{jid}")
    if not html:
        print(jid, "GAGAL diambil")
        continue
    with open(f"data/inventory/{jid}.html", "w", encoding="utf-8") as f:
        f.write(html)
    soup = BeautifulSoup(html, "html.parser")
    pages[jid] = soup
    links[jid] = {(norm(a.get_text()), a["href"], " ".join(i.get("class", [""])[-1] for i in a.find_all("i")))
                  for a in soup.find_all("a", href=True) if a["href"] not in ("#!", "#")}

common = set.intersection(*links.values()) if links else set()
print(f"Tautan yang sama di semua halaman (menu/footer, diabaikan): {len(common)}\n")

for jid, soup in pages.items():
    print("=" * 70)
    print("ID", jid, "|", norm(soup.select_one("h3").get_text()) if soup.select_one("h3") else "-")
    mp = soup.select_one("div.meta-profile")
    print("meta-profile:", norm(mp.get_text(" ")) if mp else None)
    print("\nStat card:")
    for card in soup.select(".stat-card .card-body"):
        print("  ", norm(card.select_one(".stat-text").get_text()) if card.select_one(".stat-text") else "?",
              "=", norm(card.select_one(".stat-num").get_text()) if card.select_one(".stat-num") else "?")
    print("\nTautan khusus jurnal ini (teks | href | ikon):")
    for t, h, ic in sorted(links[jid] - common):
        print("  ", t or "(tanpa teks)", "|", h, "|", ic)
    print("\nJudul kecil/tabel:", [norm(x.get_text()) for x in soup.select("p small")][:6])

html = _safe_get(LIST_URL_TEMPLATE.format(page=1))
item = BeautifulSoup(html, "html.parser").select_one("div.list-item.row.mt-3")
print("\n" + "=" * 70 + "\nSatu item di halaman listing:\n")
print(item.prettify())