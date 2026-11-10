"""Uji update per jurnal lewat profil (jaringan ditiru): python tests/test_profile.py (database uji)."""
import os
import sys

sys.path.append(os.getcwd())

from db.models import Journal, JournalRankHistory, SyncChange, SyncRun
from db.session import SessionLocal
from sync import engine, runs, worker

J = 900000011
HIST = {"accreditation_history": [{"year": 2023, "rank": "S4"}, {"year": 2024, "rank": "S3"}]}
engine.fetch_profile = lambda jid: ("<html/>", "ok")
engine.parse_detail_page = lambda html: HIST
engine.time.sleep = lambda s: None

db = SessionLocal()
ok = True


def check(name, cond):
    global ok
    ok = ok and bool(cond)
    print(("OK    " if cond else "GAGAL ") + name)


for t in (SyncChange, JournalRankHistory):
    db.query(t).filter((t.journal_id == J)).delete()
db.query(SyncRun).delete()
db.query(Journal).filter(Journal.id == J).delete()
db.add(Journal(id=J, name="Jurnal Profil Uji", subject="Asli", is_active=True))
db.add(JournalRankHistory(journal_id=J, sinta_rank="S5", accreditation_year=2023))
db.commit()

engine.run("update", apply=False, ids={J}, source="profile")
check("simulasi tidak mengubah riwayat", db.query(JournalRankHistory).filter_by(journal_id=J).count() == 1)
check("simulasi tidak membuat run", db.query(SyncRun).count() == 0)

run = runs.request_run(db, "update", "manual", source="profile", requested_by="uji-p", target_id=J)
check("tick menjalankan run manual per jurnal", worker.tick() is True)
db.expire_all()
rr = db.get(SyncRun, run.id)
rows = {h.accreditation_year: h.sinta_rank for h in db.query(JournalRankHistory).filter_by(journal_id=J)}
check("run success dengan 1 jurnal diperbarui", rr.status == "success" and rr.total_updated == 1 and rr.http_requests is not None)
check("tahun 2023 diperbarui, 2024 ditambah", rows == {2023: "S4", 2024: "S3"})
check("perubahan tercatat di sync_changes", db.query(SyncChange).filter_by(run_id=run.id, journal_id=J).count() == 2)
check("subject asli tidak berubah", db.get(Journal, J).subject == "Asli")
check("cakupan full + profile ditolak", (lambda: (engine.run("full", ids={J}, source="profile"), False)[1])
      if False else True)
try:
    engine.run("full", ids={J}, source="profile")
    check("cakupan full + profile ditolak", False)
except ValueError:
    check("cakupan full + profile ditolak", True)

db.query(SyncChange).filter_by(journal_id=J).delete()
db.query(JournalRankHistory).filter_by(journal_id=J).delete()
db.query(SyncRun).delete()
db.query(Journal).filter(Journal.id == J).delete()
db.commit()
db.close()
print("\nSEMUA LULUS" if ok else "\nADA YANG GAGAL")
sys.exit(0 if ok else 1)
