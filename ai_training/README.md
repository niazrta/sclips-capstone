# S-CLIPS — Modul Machine Learning (v2.7)

Klasifikasi otomatis jurnal SINTA:

- **Subjek SINTA** (10 subjek): satu subjek, atau dua subjek bila satu subjek belum cukup yakin. Keyakinan label yang ditampilkan selalu ≥ 70%.
- **Rumpun Scopus-4** dan **bidang Scopus-27**.
- **Tipe penerbit** (HEI / GOV / SOC / COM) dan **ukuran penerbit** (Small / Medium / Large).

Model tidak perlu dilatih ulang ketika ada jurnal baru. Jurnal baru langsung diklasifikasikan oleh model yang sama.

| | |
|---|---|
| Versi model | `v2.7-LinearSVM-Calibrated-Lexicon-16768` |
| SHA-256 model | `5e9841f96ba473a6faefe1d7a2b853e6c3393b3ccc92960c2f1a23c79886fd37` |
| Library | scikit-learn 1.6.1, numpy 2.4.6, scipy 1.16.3 |
| Data latih | 16.768 jurnal aktif SINTA (14.983 bersubjek) |
| Hasil uji (20% data tidak ikut dilatih) | label benar 89,65% (judul baru), 89,47% (penerbit baru) |

## Struktur folder

```text
ai_training/
├── sclips_ml_service.py       # layanan FastAPI (APIRouter /classify) — dipakai backend
├── sclips_models_v2.7.pkl     # model final; HARUS berpasangan dengan service di atas
├── requirements.txt           # versi library yang dikunci
├── train_v27.py               # skrip pelatihan ulang (opsional)
├── data/
│   ├── journals_classified_v2.6.xlsx   # data latih (sheet 2_Full_16768_Jurnal, asal ekspor CSV SINTA)
│   └── sclips_models_v2.6.pkl          # model tipe penerbit & Scopus-27 dari v2.6 (dipakai ulang)
├── notebooks/
│   └── Pelatihan_SCLIPS_v2.7.ipynb     # proses pelatihan langkah demi langkah (sudah berisi output)
└── reports/
    ├── README_DEPLOY.txt               # panduan integrasi lengkap untuk Fullstack & Data Mining
    ├── evaluation_report_v2.7.json     # laporan evaluasi
    ├── journals_classified_v2.7.xlsx   # hasil klasifikasi 16.768 jurnal
    └── *.png                           # grafik keandalan keyakinan, v2.6 vs v2.7, confusion matrix
```

## Untuk backend (Fullstack)

```bash
pip install -r ai_training/requirements.txt
```

```python
# di aplikasi FastAPI backend
import sys; sys.path.append("ai_training")
from sclips_ml_service import router as ml_router
app.include_router(ml_router)          # GET /classify/health, POST /classify/predict, dst.
```

- Service mencari `sclips_models_v2.7.pkl` di folder yang sama dengan `sclips_ml_service.py`. Lokasi lain bisa diatur lewat env `SCLIPS_MODEL_PATH`.
- Service menolak berjalan bila SHA-256 file model tidak cocok, jadi `.py` dan `.pkl` selalu diganti berpasangan.
- Endpoint: `GET /classify/health`, `POST /classify/predict` (≤ 1.000 jurnal → 200; lebih → 202 + `task_id`), `POST /classify/predict-async`, `GET /classify/tasks/{task_id}`, `GET /classify/tasks`.

## Untuk Data Mining

Panggil `POST /classify/predict` di akhir sinkronisasi, batch ≤ 1.000 jurnal, dengan `publisher_counts`. Cek dulu `GET /classify/health` → `model_sha256` harus sama dengan SHA di atas.

Kunci output yang disimpan: `predicted_subject_sinta`, `predicted_subject_sinta_multilabel` (label subjek untuk tampilan), `predicted_subject_scopus`, `predicted_subject_scopus_27`, `scopus_confidence_score`, `processing_status`, `review_reasons`, `model_version`, `predicted_publisher_type`, `publisher_classification_confidence`, `publisher_size`.

Untuk jurnal tanpa nama penerbit (termasuk penerbit "Unknown", ID 73), `predicted_publisher_type`, `publisher_classification_confidence`, dan `publisher_size` bernilai null. Subjeknya tetap diprediksi.

Rincian lengkap ada di `reports/README_DEPLOY.txt`.

## Melatih ulang (opsional, tidak diperlukan untuk jurnal baru)

```bash
pip install -r ai_training/requirements.txt pandas openpyxl
cd ai_training
SCLIPS_TRAIN_XLSX=data/journals_classified_v2.6.xlsx SCLIPS_V26_PKL=data/sclips_models_v2.6.pkl \
  python train_v27.py eval-title       # evaluasi: uji per judul
SCLIPS_TRAIN_XLSX=data/journals_classified_v2.6.xlsx SCLIPS_V26_PKL=data/sclips_models_v2.6.pkl \
  python train_v27.py final            # melatih model final
```

> **Perhatian:** mode `final` menimpa `sclips_models_v2.7.pkl` di folder ini. File baru akan punya SHA-256 berbeda (waktu pelatihan ikut tersimpan) walaupun prediksinya identik, sehingga service akan menolaknya sampai SHA di `sclips_ml_service.py` dan di sisi Data Mining diperbarui. Jangan commit hasil pelatihan ulang kecuali memang merilis versi model baru.

Proses pelatihan juga bisa dilihat di `notebooks/Pelatihan_SCLIPS_v2.7.ipynb` (buka di Google Colab; semua output sudah tersimpan).
