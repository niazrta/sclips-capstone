import sys, os, re, gzip, glob
sys.path.append(os.getcwd())
from bs4 import BeautifulSoup
from sqlalchemy import text
from config import config
from db.session import engine

INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200e\u200f\u202a\u202b\u202c\u202d\u202e\ufeff"))
PAT = {"e": r"E-ISSN\s*:\s*(.*?)\s*(?:\||P-ISSN|Subject Area|$)",
       "p": r"P-ISSN\s*:\s*(.*?)\s*(?:\||E-ISSN|Subject Area|$)"}

raw = {}
for path in glob.glob("data/raw_listing/page_*.html.gz"):
    soup = BeautifulSoup(gzip.open(path, "rt", encoding="utf-8").read(), "html.parser")
    for it in soup.select("div.list-item.row.mt-3"):
        a = it.select_one("div.affil-name > a")
        m = re.search(r"(\d+)/?$", a["href"]) if a and a.has_attr("href") else None
        pid = it.select_one("div.profile-id")
        if not m or not pid:
            continue
        txt = " ".join(pid.get_text(" ").split())
        raw[int(m.group(1))] = {k: (re.search(p, txt, re.I | re.S).group(1)
                                    if re.search(p, txt, re.I | re.S) else "").translate(INVISIBLE).strip()
                                for k, p in PAT.items()}

with engine.connect() as c:
    db = {r[0]: {"e": r[1], "p": r[2]} for r in c.execute(text("SELECT id, e_issn, p_issn FROM journals"))}
    low_db = c.execute(text("SELECT COUNT(*) FROM journals WHERE e_issn ~ 'x' OR p_issn ~ 'x'")).scalar()

url = lambda j: f"{config.SINTA_BASE_URL}/journals/profile/{j}"
print("Jurnal dibaca:", len(raw), "| nilai x kecil di DATABASE:", low_db)

print("\n=== 1. x KECIL di teks SINTA ===")
low = [(j, k, v) for j, d in sorted(raw.items()) for k, v in d.items() if re.fullmatch(r"\d{4}-?\d{3}x", v)]
print("Jumlah:", len(low), "(e:", sum(1 for x in low if x[1] == "e"), "| p:", sum(1 for x in low if x[1] == "p"), ")")
for j, k, v in low:
    print(f"  {j} | {k}-ISSN SINTA: {v} | DB: {db.get(j, {}).get(k)} | {url(j)}")

print("\n=== 2. Beda selain kapital (DB vs SINTA) ===")
norm = lambda s: re.sub(r"[-\s]", "", s or "").upper()
n = 0
for j, d in sorted(raw.items()):
    for k, v in d.items():
        old = db.get(j, {}).get(k)
        if old and v not in ("", "0", "-") and norm(old) != norm(v):
            n += 1
            print(f"  {j} | {k} | DB: {old} | SINTA: {v} | {url(j)}")
print("Jumlah:", n)