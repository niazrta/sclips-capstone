import sys, os
sys.path.append(os.getcwd())
from datetime import datetime, timedelta, timezone

from db.session import SessionLocal
from db.models import SyncRun
from sync import runs

db = SessionLocal()
made = []
try:
    a = runs.request_run(db, "new", "manual")
    made.append(a.id)
    print("1. run pertama dibuat, status:", a.status)

    b = runs.request_run(db, "new", "manual")
    print("2. run kedua saat yang pertama aktif ->", b, "(harus None)")

    c = runs.claim_next(db)
    print("3. diambil:", c.id == a.id, "| status:", c.status)

    runs.heartbeat(db, a.id, total_processed=5, sinta_total=16768)
    print("4. progres tersimpan:", db.get(SyncRun, a.id).total_processed)

    runs.finish(db, a.id, "success")
    d = runs.request_run(db, "update", "scheduled")
    made.append(d.id)
    print("5. setelah selesai, run baru bisa dibuat:", d is not None)

    runs.claim_next(db)
    db.get(SyncRun, d.id).heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    db.commit()
    print("6. run macet ditandai gagal:", runs.recover_stale(db), "(harus 1)")
    print("   status:", db.get(SyncRun, d.id).status)
finally:
    db.rollback()
    db.query(SyncRun).filter(SyncRun.id.in_(made)).delete(synchronize_session=False)
    db.commit()
    db.close()