"""Worker sinkronisasi: memeriksa jadwal, mengambil run dari antrean, menjalankan engine.

Tiga jalur masuk (jadwal, baris manual di sync_runs, terminal) berakhir di engine.run.
Setelah run sukses, prediksi ML dijalankan bila run_ml_predict aktif.
"""
import argparse
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from db.models import SyncRun, SyncSchedule
from db.session import SessionLocal
from sync import engine, ml, runs
from utils.logger import get_logger

logger = get_logger("sync.worker")
POLL_SECONDS = 30


def next_run(s, after):
    """Waktu jalan berikutnya (UTC) setelah 'after'. Return None bila jadwal sekali jalan sudah lewat."""
    tz = ZoneInfo(s.timezone)
    base = after.astimezone(tz)
    if s.frequency == "date":
        t = datetime.combine(s.run_date, s.run_time, tz)
        return t.astimezone(timezone.utc) if t > base else None
    for i in range(0, 62):
        d = (base + timedelta(days=i)).date()
        t = datetime.combine(d, s.run_time, tz)
        if t <= base:
            continue
        if s.frequency == "daily":
            ok = True
        elif s.frequency == "weekly":
            ok = d.weekday() in (s.weekdays or [])
        elif s.frequency == "monthly":
            ok = d.day == s.month_day
        else:
            return None            # cron belum didukung
        if ok:
            return t.astimezone(timezone.utc)
    return None


def schedule_due(db):
    """Buat satu baris queued untuk tiap jadwal aktif yang jatuh tempo. Return jumlahnya."""
    now = datetime.now(timezone.utc)
    made = 0
    for s in db.query(SyncSchedule).filter(SyncSchedule.is_active.is_(True)).all():
        if s.next_run_at is None:                  # jadwal baru dinyalakan
            s.next_run_at = next_run(s, now)
            db.commit()
            continue
        if s.next_run_at > now:
            continue
        run = runs.request_run(db, s.scope, "scheduled", requested_by=s.name,
                               run_ml_predict=s.after_ml_predict)
        if run is None:                            # ada run aktif, coba lagi di putaran berikutnya
            continue
        s.last_run_at, s.next_run_at = now, next_run(s, now)
        if s.next_run_at is None and s.frequency == "date":
            s.is_active = False
        db.commit()
        made += 1
    return made


def tick(from_dir=None, max_age_hours=24):
    """Satu putaran: pulihkan run macet, ambil satu baris queued, jalankan. Return True bila ada kerja."""
    db = SessionLocal()
    try:
        n = runs.recover_stale(db)
        if n:
            logger.warning(f"{n} run macet ditandai failed")
        schedule_due(db)
        run = runs.claim_next(db)
        if run is None:
            return False
        scope, rid, target, with_ml, source = run.scope, run.id, run.target_id, run.run_ml_predict, run.source
    finally:
        db.close()

    logger.info(f"Menjalankan run {rid} (scope={scope}, target={target}, ml={with_ml})")
    try:
        engine.run(scope, apply=True, run_id=rid, from_dir=from_dir, max_age_hours=max_age_hours,
                   ids={target} if target else None, source=source)
    except Exception as e:           # engine sudah menandai run failed
        logger.error(f"Run {rid} gagal: {e}")
        return True
    if with_ml:
        _predict_after(rid)
    return True


def _predict_after(rid):
    """Prediksi ML setelah run sukses. Kegagalan dicatat di run, status sinkronisasi tidak berubah."""
    db = SessionLocal()
    try:
        run = db.get(SyncRun, rid)
        if run.status != "success":
            return
        try:
            res = ml.predict_pending(db, run_id=rid)
            note = f"prediksi ML: {res['predicted']} jurnal"
        except ml.MLNotConfigured as e:
            note = f"prediksi ML dilewati ({e})"
        except Exception as e:
            db.rollback()
            note = f"prediksi ML gagal ({str(e)[:200]})"
            logger.error(f"Run {rid}: {note}")
        run = db.get(SyncRun, rid)
        run.error_message = (f"{run.error_message}; " if run.error_message else "") + note
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="python -m sync.worker")
    ap.add_argument("--once", action="store_true", help="satu putaran saja lalu berhenti (uji)")
    ap.add_argument("--from-dir", default=None, help="uji: baca listing dari salinan")
    ap.add_argument("--max-age-hours", type=float, default=24)
    a = ap.parse_args()

    while True:
        worked = tick(a.from_dir, a.max_age_hours)
        if a.once:
            break
        if not worked:
            time.sleep(POLL_SECONDS)
