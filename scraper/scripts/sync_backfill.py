import sys, os, re, gzip, glob, json, argparse
sys.path.append(os.getcwd())
from collections import Counter, defaultdict
from bs4 import BeautifulSoup
from sqlalchemy import text
from db.session import engine

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200e\u200f\u202a\u202b\u202c\u202d\u202e\ufeff"))
PAT = {"p": r"P-ISSN\s*:\s*(.*?)\s*(?:\||E-ISSN|Subject Area|$)",
       "e": r"E-ISSN\s*:\s*(.*?)\s*(?:\||P-ISSN|Subject Area|$)"}


def classify(raw):
    raw = (raw or "").translate(INVISIBLE).strip()
    if raw in ("", "0", "-"):
        return None, "none"
    m = re.fullmatch(r"(\d{4})[\s\-\u2010-\u2015:_]?(\d{3}[\dXx])", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}", "valid"
    if re.fullmatch(r"[\dXx-]{1,7}", raw) and re.search(r"\d", raw):
        return raw, "short"
    return raw, "invalid"


# 1. teks ISSN mentah dari HTML listing
raw_issn = {}
for path in glob.glob("data/raw_listing/page_*.html.gz"):
    soup = BeautifulSoup(gzip.open(path, "rt", encoding="utf-8").read(), "html.parser")
    for it in soup.select("div.list-item.row.mt-3"):
        a = it.select_one("div.affil-name > a")
        m = re.search(r"(\d+)/?$", a["href"]) if a and a.has_attr("href") else None
        pid = it.select_one("div.profile-id")
        if not m or not pid:
            continue
        txt = " ".join(pid.get_text(" ").split())
        vals = {}
        for k, p in PAT.items():
            mm = re.search(p, txt, re.I | re.S)
            vals[k] = mm.group(1) if mm else ""
        raw_issn[int(m.group(1))] = vals
print("Jurnal terbaca dari HTML mentah:", len(raw_issn))

snap = json.load(open("data/listing_snapshot_v2.json", encoding="utf-8"))
srows = snap["rows"] if isinstance(snap, dict) else snap
info = {}
for r in srows:
    sid = str(r.get("sinta_publisher_id") or "")
    info[int(r["sinta_journal_id"])] = (r.get("publisher_name") or None,
                                        int(sid) if sid.isdigit() else None)

conn = engine.connect()
tx = conn.begin()
try:
    # 2. ISSN
    db = {r[0]: r[1:] for r in conn.execute(text(
        "SELECT id, e_issn, p_issn, e_issn_status, p_issn_status FROM journals"))}
    cat = {"e": Counter(), "p": Counter()}
    stat = {"e": Counter(), "p": Counter()}
    samples = defaultdict(list)
    upd = []
    for jid, (e_db, p_db, es_db, ps_db) in db.items():
        if jid not in raw_issn:
            continue
        row = {"id": jid}
        for k, old in (("e", e_db), ("p", p_db)):
            new, st = classify(raw_issn[jid][k])
            if new == old:
                c = "sama"
            elif old is None:
                c = "isi_baru"
            elif new is None:
                c = "dikosongkan"
            elif old.upper().endswith("X") and st == "short" and \
                 new.replace("-", "") == old.replace("-", "")[:-1]:
                c = "kembalikan_X"
            elif re.match(r"[PEpe]\s*\d", new) and \
                 re.sub(r"^[PEpe]\s*", "", new).replace("-", "") == old.replace("-", ""):
                c = "kembalikan_awalan"
            elif old.upper() == new.upper():
                c = "beda_kapital"
            elif st in ("short", "invalid"):
                c = "ikuti_sumber"
            else:
                c = "lain"
            cat[k][c] += 1
            stat[k][st] += 1
            if c not in ("sama", "isi_baru") and len(samples[(k, c)]) < (300 if c in ("lain", "ikuti_sumber") else 6):
                samples[(k, c)].append((jid, old, new))
            row[k + "_issn"], row[k + "_st"] = new, st
        if (row["e_issn"], row["e_st"], row["p_issn"], row["p_st"]) != (e_db, es_db, p_db, ps_db):
            upd.append(row)
    if upd:
        conn.execute(text("UPDATE journals SET e_issn=:e_issn, e_issn_status=:e_st, "
                          "p_issn=:p_issn, p_issn_status=:p_st WHERE id=:id"), upd)
    print("\nISSN e:", dict(cat["e"]), "| status:", dict(stat["e"]))
    print("ISSN p:", dict(cat["p"]), "| status:", dict(stat["p"]))
    for key, v in samples.items():
        print("  contoh", key, v)

    # 3. sinta_affiliation_id apa adanya dari tautan listing
    aff_old = {r[0]: r[1] for r in conn.execute(text("SELECT id, sinta_affiliation_id FROM journals"))}
    aff_upd = [{"id": j, "a": a} for j, (n, a) in info.items() if j in aff_old and aff_old[j] != a]
    if aff_upd:
        conn.execute(text("UPDATE journals SET sinta_affiliation_id=:a WHERE id=:id"), aff_upd)
    print("\nsinta_affiliation_id diperbarui:", len(aff_upd))

    # 4. penerbit: nama persis SINTA, tanpa menyalin label ML
    pubs = {r[0]: {"raw": r[1], "type": r[2], "sid": r[3]} for r in conn.execute(text(
        "SELECT id, raw_name, type, sinta_publisher_id FROM publishers"))}
    by_raw = {p["raw"]: i for i, p in pubs.items() if p["raw"]}
    jpub = {r[0]: r[1] for r in conn.execute(text("SELECT id, publisher_id FROM journals"))}
    need = sorted({n for j, (n, a) in info.items() if n and j in jpub} - set(by_raw))
    for n in need:
        nid = conn.execute(text("INSERT INTO publishers (name, raw_name, is_active) "
                                "VALUES (:n, :n, true) RETURNING id"), {"n": n}).scalar()
        by_raw[n] = nid
        pubs[nid] = {"raw": n, "type": None, "sid": None}

    moves, lost_label, used, ids = [], 0, set(), defaultdict(set)
    for j, (n, a) in info.items():
        if j not in jpub:
            continue
        target = by_raw[n] if n else None
        if target:
            used.add(target)
            if a:
                ids[target].add(a)
        if target != jpub[j]:
            moves.append({"id": j, "p": target})
            old_t = pubs[jpub[j]]["type"] if jpub[j] in pubs else None
            new_t = pubs[target]["type"] if target else None
            if old_t and not new_t:
                lost_label += 1
    if moves:
        conn.execute(text("UPDATE journals SET publisher_id=:p WHERE id=:id"), moves)
    renamed = conn.execute(text("UPDATE publishers SET name = raw_name "
                                "WHERE raw_name IS NOT NULL AND name IS DISTINCT FROM raw_name")).rowcount
    sid_upd = []
    for pid in used:
        val = next(iter(ids[pid])) if len(ids[pid]) == 1 else None
        if pubs[pid]["sid"] != val:
            sid_upd.append({"id": pid, "s": val})
    if sid_upd:
        conn.execute(text("UPDATE publishers SET sinta_publisher_id=:s WHERE id=:id"), sid_upd)
    orphan = conn.execute(text("SELECT COUNT(*) FROM publishers p WHERE NOT EXISTS "
                               "(SELECT 1 FROM journals j WHERE j.publisher_id = p.id)")).scalar()
    to_none = sum(1 for m in moves if m["p"] is None)
    print("Baris penerbit baru dibuat           :", len(need), need[:5])
    print("Jurnal dipindah ke baris lain/kosong  :", len(moves))
    print("Jurnal dipindah ke penerbit kosong    :", to_none)
    print("  ...yang kehilangan tipe (label ML)  :", lost_label)
    print("Nama penerbit diganti jadi teks SINTA :", renamed)
    print("publishers.sinta_publisher_id berubah :", len(sid_upd))
    print("Baris penerbit tanpa jurnal (tidak dihapus):", orphan)

    bad = sum(cat[k]["lain"] + cat[k]["dikosongkan"] for k in cat)
    if args.apply:
        if bad:
            raise SystemExit(f"DIBATALKAN: {bad} perubahan ISSN tak terduga (lain/dikosongkan). Periksa contohnya.")
        tx.commit()
        print("\nTERSIMPAN")
    else:
        tx.rollback()
        print("\nDRY-RUN: tidak ada yang diubah.")
except BaseException:
    tx.rollback()
    raise
finally:
    conn.close()