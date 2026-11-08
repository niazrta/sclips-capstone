import argparse
import time

from db.session import SessionLocal
from sync import engine, runs
from utils.logger import get_logger

logger = get_logger("sync.worker")
POLL_SECONDS = 30


def tick(from_dir=None, max_age_hours=24):
    """Satu putaran: pulihkan run macet, ambil satu baris queued, jalankan. Return True bila ada kerja."""
    db = SessionLocal()
    try:
        n = runs.recover_stale(db)
        if n:
            logger.warning(f"{n} run macet ditandai failed")
        run = runs.claim_next(db)
        if run is None:
            return False
        scope, rid = run.scope, run.id
    finally:
        db.close()

    logger.info(f"Menjalankan run {rid} (scope={scope})")
    try:
        engine.run(scope, apply=True, run_id=rid, from_dir=from_dir, max_age_hours=max_age_hours)
    except Exception as e:           # engine sudah menandai run failed
        logger.error(f"Run {rid} gagal: {e}")
    return True


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