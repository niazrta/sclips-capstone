import sys, os, re, time
from collections import Counter
sys.path.append(os.getcwd())
from bs4 import BeautifulSoup
from scraper.sinta_scraper import _safe_get, LIST_URL_TEMPLATE

PAGES = [1, 150, 400, 700, 1000, 1300, 1600, 1677]


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


links, stats, badges = Counter(), Counter(), Counter()
total = cover = garuda = 0
samples = {}

for p in PAGES:
    html = _safe_get(LIST_URL_TEMPLATE.format(page=p))
    if not html:
        print("gagal halaman", p)
        continue
    for it in BeautifulSoup(html, "html.parser").select("div.list-item.row.mt-3"):
        total += 1
        for a in it.select("div.affil-abbrev a[href]"):
            links[norm(a.get_text())] += 1
        for n in it.select("div.pr-num"):
            t = n.find_next_sibling("div", class_="pr-txt")
            lab = norm(t.get_text()) if t else "?"
            stats[lab] += 1
            samples.setdefault(lab, []).append(norm(n.get_text()))
        for s in it.select("span.num-stat"):
            badges[(" ".join(s.get("class", [])), norm(s.get_text()))] += 1
        img = it.select_one("img")
        if img and img.get("src"):
            cover += 1
            samples.setdefault("cover_src", []).append(img["src"])
        if it.select_one("a[href*=garuda]"):
            garuda += 1
    time.sleep(2)

print("Jurnal diperiksa:", total)
print("\nTautan di affil-abbrev :", dict(links))
print("\nStatistik               :", dict(stats))
print("\nBadge (kelas, teks)     :")
for k, v in badges.most_common():
    print("  ", v, k)
print("\nPunya gambar:", cover, "| punya tautan Garuda:", garuda)
for k, v in samples.items():
    print(f"\nContoh {k}:", v[:6])