import json
import os
import platform
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError

from db.models import SyncRun

STALE_AFTER = timedelta(minutes=10)
SCOPES = ("update", "full")
COUNTERS = {"total_processed", "total_inserted", "total_updated", "total_skipped",
            "total_flagged", "pages_failed", "sinta_total", "db_total_before"}
# pengukuran untuk pengujian: durasi, jaringan, CPU, RAM, ukuran database, spesifikasi mesin
MEASURES = {"http_requests", "bytes_downloaded", "cpu_avg_percent", "cpu_peak_percent",
            "ram_peak_mb", "db_size_mb", "host_info"}


def _now():
    return datetime.now(timezone.utc)


def request_run(db, scope, trigger, source=None, requested_by=None, target_id=None,
                run_ml_predict=False):
    """Buat permintaan run. Return None kalau sudah ada run aktif (queued/running).

    scope      : 'update' atau 'full'
    target_id  : ID satu jurnal; hanya boleh untuk cakupan 'update'
    run_ml_predict : True bila prediksi ML dijalankan setelah run sukses
    """
    if scope not in SCOPES:
        raise ValueError(f"cakupan tidak valid: {scope} (pilihan: {', '.join(SCOPES)})")
    if target_id is not None and scope != "update":
        raise ValueError("target_id (satu jurnal) hanya untuk cakupan 'update'")
    run = SyncRun(scope=scope, trigger=trigger, source=source, requested_by=requested_by,
                  target_id=target_id, run_ml_predict=bool(run_ml_predict), status="queued")
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


def heartbeat(db, run_id, **values):
    """Perbarui detak, angka progres, dan pengukuran."""
    run = db.get(SyncRun, run_id)
    run.heartbeat_at = _now()
    for k, v in values.items():
        if k in COUNTERS or k in MEASURES:
            setattr(run, k, v)
    db.commit()


def finish(db, run_id, status, error=None):
    """Tutup run dengan status success, failed, atau paused. Lama proses dihitung otomatis."""
    if status not in ("success", "failed", "paused"):
        raise ValueError(f"status tidak valid: {status}")
    run = db.get(SyncRun, run_id)
    run.status = status
    run.finished_at = _now()
    if run.started_at is not None:
        run.duration_seconds = round((run.finished_at - run.started_at).total_seconds(), 1)
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
        if run.started_at is not None:
            run.duration_seconds = round((run.finished_at - run.started_at).total_seconds(), 1)
        run.error_message = "Proses berhenti (detak tidak diperbarui)"
    db.commit()
    return len(stale)


# ---------- pengukuran sumber daya ----------

def host_info():
    """Spesifikasi mesin sebagai teks JSON: sistem operasi, Python, inti CPU, total RAM."""
    info = {"os": platform.platform(), "python": platform.python_version(),
            "cpu_logical": os.cpu_count()}
    try:
        import psutil
        info["cpu_physical"] = psutil.cpu_count(logical=False)
        info["ram_total_gb"] = round(psutil.virtual_memory().total / 1024 ** 3, 1)
    except ImportError:
        pass
    return json.dumps(info, ensure_ascii=False)


class ResourceMonitor:
    """Catat CPU dan RAM proses ini selama run berlangsung (pustaka psutil).

    CPU dinyatakan dalam persen satu inti (nilai di atas 100 berarti lebih dari satu inti).
    Tanpa psutil, stop() mengembalikan kamus kosong dan run tetap berjalan.
    """

    def __init__(self, interval=2.0):
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self._cpu = []
        self._ram_peak = 0
        self._result = None
        try:
            import psutil
            self._proc = psutil.Process()
        except ImportError:
            self._proc = None

    def start(self):
        if self._proc is None:
            return self
        self._proc.cpu_percent(None)          # putaran pertama hanya menyiapkan pembanding
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        while not self._stop.wait(self.interval):
            self._cpu.append(self._proc.cpu_percent(None))
            self._ram_peak = max(self._ram_peak, self._proc.memory_info().rss)

    def stop(self):
        if self._proc is None:
            return {}
        if self._result is None:
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=5)
            self._ram_peak = max(self._ram_peak, self._proc.memory_info().rss)
            if not self._cpu:                  # run lebih singkat dari satu selang pengambilan
                self._cpu.append(self._proc.cpu_percent(None))
            self._result = {
                "cpu_avg_percent": round(sum(self._cpu) / len(self._cpu), 1),
                "cpu_peak_percent": round(max(self._cpu), 1),
                "ram_peak_mb": round(self._ram_peak / 1024 ** 2, 1),
            }
        return dict(self._result)
