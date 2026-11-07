import glob
import gzip
import os
import re
import time
from datetime import datetime, timezone
from decimal import Decimal

import requests
from sqlalchemy import text

from config import config
from db.models import Journal, JournalRankHistory, Publisher, SyncChange
from db.session import SessionLocal
from scraper.sinta_scraper import (
    LIST_URL_TEMPLATE, REQUEST_TIMEOUT, _safe_get, parse_detail_page,
    parse_listing_page, session,
)
from sync import runs
from utils.logger import get_logger

logger = get_logger("sync.engine")

FIELDS = ["name", "subject", "e_issn", "e_issn_status", "p_issn", "p_issn_status",
          "sinta_affiliation_id", "rank_badge", "scopus_indexed", "garuda_indexed",
          "impact", "h5_index", "citations_5yr", "citations",
          "website", "editor_url", "google_scholar_url", "garuda_id", "cover_url"]
METRICS = {"impact", "h5_index", "citations_5yr", "citations"}
TOTALS = re.compile(r"Page\s+[\d.,]+\s+of\s+([\d.,]+)\s*\|\s*Total Records\s+([\d.,]+)", re.I)


def _num(s):
    return int(re.sub(r"[.,]", "", s))


def _norm(v):
    if isinstance(v, (Decimal, float)):
        return round(float(v), 2)
    return v


def read_listing(from_dir=None, save_dir=None):
    """Baca listing dari SINTA, atau dari salinan di from_dir."""
    pages = {}
    if from_dir:
        for path in glob.glob(os.path.join(from_dir, "page_*.html.gz")):
            n = int(re.search(r"page_(\d+)", os.path.basename(path)).group(1))
            with gzip.open(path, "rt", encoding="utf-8") as f:
                pages[n] = f.read()
        html1 = pages.get(1)
    else:
        html1 = _safe_get(LIST_URL_TEMPLATE.format(page=1))
    m = TOTALS.search(html1 or "")
    if not m:
        raise RuntimeError("Halaman 1 tidak terbaca atau Total Records tidak ditemukan")
    total_pages, total_records = _num(m.group(1)), _num(m.group(2))

    if from_dir:
        failed = [p for p in range(1, total_pages + 1) if p not in pages]
    else:
        pages[1], failed = html1, []
        for p in range(2, total_pages + 1):
            time.sleep(config.SCRAPE_DELAY_SECONDS)
            html = _safe_get(LIST_URL_TEMPLATE.format(page=p))
            if html is None:
                failed.append(p)
            else:
                pages[p] = html
            if p % 200 == 0:
                logger.info(f"Listing {p}/{total_pages}, gagal {len(failed)}")
        for p in list(failed):
            time.sleep(5)
            html = _safe_get(LIST_URL_TEMPLATE.format(page=p))
            if html is not None:
                pages[p] = html
                failed.remove(p)
        if save_dir and not failed:
            os.makedirs(save_dir, exist_ok=True)
            for n, html in pages.items():
                with gzip.open(os.path.join(save_dir, f"page_{n}.html.gz"), "wt", encoding="utf-8") as f:
                    f.write(html)

    rows = []
    for p in sorted(pages):
        rows.extend(parse_listing_page(pages[p]))
    ids = [r["sinta_journal_id"] for r in rows]
    complete = (not failed) and len(rows) == total_records and len(set(ids)) == len(ids)
    return {"rows": rows, "total_pages": total_pages, "total_records": total_records,
            "failed": failed, "complete": complete}


def fetch_profile(jid):
    """Ambil profil tanpa mengikuti alihan. Return (html, status)."""
    url = f"{config.SINTA_BASE_URL}/journals/profile/{jid}"
    for _ in range(3):
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=False)
        except requests.exceptions.RequestException:
            time.sleep(3)
            continue
        if r.status_code == 200:
            return r.text, "ok"
        if 300 <= r.status_code < 400:
            return None, "redirect"
        time.sleep(3)
    return None, "error"


def plan_update(db, rows):
    """Bandingkan listing dengan database. Hanya membaca."""
    jmap = {j.id: j for j in db.query(Journal).all()}
    pname = {p.id: p.name for p in db.query(Publisher).all()}
    plan, not_in_db = [], 0
    for r in rows:
        j = jmap.get(r["sinta_journal_id"])
        if j is None:
            not_in_db += 1
            continue
        changes = []
        for f in FIELDS:
            new = r.get("sinta_publisher_id") if f == "sinta_affiliation_id" else r.get(f)
            old = getattr(j, f)
            if _norm(old) != _norm(new):
                changes.append((f, old, new))
        cur_pub, new_pub = pname.get(j.publisher_id), r.get("publisher_name")
        if cur_pub != new_pub:
            changes.append(("publisher", cur_pub, new_pub))
        if changes:
            plan.append((j, r, changes))
    seen = {r["sinta_journal_id"] for r in rows if r["sinta_journal_id"] in jmap}
    return plan, seen, not_in_db


def _write_change(db, run_id, jid, field, old, new):
    db.add(SyncChange(run_id=run_id, journal_id=jid, field=field,
                      old_value=None if old is None else str(old),
                      new_value=None if new is None else str(new)))


def apply_journal(db, run_id, j, changes, pmap, now):
    for f, old, new in changes:
        if f == "publisher":
            if new is None:
                j.publisher_id = None
            else:
                pid = pmap.get(new)
                if pid is None:
                    p = Publisher(name=new, raw_name=new, is_active=True)  # tanpa tipe
                    db.add(p)
                    db.flush()
                    pid = pmap[new] = p.id
                j.publisher_id = pid
        else:
            setattr(j, f, Decimal(str(new)) if (f == "impact" and new is not None) else new)
        _write_change(db, run_id, j.id, f, old, new)
    if any(f in METRICS for f, _, _ in changes):
        j.metrics_updated_at = now


def apply_history(db, run_id, jid, history, now):
    """Tahun baru ditambah, tahun berbeda diperbarui, tidak ada yang dihapus."""
    existing = {h.accreditation_year: h for h in
                db.query(JournalRankHistory).filter_by(journal_id=jid).all()}
    for h in history:
        row = existing.get(h["year"])
        if row is None:
            db.add(JournalRankHistory(journal_id=jid, sinta_rank=h["rank"],
                                      accreditation_year=h["year"], updated_at=now))
            _write_change(db, run_id, jid, f"history_{h['year']}", None, h["rank"])
        elif row.sinta_rank != h["rank"]:
            _write_change(db, run_id, jid, f"history_{h['year']}", row.sinta_rank, h["rank"])
            row.sinta_rank, row.updated_at = h["rank"], now


def run_update(apply=False, from_dir=None, save_dir=None, limit=None, ids=None, max_age_hours=24):
    if apply and from_dir:
        age = (time.time() - os.path.getmtime(os.path.join(from_dir, "page_1.html.gz"))) / 3600
        if age > max_age_hours:
            print(f"DIBATALKAN: salinan listing berumur {age:.0f} jam (batas {max_age_hours}).")
            return
    data = read_listing(from_dir, save_dir)
    print(f"Halaman: {data['total_pages']} | Total Records: {data['total_records']} | "
          f"baris terbaca: {len(data['rows'])} | halaman gagal: {data['failed'][:10]}")
    print("Listing lengkap:", data["complete"])
    if not data["complete"]:
        print("DIBATALKAN: listing tidak lengkap, tidak ada yang ditulis.")
        return

    db = SessionLocal()
    run = None
    try:
        plan, seen, not_in_db = plan_update(db, data["rows"])
        if limit:
            plan = plan[:limit]
        if ids:
            plan = [(j, r, ch) for j, r, ch in plan if j.id in ids]
        by_field = {}
        for _, _, ch in plan:
            for f, _, _ in ch:
                by_field[f] = by_field.get(f, 0) + 1
        badge_ids = [j.id for j, _, ch in plan if any(f == "rank_badge" for f, _, _ in ch)]
        blanked = [j.id for j, _, ch in plan if any(f == "subject" and n is None for f, _, n in ch)]

        print(f"\nJurnal terbaca dan sudah ada di database : {len(seen)}")
        print(f"Jurnal di listing tapi belum ada (diabaikan): {not_in_db}")
        print(f"Jurnal yang berubah                      : {len(plan)}")
        print("Perubahan per field                      :", by_field)
        print(f"Subject dikosongkan                      : {len(blanked)} {blanked[:10]}")
        print(f"Profil akan dibuka (badge berubah)       : {len(badge_ids)} {badge_ids[:10]}")
        for j, _, ch in plan[:15]:
            print(" ", j.id, [(f, o, n) for f, o, n in ch][:4])

        if not apply:
            print("\nDRY-RUN: tidak ada yang diubah.")
            return

        run = runs.request_run(db, "update", "manual", requested_by="cli")
        if run is None:
            print("Sudah ada run aktif, dibatalkan.")
            return
        runs.claim_next(db)
        now = datetime.now(timezone.utc)
        pmap = {p.name: p.id for p in db.query(Publisher).all()}
        profile_fail = 0

        for n, (j, r, ch) in enumerate(plan, 1):
            apply_journal(db, run.id, j, ch, pmap, now)
            if j.id in badge_ids:
                html, state = fetch_profile(j.id)
                time.sleep(config.SCRAPE_DELAY_SECONDS)
                try:
                    if html is None:
                        raise ValueError(f"profil {state}")
                    apply_history(db, run.id, j.id, parse_detail_page(html)["accreditation_history"], now)
                    j.last_detail_scraped_at = now
                except Exception as e:
                    profile_fail += 1
                    logger.warning(f"{j.id}: profil dilewati ({e})")
            db.commit()
            if n % 50 == 0:
                runs.heartbeat(db, run.id, total_processed=n)

        db.execute(text("UPDATE journals SET last_seen_at = :ts WHERE id = ANY(:ids)"),
                   {"ts": now, "ids": list(seen)})
        db.commit()
        runs.heartbeat(db, run.id, sinta_total=data["total_records"], total_processed=len(seen),
                       total_updated=len(plan), total_skipped=len(seen) - len(plan))
        runs.finish(db, run.id, "success",
                    error=f"{profile_fail} profil dilewati" if profile_fail else None)
        print("\nTERSIMPAN. Profil dilewati:", profile_fail)
    except Exception as e:
        db.rollback()
        if run is not None:
            runs.finish(db, run.id, "failed", error=str(e)[:500])
        raise
    finally:
        db.close()