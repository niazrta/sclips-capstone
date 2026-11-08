from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError

from db.models import SyncRun

STALE_AFTER = timedelta(minutes=10)
COUNTERS = {"total_processed", "total_inserted", "total_updated", "total_skipped",
            "total_flagged", "pages_failed", "sinta_total", "db_total_before"}


def _now():
    return datetime.now(timezone.utc)


def request_run(db, scope, trigger, source=None, requested_by=None, target_id=None):
    """Buat permintaan run. Return None kalau sudah ada run aktif (queued/running)."""
    run = SyncRun(scope=scope, trigger=trigger, source=source,
                  requested_by=requested_by, target_id=target_id, status="queued")
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    db.refresh(run)
    return run


def claim_next(db):
    """Ambil run queued tertua, ubah jadi running. Return None kalau tidak ada."""
    run = (db.query(SyncRun)
           .filter(SyncRun.status == "queued")
           .order_by(SyncRun.id)
           .with_for_update(skip_locked=True)
           .first())
    if run is None:
        return None
    run.status = "running"
    run.started_at = _now()
    run.heartbeat_at = run.started_at
    db.commit()
    return run


def heartbeat(db, run_id, **counters):
    """Perbarui detak dan angka progres."""
    run = db.get(SyncRun, run_id)
    run.heartbeat_at = _now()
    for k, v in counters.items():
        if k in COUNTERS:
            setattr(run, k, v)
    db.commit()


def finish(db, run_id, status, error=None):
    """Tutup run dengan status success, failed, atau paused."""
    if status not in ("success", "failed", "paused"):
        raise ValueError(f"status tidak valid: {status}")
    run = db.get(SyncRun, run_id)
    run.status = status
    run.finished_at = _now()
    run.error_message = error
    db.commit()


def recover_stale(db):
    """Tandai run 'running' yang detaknya berhenti sebagai gagal. Return jumlahnya."""
    limit = _now() - STALE_AFTER
    stale = (db.query(SyncRun)
             .filter(SyncRun.status == "running", SyncRun.heartbeat_at < limit)
             .all())
    for run in stale:
        run.status = "failed"
        run.finished_at = _now()
        run.error_message = "Proses berhenti (detak tidak diperbarui)"
    db.commit()
    return len(stale)