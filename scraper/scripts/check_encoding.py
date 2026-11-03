import sys, os
sys.path.append(os.getcwd())
from config import config
from scraper.sinta_scraper import session, REQUEST_TIMEOUT

r = session.get(f"{config.SINTA_BASE_URL}/journals/profile/671", timeout=REQUEST_TIMEOUT)
print("content-type:", r.headers.get("content-type"), "| encoding:", r.encoding, "| apparent:", r.apparent_encoding)
j = r.content.find(b"rkiye")
if j >= 0:
    print("bytes :", r.content[j-3:j+6])
    k = r.text.find("rkiye")
    print("teks  :", repr(r.text[k-3:k+6]))
else:
    print("kata tidak ditemukan (halaman berubah)")