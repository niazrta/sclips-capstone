"""Uji klien ML dengan layanan palsu: python tests/test_ml.py (gunakan database uji)."""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.append(os.getcwd())

from db.models import Journal, Publisher, SyncRun
from db.session import SessionLocal
from sync import ml, runs

MODE = {"post": "ok"}
SENT = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        b = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._send(200, {"status": "ok", "model_version": "v-uji", "model_sha256": "abc123"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SENT.append(body)
        if MODE["post"] == "422":
            return self._send(422, {"detail": "uji"})
        out = []
        for it in body["journals"]:
            out.append({"journal_id": it["journal_id"], "predicted_subject_sinta": "Teknik",
                        "predicted_subject_sinta_multilabel": None,
                        "predicted_subject_scopus": "Engineering", "predicted_subject_scopus_27": float("nan"),
                        "scopus_confidence_score": 91.2345, "processing_status": "Needs Review",
                        "review_reasons": ["confidence_subjek_rendah", "tanpa_nama_penerbit"],
                        "model_version": "v-uji", "predicted_publisher_type": "HEI",
                        "publisher_classification_confidence": 88.0, "publisher_size": "Large"})
        self._send(200, {"status": "success", "results": out})


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_port}"

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


J1, J2, J3 = 900000001, 900000002, 900000003
for j in (J1, J2, J3):
    db.query(Journal).filter(Journal.id == j).delete()
p = Publisher(name="Universitas Uji", sinta_publisher_id=555)
db.add(p)
db.flush()
db.add_all([Journal(id=J1, name="Jurnal Uji Satu", subject="Subjek Asli", publisher_id=p.id, is_active=True),
            Journal(id=J2, name="Jurnal Uji Dua", subject=None, publisher_id=None, is_active=True),
            Journal(id=J3, name="X", subject="Z", is_active=True)])
db.commit()
only = {J1, J2, J3}

os.environ.pop("ML_SERVICE_URL", None)
check("tanpa ML_SERVICE_URL: MLNotConfigured",
      raises(lambda: ml.predict_pending(db, only_ids=only), ml.MLNotConfigured))

os.environ["ML_SERVICE_URL"] = URL
r = ml.predict_pending(db, only_ids=only, apply=False)
check("simulasi menghitung tanpa mengirim", r["pending"] == 3 and r["predicted"] == 0 and not SENT)

os.environ["ML_MODEL_SHA256"] = "salah"
check("hash model berbeda: ditolak", raises(lambda: ml.predict_pending(db, only_ids=only), ml.MLError) and not SENT)
os.environ["ML_MODEL_SHA256"] = "abc123"

r = ml.predict_pending(db, only_ids=only)
check("2 jurnal terkirim, judul 1 karakter dilewati", r["predicted"] == 2 and r["skipped"] == [J3])
check("payload memuat nama penerbit dan jumlah", SENT[-1]["journals"][0]["publisher_name_raw"] == "Universitas Uji"
      and SENT[-1]["journals"][0]["sinta_publisher_id"] == "555" and "publisher_counts" in SENT[-1])
db.expire_all()
j1, j2, j3 = (db.get(Journal, i) for i in (J1, J2, J3))
check("subject asli tidak berubah", j1.subject == "Subjek Asli" and j2.subject is None and j3.subject == "Z")
check("NaN menjadi NULL", j1.predicted_subject_scopus_27 is None)
check("status, alasan, versi tersimpan", j1.predicted_status == "Needs Review"
      and j1.predicted_review_reasons == "confidence_subjek_rendah; tanpa_nama_penerbit"
      and j1.predicted_model_version == "v-uji")
check("tipe penerbit tersimpan", db.get(Publisher, p.id).type == "HEI" and db.get(Publisher, p.id).publisher_size == "Large")
check("jurnal tanpa penerbit tetap diprediksi", j2.predicted_status == "Needs Review" and j3.predicted_status is None)

r = ml.predict_pending(db, only_ids=None, run_id=None)
check("pending tidak lagi memuat jurnal yang sudah diprediksi", J1 not in [j.id for j in ml.pending_journals(db)])

MODE["post"] = "422"
check("422 memunculkan MLError tanpa pengulangan", raises(lambda: ml.predict_pending(db, only_ids={J1}), ml.MLError))

# jalur worker: kegagalan ML tidak mengubah status run
from sync import worker
MODE["post"] = "ok"
db.query(SyncRun).delete()
db.commit()
run = runs.request_run(db, "update", "manual", requested_by="uji-ml", run_ml_predict=True)
runs.claim_next(db)
runs.finish(db, run.id, "success")
os.environ["ML_SERVICE_URL"] = "http://127.0.0.1:1"      # tidak terjangkau
ml.RETRIES = 1
worker._predict_after(run.id)
db.expire_all()
rr = db.get(SyncRun, run.id)
check("ML gagal: status run tetap success, catatan terisi", rr.status == "success" and "prediksi ML gagal" in rr.error_message)

for j in (J1, J2, J3):
    db.query(Journal).filter(Journal.id == j).delete()
db.query(Publisher).filter(Publisher.id == p.id).delete()
db.query(SyncRun).delete()
db.commit()
db.close()
print("\nSEMUA LULUS" if ok else "\nADA YANG GAGAL")
sys.exit(0 if ok else 1)
