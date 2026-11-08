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
from db.models import Journal, JournalRankHistory, JournalStatus, Publisher, SyncChange, SyncRun
from db.session import SessionLocal, engine as db_engine
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

MAX_CEK_KANDIDAT = 100   # lebih dari ini: run dijeda, profil tidak dicek
MAX_TANDAI = 20          # lebih dari ini terkonfirmasi hilang: tidak ada yang ditandai


# ---------- membaca SINTA ----------

def _num(s):
    return int(re.sub(r"[.,]", "", s))


def _norm(v):
    if isinstance(v, (Decimal, float)):
        return round(float(v), 2)
    return v


def read_listing(from_dir=None, save_dir=None, on_progress=None):
    """Baca seluruh listing dari SINTA, atau dari salinan di from_dir."""
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
            if p % 50 == 0 and on_progress:
                on_progress()
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


def _check_candidates(cands, control_id):
    """Buka profil tiap kandidat tanpa mengikuti alihan. Hanya membaca.
    Jurnal kontrol (ada di listing) harus terbuka normal dulu, kalau tidak alihan tidak dipercaya."""
    html, state = fetch_profile(control_id)
    time.sleep(config.SCRAPE_DELAY_SECONDS)
    if state != "ok":
        print(f"Kontrol gagal: profil {control_id} berstatus '{state}'. Tidak ada kandidat yang dipercaya.")
        return [], [], list(cands)
    print(f"Kontrol lolos: profil {control_id} terbuka normal.")
    confirmed, still_open, unknown = [], [], []
    for jid in cands:
        html, state = fetch_profile(jid)
        time.sleep(config.SCRAPE_DELAY_SECONDS)
        if state == "redirect":
            confirmed.append(jid)
        elif state == "ok":
            try:
                parse_detail_page(html)
                still_open.append(jid)
            except Exception:
                unknown.append(jid)
        else:
            unknown.append(jid)
    return confirmed, still_open, unknown


# ---------- membandingkan dan menulis ----------

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


def _publisher_id(db, pmap, name):
    """ID penerbit untuk nama SINTA persis. Dibuat tanpa tipe bila belum ada."""
    if name is None:
        return None
    pid = pmap.get(name)
    if pid is None:
        p = Publisher(name=name, raw_name=name, is_active=True)
        db.add(p)
        db.flush()
        pid = pmap[name] = p.id
    return pid


def apply_journal(db, run_id, j, changes, pmap, now):
    for f, old, new in changes:
        if f == "publisher":
            j.publisher_id = _publisher_id(db, pmap, new)
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


def _new_journal(r, publisher_id, now):
    vals = {f: (r.get("sinta_publisher_id") if f == "sinta_affiliation_id" else r.get(f)) for f in FIELDS}
    if vals["impact"] is not None:
        vals["impact"] = Decimal(str(vals["impact"]))
    return Journal(id=r["sinta_journal_id"], publisher_id=publisher_id, is_active=True,
                   status=JournalStatus.active, last_seen_at=now, metrics_updated_at=now, **vals)


def _fresh(from_dir, max_age_hours):
    age = (time.time() - os.path.getmtime(os.path.join(from_dir, "page_1.html.gz"))) / 3600
    if age > max_age_hours:
        print(f"DIBATALKAN: salinan listing berumur {age:.0f} jam (batas {max_age_hours}).")
        return False
    return True


# ---------- satu program untuk tiga cakupan ----------

def run(scope, apply=False, from_dir=None, save_dir=None, limit=None, ids=None,
        max_age_hours=24, force_read=False, run_id=None):
    if scope not in ("new", "update", "full"):
        raise ValueError(f"cakupan tidak dikenal: {scope}")
    if apply and from_dir and not _fresh(from_dir, max_age_hours):
        if run_id is not None:
            d = SessionLocal()
            runs.finish(d, run_id, "failed", error="salinan listing terlalu tua")
            d.close()
        return
    print("Database:", db_engine.url.database)
    do_update = scope in ("update", "full")
    do_new = scope in ("new", "full")
    db = SessionLocal()
    run_row = None

    def finish(status, note=None, **counters):
        if run_row is not None:
            runs.heartbeat(db, run_row.id, **counters)
            runs.finish(db, run_row.id, status, error=note)
        print(f"\nSTATUS: {status}" + (f" ({note})" if note else ""))

    try:
        if run_id is not None:
            run_row = db.get(SyncRun, run_id)      # baris queued yang sudah diklaim worker
        elif apply:
            run_row = runs.request_run(db, scope, "manual", requested_by="cli")
            if run_row is None:
                print("Sudah ada run aktif, dibatalkan.")
                return
            runs.claim_next(db)

        active_total = db.query(Journal).filter(Journal.is_active.is_(True)).count()

        # pra-pengecekan murah: hanya cakupan 'new'
        if scope == "new" and not from_dir and not force_read:
            m = TOTALS.search(_safe_get(LIST_URL_TEMPLATE.format(page=1)) or "")
            if not m:
                raise RuntimeError("Halaman 1 tidak terbaca atau Total Records tidak ditemukan")
            sinta_total = _num(m.group(2))
            print(f"Total Records SINTA: {sinta_total} | jurnal aktif di database: {active_total}")
            if sinta_total == active_total:
                finish("success", "angka sama, listing tidak dibaca",
                       sinta_total=sinta_total, db_total_before=active_total)
                return

        beat = (lambda: runs.heartbeat(db, run_row.id)) if run_row else None
        data = read_listing(from_dir, save_dir, on_progress=beat)
        print(f"Halaman: {data['total_pages']} | Total Records: {data['total_records']} | "
              f"baris terbaca: {len(data['rows'])} | halaman gagal: {data['failed'][:10]}")
        print("Listing lengkap:", data["complete"])
        if not data["complete"]:
            finish("paused", "listing tidak lengkap, tidak ada yang ditulis",
                   sinta_total=data["total_records"], db_total_before=active_total)
            return

        rows = {r["sinta_journal_id"]: r for r in data["rows"]}
        known = {j.id: j for j in db.query(Journal).all()}
        seen_ids = [i for i in rows if i in known]

        # --- rencana pembaruan ---
        plan, badge_ids = [], set()
        if do_update:
            plan, _, not_in_db = plan_update(db, data["rows"])
            if ids:
                plan = [p for p in plan if p[0].id in ids]
            if limit:
                plan = plan[:limit]
            by_field = {}
            for _, _, ch in plan:
                for f, _, _ in ch:
                    by_field[f] = by_field.get(f, 0) + 1
            badge_ids = {j.id for j, _, ch in plan if any(f == "rank_badge" for f, _, _ in ch)}
            blanked = [j.id for j, _, ch in plan if any(f == "subject" and n is None for f, _, n in ch)]
            print(f"\nJurnal terbaca dan sudah ada di database : {len(seen_ids)}")
            if scope == "update":
                print(f"Jurnal di listing tapi belum ada (diabaikan): {not_in_db}")
            print(f"Jurnal yang berubah                      : {len(plan)}")
            print("Perubahan per field                      :", by_field)
            print(f"Subject dikosongkan                      : {len(blanked)} {blanked[:10]}")
            print(f"Profil akan dibuka (badge berubah)       : {len(badge_ids)} {sorted(badge_ids)[:10]}")
            for j, _, ch in plan[:40]:
                print(" ", j.id, [(f, o, n) for f, o, n in ch][:6])

        # --- rencana jurnal baru, muncul lagi, hilang ---
        new_ids, back, cands, esc_c = [], [], [], []
        confirmed, esc_conf, unknown, hold = [], [], [], None
        if do_new:
            new_ids = sorted(set(rows) - set(known))
            back = sorted(i for i in rows if i in known and not known[i].is_active)
            cands = sorted(i for i, j in known.items() if j.is_active and i not in rows)
            if scope == "full":
                esc_c = sorted(i for i, j in known.items()
                               if j.status == JournalStatus.unverified and i not in rows)
            print(f"\nJurnal baru di SINTA          : {len(new_ids)} {new_ids[:10]}")
            print(f"Muncul lagi di listing        : {len(back)} {[(i, known[i].status.value) for i in back[:10]]}")
            print(f"Kandidat hilang dari listing  : {len(cands)} {cands[:10]}")
            if scope == "full":
                print(f"Unverified masih absen        : {len(esc_c)} {esc_c[:10]}")

            check = []
            if len(cands) > MAX_CEK_KANDIDAT:
                hold = (f"{len(cands)} kandidat hilang (lebih dari {MAX_CEK_KANDIDAT}), "
                        "tidak diperiksa dan tidak ada yang ditandai")
            else:
                check = cands + (esc_c if len(esc_c) <= MAX_CEK_KANDIDAT else [])
            if check:
                conf_all, open_all, unknown = _check_candidates(check, next(iter(rows)))
                cs, es = set(cands), set(esc_c)
                confirmed = [i for i in conf_all if i in cs]
                esc_conf = [i for i in conf_all if i in es]
                print(f"  profil dialihkan (terkonfirmasi hilang): {len(confirmed)} {confirmed[:10]}")
                print(f"  profil masih terbuka (tidak ditandai)  : {len([i for i in open_all if i in cs])}")
                print(f"  tidak dapat dipastikan (tidak ditandai): {len(unknown)} {unknown[:10]}")
                if scope == "full":
                    print(f"  unverified masih dialihkan (jadi inactive): {len(esc_conf)} {esc_conf[:10]}")
                if len(confirmed) > MAX_TANDAI:
                    hold = (f"{len(confirmed)} terkonfirmasi hilang (lebih dari {MAX_TANDAI}), "
                            "tidak ada yang ditandai")
            if hold:
                print("\nDIJEDA:", hold)

        if not apply:
            print("\nDRY-RUN: tidak ada yang diubah.")
            return

        # --- menulis ---
        now = datetime.now(timezone.utc)
        seen_at = (datetime.fromtimestamp(os.path.getmtime(os.path.join(from_dir, "page_1.html.gz")),
                                          timezone.utc) if from_dir else now)
        pmap = {p.name: p.id for p in db.query(Publisher).all()}
        inserted = profile_fail = row_fail = 0

        for n, (j, r, ch) in enumerate(plan, 1):
            apply_journal(db, run_row.id, j, ch, pmap, now)
            if j.id in badge_ids:
                html, state = fetch_profile(j.id)
                time.sleep(config.SCRAPE_DELAY_SECONDS)
                try:
                    if html is None:
                        raise ValueError(f"profil {state}")
                    apply_history(db, run_row.id, j.id, parse_detail_page(html)["accreditation_history"], now)
                    j.last_detail_scraped_at = now
                except Exception as e:
                    profile_fail += 1
                    logger.warning(f"{j.id}: profil dilewati ({e})")
            db.commit()
            if n % 50 == 0:
                runs.heartbeat(db, run_row.id, total_processed=n)

        for n, jid in enumerate(new_ids, 1):
            try:
                r = rows[jid]
                db.add(_new_journal(r, _publisher_id(db, pmap, r.get("publisher_name")), seen_at))
                db.flush()
                _write_change(db, run_row.id, jid, "journal_baru", None, r["name"])
                html, state = fetch_profile(jid)
                time.sleep(config.SCRAPE_DELAY_SECONDS)
                try:
                    if html is None:
                        raise ValueError(f"profil {state}")
                    apply_history(db, run_row.id, jid, parse_detail_page(html)["accreditation_history"], now)
                    db.get(Journal, jid).last_detail_scraped_at = now
                except Exception as e:
                    profile_fail += 1
                    logger.warning(f"{jid}: riwayat tidak diambil ({e})")
                db.commit()
                inserted += 1
            except Exception as e:
                db.rollback()
                pmap = {p.name: p.id for p in db.query(Publisher).all()}
                row_fail += 1
                logger.error(f"{jid}: gagal dimasukkan ({e})")
            if n % 20 == 0:
                runs.heartbeat(db, run_row.id)

        for jid in back:
            j = known[jid]
            if j.status == JournalStatus.unverified:
                _write_change(db, run_row.id, jid, "status", "unverified", "active")
                j.status, j.is_active, j.last_seen_at = JournalStatus.active, True, seen_at
            else:
                logger.warning(f"{jid}: berstatus {j.status.value} tetapi muncul lagi di listing, tidak diubah")
        db.commit()

        escalated = 0
        if do_new:
            if hold is None:
                for jid in confirmed:
                    j = known[jid]
                    _write_change(db, run_row.id, jid, "status", j.status.value, "unverified")
                    j.status, j.is_active = JournalStatus.unverified, False
                if esc_conf and len(esc_conf) <= MAX_TANDAI:
                    for jid in esc_conf:
                        _write_change(db, run_row.id, jid, "status", "unverified", "inactive")
                        known[jid].status = JournalStatus.inactive
                        escalated += 1
            else:
                for jid in (cands if len(cands) > MAX_CEK_KANDIDAT else confirmed):
                    _write_change(db, run_row.id, jid, "kandidat_hilang", "active", None)
            db.commit()

        db.execute(text("UPDATE journals SET last_seen_at = :ts WHERE id = ANY(:ids)"),
                   {"ts": seen_at, "ids": seen_ids})
        db.commit()

        notes = [hold] if hold else []
        if escalated:
            notes.append(f"{escalated} jurnal unverified menjadi inactive")
        if unknown:
            notes.append(f"{len(unknown)} kandidat tidak dapat dipastikan")
        if profile_fail:
            notes.append(f"{profile_fail} profil dilewati")
        if row_fail:
            notes.append(f"{row_fail} jurnal gagal dimasukkan")
        finish("paused" if hold else "success", "; ".join(notes) or None,
               sinta_total=data["total_records"], db_total_before=active_total,
               total_processed=len(rows), total_inserted=inserted, total_updated=len(plan),
               total_skipped=len(seen_ids) - len(plan),
               total_flagged=0 if hold else len(confirmed))
    except Exception as e:
        db.rollback()
        if run_row is not None:
            runs.finish(db, run_row.id, "failed", error=str(e)[:500])
        raise
    finally:
        db.close()


def run_update(**kw):
    return run("update", **kw)


def run_new(**kw):
    return run("new", **kw)


def run_full(**kw):
    return run("full", **kw)