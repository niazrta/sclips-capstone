import sys, os, re, gzip, glob, json
from collections import Counter, defaultdict
sys.path.append(os.getcwd())
from bs4 import BeautifulSoup
from scraper.cleaner import clean_issn

# 1. ISSN yang gagal dibaca, dari HTML mentah (bukan dari snapshot)
PAT = {"p": r"P-ISSN\s*:\s*(.*?)\s*(?:\||E-ISSN|Subject Area|$)",
       "e": r"E-ISSN\s*:\s*(.*?)\s*(?:\||P-ISSN|Subject Area|$)"}
bad, total = {"p": [], "e": []}, 0
for path in glob.glob("data/raw_listing/page_*.html.gz"):
    soup = BeautifulSoup(gzip.open(path, "rt", encoding="utf-8").read(), "html.parser")
    for it in soup.select("div.list-item.row.mt-3"):
        total += 1
        a = it.select_one("div.affil-name > a")
        jid = a["href"].rstrip("/").split("/")[-1] if a else "?"
        pid = it.select_one("div.profile-id")
        txt = " ".join(pid.get_text(" ").split()) if pid else ""
        for k, p in PAT.items():
            m = re.search(p, txt, re.I | re.S)
            raw = m.group(1).strip() if m else ""
            if raw and raw not in ("0", "-") and not clean_issn(re.sub(r"^[PE]\s*", "", raw)):
                bad[k].append((jid, raw))
print("Jurnal diperiksa:", total)
for k in bad:
    print(f"\n{k}-ISSN tidak terbaca: {len(bad[k])}")
    for jid, raw in sorted(bad[k])[:60]:
        print("  ", jid, repr(raw))

# 2. Nama penerbit yang tautannya ke afiliasi lain (kasus UGM)
d = json.load(open("data/listing_snapshot_v2.json", encoding="utf-8"))
rows = d["rows"] if isinstance(d, dict) else d
ids_by_name = defaultdict(Counter)
jur = defaultdict(list)
for r in rows:
    s = str(r.get("sinta_publisher_id") or "")
    n = r.get("publisher_name")
    if s.isdigit() and n:
        ids_by_name[n][s] += 1
        jur[(n, s)].append(r["sinta_journal_id"])
multi = {n: c for n, c in ids_by_name.items() if len(c) > 1}
print(f"\nNama dengan >1 afiliasi: {len(multi)}")
for n, c in sorted(multi.items(), key=lambda x: -sum(x[1].values()))[:25]:
    main = c.most_common(1)[0][0]
    for s, k in c.items():
        if s != main:
            print(f"  {n} | utama {main} ({c[main]} jurnal) | tautan lain {s}: jurnal {jur[(n, s)][:5]}")