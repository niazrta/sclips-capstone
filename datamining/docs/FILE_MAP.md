# Peta File Modul Data Mining (S-CLIPS)

## Urutan kerja (kronologis)

| Fase | Yang dikerjakan | File |
| --- | --- | --- |
| 1. Scraping awal | Ambil semua jurnal SINTA, simpan ke PostgreSQL (15.146 jurnal) | `scripts/archive/01_initial_scrape/` (`main_initial_scrape.py`, `upsert_OLD_DO_NOT_USE.py`) |
| 2. Audit | Bandingkan dengan listing SINTA (16.768). Selisih 1.624 jurnal | `scripts/archive/02_audit_and_validation/` |
| 3. Pemulihan | Masukkan jurnal hilang, kunci = ID SINTA | `scripts/archive/03_recovery/` |
| 4. Perbaikan data | ISSN, subject, nama penerbit, encoding | `scripts/archive/04_data_fixes/` |
| 5. Field listing dan ML | 13 kolom listing, impor prediksi ML | `scripts/archive/05_listing_fields_and_ml/`, `scripts/import_ml_predictions.py` |
| 6. Parser baru | ID lewat regex, ISSN apa adanya dengan status | `scraper/sinta_scraper.py`, `scraper/cleaner.py`, `tests/test_parser.py` |
| 7. Sinkronisasi | Dua cakupan (`update`, `full`), update per jurnal, worker, jadwal | `sync/engine.py`, `sync/runs.py`, `sync/worker.py`, `sync/__main__.py` |
| 8. Pengukuran dan prediksi ML | Durasi, CPU, RAM per run; pemanggilan layanan ML setelah sinkronisasi | `sync/runs.py` (`ResourceMonitor`), `sync/ml.py` |

## Kode operasional

| Lokasi | Peran |
| --- | --- |
| `scraper/sinta_scraper.py` | Mengambil dan membaca halaman SINTA (listing, profil) |
| `scraper/cleaner.py` | Aturan teks: rapikan spasi, status ISSN |
| `sync/engine.py` | Satu program sinkronisasi (`update`, `full`; update per jurnal lewat profil) |
| `sync/runs.py` | Pencatatan run, detak, pemulihan run macet, pengukuran CPU dan RAM |
| `sync/worker.py` | Penjadwal, pengambil antrean, pemicu prediksi ML setelah run sukses |
| `sync/ml.py` | Klien layanan ML: kirim jurnal, simpan hasil ke `journals` dan `publishers` |
| `db/`, `migrations/` | Skema dan riwayat perubahannya |
| `utils/export.py` | Ekspor CSV untuk ML |
| `scripts/import_ml_predictions.py` | Impor prediksi ML dari CSV atau xlsx (simulasi default) |
| `tests/` | Tes parser, pencatatan run, klien ML, dan update per jurnal |
| `docs/` | `SINKRONISASI.md`, `FILE_MAP.md` |

## Arsip
`scripts/archive/` memuat alat sekali pakai (audit, pemulihan, perbaikan data). Bukti proses validasi, tidak dijalankan lagi. File bernama `_OLD_DO_NOT_*` sengaja ditandai.

## Temuan utama
- e-ISSN tidak unik di SINTA (35 dipakai lebih dari satu jurnal), sehingga kunci jurnal adalah ID SINTA.
- Kode lama menambah `X` pada 26 ISSN; dikembalikan sesuai SINTA.
- Penerbit: 69 nama punya tautan ke lebih dari satu afiliasi; keduanya disimpan apa adanya.
- Penanda kosong SINTA (`#!`, `-`) pada 2.837 Google Scholar dan 2.766 cover dibaca sebagai NULL.
- Pengelompokan ML adalah turunan subject SINTA; tipe penerbit berbasis aturan kata kunci, bukan label manusia.
