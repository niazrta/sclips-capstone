import sys, os, csv, json, time, argparse
sys.path.append(os.getcwd())
from collections import defaultdict
from datetime import datetime, timezone

from config import config
from db.session import SessionLocal
from db.models import Journal, Publisher, JournalRankHistory, JournalStatus
from scraper.cleaner import normalize_publisher_name, clean_issn
import requests
from scraper.sinta_scraper import session, REQUEST_TIMEOUT, parse_detail_page
from utils.logger import get_logger

logger = get_logger("recover")

SNAPSHOT = "data/listing_snapshot.json"
AFFECTED = "data/affected_ids.json"
DONE = "data/recover_done.txt"
REVIEW = "data/recover_review.txt"
MAX_FLAG = 50  # pengaman: kalau lebih dari ini ID "ekstra", ada yang salah


def phase_a(db):
    with open(SNAPSHOT, encoding="utf-8") as f:
        snap = json.load(f)
    by_id = {int(j["sinta_journal_id"]): j for j in snap if j.get("sinta_journal_id")}
    now = datetime.now(timezone.utc)
    stats = defaultdict(int)

    # e-ISSN yang dipakai >1 jurnal: simpan untuk laporan, dan tandai untuk ambil detail ulang
    groups = defaultdict(list)
    for i, j in by_id.items():
        e = clean_issn(j.get("e_issn"))
        if e:
            groups[e].append(i)
    shared = {e: ids for e, ids in groups.items() if len(ids) > 1}
    with open("data/shared_eissn.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["e_issn", "sinta_id", "name"])
        for e, ids in sorted(shared.items()):
            for i in sorted(ids):
                w.writerow([e, i, by_id[i]["name"]])
    affected = {i for ids in shared.values() for i in ids}

    existing = {r.id: r for r in db.query(Journal).all()}
    all_pubs = db.query(Publisher).all()
    pubs = {}
    for p in all_pubs:
        pubs.setdefault(p.name, p)
    pub_name_by_id = {p.id: p.name for p in all_pubs}

    def get_pub(j):
        raw = j.get("publisher_name")
        if not raw:
            return None, None
        name = normalize_publisher_name(raw) or "Unknown"
        pub = pubs.get(name)
        if pub is None:
            pub = Publisher(name=name, raw_name=raw, is_active=True)
            db.add(pub)
            db.flush()
            pubs[name] = pub
            pub_name_by_id[pub.id] = name
            stats["publisher_baru"] += 1
        sid = str(j.get("sinta_publisher_id") or "")
        if sid.isdigit() and pub.sinta_publisher_id is None:
            pub.sinta_publisher_id = int(sid)
        return pub, name

    for i, j in by_id.items():
        pub, pub_name = get_pub(j)
        e, p = clean_issn(j.get("e_issn")), clean_issn(j.get("p_issn"))
        subj = j.get("subject") or None
        row = existing.get(i)

        if row is None:
            db.add(Journal(
                id=i, name=j["name"], e_issn=e, p_issn=p, sinta_url=j["sinta_url"],
                publisher_id=pub.id if pub else None, subject=subj,
                is_active=True, status=JournalStatus.active, last_seen_at=now,
            ))
            stats["insert"] += 1
            affected.add(i)
            continue

        dirty = False
        for field, new in (("name", j["name"]), ("e_issn", e), ("p_issn", p)):
            if getattr(row, field) != new:
                stats["ubah_" + field] += 1
                setattr(row, field, new)
                dirty = True
        if pub and pub_name_by_id.get(row.publisher_id) != pub_name:
            row.publisher_id = pub.id
            stats["ubah_publisher"] += 1
            dirty = True
        if subj and row.subject != subj:
            row.subject = subj
            stats["ubah_subject"] += 1
        if dirty:
            affected.add(i)
        row.last_seen_at = now
        if not row.is_active or row.status != JournalStatus.active:
            stats["aktif_kembali"] += 1
            row.is_active = True
            row.status = JournalStatus.active
            affected.add(i)

    extra = sorted(set(existing) - set(by_id))
    if len(extra) > MAX_FLAG:
        raise SystemExit(f"{len(extra)} jurnal di DB tidak ada di snapshot. Terlalu banyak, dibatalkan.")
    for i in extra:
        r = existing[i]
        if r.is_active:
            stats["tandai_unverified"] += 1
        r.is_active = False
        r.status = JournalStatus.unverified

    return stats, sorted(affected), extra

def fetch_profile(jid):
    url = f"{config.SINTA_BASE_URL}/journals/profile/{jid}"

    for _ in range(3):
        try:
            r = session.get(
                url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False
            )
        except requests.exceptions.RequestException:
            time.sleep(3)
            continue

        if r.status_code == 200:
            return r.text, "ok"

        if 300 <= r.status_code < 400:
            return None, "redirect"

        time.sleep(3)

    return None, "error"

def phase_b(db, ids):
    done = set()
    if os.path.exists(DONE):
        with open(DONE) as f:
            done = {int(x) for x in f.read().split()}
    todo = [i for i in ids if i not in done]
    logger.info(f"Detail: {len(todo)} jurnal ({len(done)} sudah selesai sebelumnya)")

    fail_streak = 0
    for n, jid in enumerate(todo, 1):
        html, state = fetch_profile(jid)
        if state == "redirect":
            with open(REVIEW, "a") as f:
                f.write(f"{jid}\n")
            logger.warning(f"{jid}: profil dialihkan, dilewati (lihat {REVIEW})")
            time.sleep(config.SCRAPE_DELAY_SECONDS)
            continue
        if html is None:
            fail_streak += 1
            if fail_streak >= 10:
                logger.error("10 gagal beruntun, berhenti. Lanjutkan nanti dengan --detail-only")
                break
            time.sleep(config.SCRAPE_DELAY_SECONDS)
            continue
        fail_streak = 0
        try:
            d = parse_detail_page(html)
            hist = d["accreditation_history"]

            q = db.query(JournalRankHistory).filter(
                JournalRankHistory.journal_id == jid
            )

            if not hist and q.count() > 0:
                with open(REVIEW, "a") as f:
                    f.write(f"{jid}\n")

                logger.warning(
                    f"{jid}: riwayat kosong padahal sebelumnya ada, "
                    f"tidak diubah (lihat {REVIEW})"
                )

            else:
                q.delete()

                for h in hist:
                    db.add(JournalRankHistory(
                        journal_id=jid,
                        sinta_rank=h["rank"],
                        accreditation_year=h["year"]
                    ))

                db.get(Journal, jid).current_rank = d["current_rank"]
                db.commit()

                with open(DONE, "a") as f:
                    f.write(f"{jid}\n")
        except Exception as e:
            db.rollback()
            with open(REVIEW, "a") as f:
                f.write(f"{jid}\n")
            logger.error(f"{jid}: gagal ({e})")
        if n % 100 == 0:
            logger.info(f"Detail {n}/{len(todo)}")
        time.sleep(config.SCRAPE_DELAY_SECONDS)
    logger.info("Selesai tahap detail")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--detail-only", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        if args.detail_only:
            with open(AFFECTED) as f:
                ids = json.load(f)
        else:
            stats, affected, extra = phase_a(db)
            print("\n===== RENCANA PERUBAHAN =====")
            for k, v in sorted(stats.items()):
                print(f"{k:22}: {v}")
            print(f"{'detail diambil ulang':22}: {len(affected)}")
            print("ID dinonaktifkan      :", extra)
            if not args.apply:
                db.rollback()
                print("\nDRY-RUN: tidak ada yang diubah. Tambahkan --apply untuk menjalankan.")
                return
            db.commit()
            prev = []
            if os.path.exists(AFFECTED):
                with open(AFFECTED) as f:
                    prev = json.load(f)
            ids = sorted(set(prev) | set(affected))
            with open(AFFECTED, "w") as f:
                json.dump(ids, f)
        phase_b(db, ids)
    finally:
        db.close()


if __name__ == "__main__":
    main()