# Peta File Modul Data Mining (S-CLIPS)

## Alur kerja (urutan kronologis)

| Fase | Yang dikerjakan | File |
| --- | --- | --- |
| 1. Scraping awal | Ambil semua jurnal dari SINTA, bersihkan, simpan ke PostgreSQL. Hasil: 15.146 jurnal | `scraper/sinta_scraper.py`, `scraper/cleaner.py`, `db/upsert.py`, `scripts/archive/01_initial_scrape/main_initial_scrape.py` |
| 2. Audit | Bandingkan dengan listing SINTA (16.768 jurnal). Selisih 1.624 jurnal | `scripts/archive/02_audit_and_validation/` |
| 3. Pemulihan | Masukkan jurnal yang hilang memakai ID SINTA sebagai kunci | `scripts/archive/03_recovery/recover_missing.py` |
| 4. Perbaikan data | ISSN berakhiran X, subject, nama penerbit, encoding | `scripts/archive/04_data_fixes/` |
| 5. Field tambahan | 13 kolom dari listing (tautan, indeksasi, metrik) | `scripts/sync_listing_fields.py`, `scripts/archive/05_listing_fields_and_ml/` |
| 6. Integrasi ML | Export CSV untuk ML, impor hasil prediksi | `utils/export.py`, `scripts/import_ml_predictions.py`, `scripts/check_ml_prediction2.py` |
| 7. Sinkronisasi berkala | Sync listing, refresh detail, jadwal (dikerjakan) | belum ditulis |

## Status file

| Kategori | Arti | Contoh |
| --- | --- | --- |
| Operasional | Dipakai sistem | `db/models.py`, `db/session.py`, `config.py`, `migrations/`, parser di `scraper/` |
| Perlu ditulis ulang | Logika lama, jangan dipakai sebagai acuan | `db/upsert.py` |
| Perawatan manual | Dijalankan saat perlu | `utils/export.py`, `scripts/import_ml_predictions.py` |
| Arsip | Alat validasi dan pemulihan sekali pakai, bukti metodologi, tidak dijalankan lagi | `scripts/archive/*` |

## Temuan utama yang tercatat
- e-ISSN tidak unik di SINTA (35 e-ISSN dipakai lebih dari satu jurnal), jadi kunci jurnal adalah ID SINTA.
- Sebagian ISSN berakhiran X terpotong oleh parser lama, sudah diperbaiki.
- 38 jurnal punya `current_rank` berbeda dari badge listing. `rank_badge` dipakai sebagai peringkat resmi.
- Sekitar 20 nama jurnal rusak di sumber SINTA, dipertahankan apa adanya.
- Hasil ML adalah pengelompokan turunan dari subject SINTA, bukan klasifikasi Scopus sungguhan.