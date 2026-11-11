"""Klien layanan ML: kirim jurnal ke /classify/predict, simpan hasilnya ke database.

Pengaturan lewat variabel lingkungan:
  ML_SERVICE_URL   alamat dasar layanan, mis. http://localhost:8000 (endpoint /classify/... ditambahkan di sini)
  ML_MODEL_SHA256  opsional; bila diisi, prediksi ditolak jika /classify/health melaporkan hash lain

Kolom `journals.subject` (subjek asli SINTA) tidak pernah diubah oleh modul ini.

Pemakaian:
  python -m sync.ml                 simulasi: hitung jurnal yang menunggu prediksi
  python -m sync.ml --apply         kirim ke layanan ML lalu simpan
  python -m sync.ml --all --apply   prediksi ulang semua jurnal aktif
  python -m sync.ml --ids 1,2 --apply
"""
import argparse
import math
import os
import time
from datetime import datetime, timezone

import requests
from sqlalchemy import func

from db.models import Journal, Publisher, SyncChange

UNKNOWN_PUBLISHER = 73          # penerbit palsu "Unknown", tidak diberi tipe
BATCH = 1000                    # batas permintaan sinkron layanan ML (sync_batch_limit)
TIMEOUT = 30                    # detik; batas layanan ML adalah 30 detik per permintaan
RETRIES = 3
CHANGE_FIELDS = {"name", "publisher", "journal_baru"}   # perubahan yang memengaruhi hasil klasifikasi


class MLNotConfigured(RuntimeError):
    """ML_SERVICE_URL belum diatur."""


class MLError(RuntimeError):
    """Layanan ML menolak atau gagal merespons."""


def _base_url():
    url = os.getenv("ML_SERVICE_URL", "").strip().rstrip("/")
    if not url:
        raise MLNotConfigured("ML_SERVICE_URL belum diatur")
    return url


def check_health(base=None):
    """Panggil /classify/health; bandingkan hash model bila ML_MODEL_SHA256 diisi."""
    base = base or _base_url()
    try:
        r = requests.get(f"{base}/classify/health", timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        raise MLError(f"layanan ML tidak terjangkau: {e}")
    if r.status_code != 200:
        raise MLError(f"/classify/health mengembalikan {r.status_code}")
    info = r.json()
    expected = os.getenv("ML_MODEL_SHA256", "").strip().lower()
    if expected and info.get("model_sha256", "").lower() != expected:
        raise MLError("hash model tidak cocok dengan ML_MODEL_SHA256, prediksi ditolak")
    return info


def _post(base, payload):
    """Kirim satu batch. Ulangi untuk 5xx dan waktu habis; 422 langsung gagal."""
    last = None
    for n in range(RETRIES):
        try:
            r = requests.post(f"{base}/classify/predict", json=payload, timeout=TIMEOUT)
        except requests.exceptions.RequestException as e:
            last = e
            time.sleep(2 * (n + 1))
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code == 422:
            raise MLError(f"payload ditolak (422): {r.text[:300]}")
        last = f"status {r.status_code}"
        time.sleep(2 * (n + 1))
    raise MLError(f"permintaan ke layanan ML gagal setelah {RETRIES} percobaan: {last}")


def build_payload(db, journals):
    """Susun isi permintaan; jurnal berjudul kurang dari 2 karakter dilewati."""
    counts = dict(db.query(Journal.publisher_id, func.count(Journal.id))
                  .filter(Journal.is_active.is_(True), Journal.publisher_id.isnot(None))
                  .group_by(Journal.publisher_id).all())
    pubs = {p.id: p for p in db.query(Publisher).filter(
        Publisher.id.in_({j.publisher_id for j in journals if j.publisher_id})).all()}
    items, skipped = [], []
    for j in journals:
        title = (j.name or "").strip()
        if len(title) < 2:
            skipped.append(j.id)
            continue
        p = pubs.get(j.publisher_id)
        pname = p.name if p else ""
        items.append({"journal_id": j.id, "publisher_id": j.publisher_id, "journal_title": title,
                      "publisher_name_raw": pname, "publisher_name_clean": pname,
                      "sinta_publisher_id": str(p.sinta_publisher_id) if p and p.sinta_publisher_id else "",
                      "website_url": j.website or ""})
    return {"journals": items,
            "publisher_counts": {str(k): v for k, v in counts.items()}}, skipped


def _clean(v):
    """NaN dan string kosong menjadi NULL."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, str) and not v.strip():
        return None
    return v


def save_predictions(db, results, now=None):
    """Simpan hasil ke journals dan publishers. Tidak commit. Return (jurnal, penerbit) yang diperbarui."""
    now = now or datetime.now(timezone.utc)
    nj, ptype = 0, {}
    for r in results:
        j = db.get(Journal, int(r["journal_id"]))
        if j is None:
            continue
        j.predicted_subject_sinta = _clean(r.get("predicted_subject_sinta"))
        j.predicted_subject_sinta_multilabel = _clean(r.get("predicted_subject_sinta_multilabel"))
        j.predicted_subject_scopus = _clean(r.get("predicted_subject_scopus"))
        j.predicted_subject_scopus_27 = _clean(r.get("predicted_subject_scopus_27"))
        c = _clean(r.get("scopus_confidence_score"))
        j.scopus_confidence = None if c is None else round(float(c), 3)
        j.predicted_status = _clean(r.get("processing_status"))
        reasons = r.get("review_reasons")
        if isinstance(reasons, (list, tuple)):
            reasons = "; ".join(str(x) for x in reasons)
        j.predicted_review_reasons = _clean(reasons)
        j.predicted_model_version = _clean(r.get("model_version"))
        j.predictions_updated_at = now
        nj += 1
        pid, t = j.publisher_id, _clean(r.get("predicted_publisher_type"))
        if pid and pid != UNKNOWN_PUBLISHER and t is not None:
            pc = _clean(r.get("publisher_classification_confidence"))
            ptype[pid] = (t, _clean(r.get("publisher_size")), None if pc is None else round(float(pc), 3))
    for pid, (t, sz, pc) in ptype.items():
        p = db.get(Publisher, pid)
        if p is not None:
            p.type, p.publisher_size, p.type_confidence = t, sz, pc
    return nj, len(ptype)


def pending_journals(db, run_id=None, all_active=False, only_ids=None):
    """Jurnal aktif yang perlu diprediksi: belum pernah, atau berubah (nama/penerbit/baru) pada run ini."""
    q = db.query(Journal).filter(Journal.is_active.is_(True))
    if only_ids:
        return q.filter(Journal.id.in_(only_ids)).order_by(Journal.id).all()
    if all_active:
        return q.order_by(Journal.id).all()
    cond = (Journal.predictions_updated_at.is_(None)) | (Journal.predicted_status.is_(None))
    if run_id is not None:
        changed = (db.query(SyncChange.journal_id)
                   .filter(SyncChange.run_id == run_id, SyncChange.field.in_(CHANGE_FIELDS)))
        cond = cond | Journal.id.in_(changed)
    return q.filter(cond).order_by(Journal.id).all()


def predict_pending(db, run_id=None, all_active=False, only_ids=None, apply=True):
    """Kirim jurnal yang menunggu ke layanan ML dan simpan hasilnya (commit per batch)."""
    base = _base_url()
    todo = pending_journals(db, run_id, all_active, only_ids)
    res = {"pending": len(todo), "predicted": 0, "publishers_typed": 0, "skipped": [], "model_version": None}
    if not apply or not todo:
        return res
    info = check_health(base)
    res["model_version"] = info.get("model_version")
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        payload, skipped = build_payload(db, chunk)
        res["skipped"] += skipped
        if not payload["journals"]:
            continue
        out = _post(base, payload)
        results = out.get("results", [])
        if len(results) != len(payload["journals"]):
            raise MLError(f"jumlah hasil ({len(results)}) berbeda dari yang dikirim ({len(payload['journals'])})")
        nj, npub = save_predictions(db, results)
        db.commit()
        res["predicted"] += nj
        res["publishers_typed"] += npub
    return res


if __name__ == "__main__":
    from db.session import SessionLocal

    ap = argparse.ArgumentParser(prog="python -m sync.ml")
    ap.add_argument("--apply", action="store_true", help="kirim ke layanan ML dan simpan (tanpa ini: simulasi)")
    ap.add_argument("--all", action="store_true", help="semua jurnal aktif, bukan hanya yang menunggu")
    ap.add_argument("--ids", default=None, help="ID jurnal, pisah koma")
    ap.add_argument("--run-id", type=int, default=None, help="sertakan jurnal yang berubah pada run ini")
    a = ap.parse_args()
    ids = {int(x) for x in a.ids.split(",")} if a.ids else None
    s = SessionLocal()
    try:
        r = predict_pending(s, run_id=a.run_id, all_active=a.all, only_ids=ids, apply=a.apply)
        print(r)
        if not a.apply:
            print("SIMULASI: tidak ada yang dikirim. Tambahkan --apply.")
    finally:
        s.close()
