"""Uji antrean sinkronisasi: python tests/test_runs.py (memakai DATABASE_URL; gunakan database uji)."""
import os
import sys
import time

sys.path.append(os.getcwd())

from db.models import SyncRun
from db.session import SessionLocal
from sync import runs

db = SessionLocal()
ok = True


def check(name, cond):
    global ok
    ok = ok and bool(cond)
    print(("OK    " if cond else "GAGAL ") + name)


def raises(fn, exc):
    try:
        fn()
    except exc:
        return True
    return False


db.query(SyncRun).filter(SyncRun.requested_by.like("uji-%")).delete(synchronize_session=False)
db.commit()
assert db.query(SyncRun).filter(SyncRun.status.in_(["queued", "running"])).count() == 0, \
    "ada run aktif; gunakan database uji"

# 1. satu run aktif pada satu waktu
a = runs.request_run(db, "update", "manual", requested_by="uji-1")
b = runs.request_run(db, "full", "manual", requested_by="uji-2")
check("run kedua ditolak selama ada run aktif", a is not None and b is None)

# 2. cakupan dan target_id divalidasi
check("cakupan 'new' ditolak", raises(lambda: runs.request_run(db, "new", "manual"), ValueError))
check("target_id untuk 'full' ditolak", raises(lambda: runs.request_run(db, "full", "manual", target_id=1), ValueError))

# 3. klaim, detak, pengukuran, selesai
c = runs.claim_next(db)
check("klaim mengubah status menjadi running", c.id == a.id and c.status == "running")
runs.heartbeat(db, a.id, total_processed=5, http_requests=7, bytes_downloaded=1234, ram_peak_mb=50.5,
               host_info="{}", tidak_dikenal=1)
time.sleep(0.2)
runs.finish(db, a.id, "success")
r = db.get(SyncRun, a.id)
check("angka progres dan pengukuran tersimpan", r.total_processed == 5 and r.http_requests == 7
      and r.bytes_downloaded == 1234 and float(r.ram_peak_mb) == 50.5)
check("duration_seconds terisi", r.duration_seconds is not None and float(r.duration_seconds) >= 0)
check("status tidak valid ditolak", raises(lambda: runs.finish(db, a.id, "selesai"), ValueError))

# 4. update satu jurnal dan opsi ML tersimpan pada baris run
d = runs.request_run(db, "update", "manual", requested_by="uji-3", target_id=123456789, run_ml_predict=True)
check("target_id dan run_ml_predict tersimpan", d.target_id == 123456789 and d.run_ml_predict is True)
check("run_ml_predict bawaan False", a.run_ml_predict is False)

# 5. run macet dipulihkan
runs.claim_next(db)
from datetime import timedelta
d.heartbeat_at = d.heartbeat_at - timedelta(minutes=30)
db.commit()
check("run macet ditandai failed", runs.recover_stale(db) == 1)
check("run macet punya durasi", db.get(SyncRun, d.id).duration_seconds is not None)

# 6. pemantau CPU dan RAM
m = runs.ResourceMonitor(interval=0.2).start()
t = time.time()
while time.time() - t < 0.7:
    sum(i * i for i in range(10000))
res = m.stop()
try:
    import psutil  # noqa
    check("ResourceMonitor mengembalikan CPU dan RAM", set(res) == {"cpu_avg_percent", "cpu_peak_percent", "ram_peak_mb"}
          and res["ram_peak_mb"] > 0)
    check("stop kedua mengembalikan hasil yang sama", m.stop() == res)
except ImportError:
    check("tanpa psutil: kamus kosong", res == {})
check("host_info berisi JSON", runs.host_info().startswith("{"))

db.query(SyncRun).filter(SyncRun.requested_by.like("uji-%")).delete(synchronize_session=False)
db.commit()
db.close()
print("\nSEMUA LULUS" if ok else "\nADA YANG GAGAL")
sys.exit(0 if ok else 1)
