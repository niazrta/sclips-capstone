# S-CLIPS Data Mining

Modul pengambilan dan sinkronisasi data jurnal SINTA ke PostgreSQL.

## Persiapan
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # isi DATABASE_URL dan SINTA_BASE_URL
alembic upgrade head
```

## Sinkronisasi
```
python -m sync --scope update                    # simulasi; tambah --apply untuk menulis
python -m sync --scope full
python -m sync --scope update --ids 3856 --profile    # satu jurnal lewat profil (cepat)
python -m sync.worker                            # penjadwal dan pengambil antrean
```
Dua cakupan: `update` (perbarui jurnal yang ada) dan `full` (update, jurnal baru, jurnal hilang; lebih jarang dijalankan). Tanpa `--apply`, tidak ada yang ditulis. Opsi uji: `--from-dir` (baca salinan listing), `--offline`, `--ids`, `--limit`. Setiap run mencatat durasi, CPU, RAM, ukuran database, dan spesifikasi mesin di `sync_runs`. Definisi lengkap: `docs/SINKRONISASI.md`.

## Prediksi ML
Dijalankan worker setelah run sukses bila `run_ml_predict` aktif. Pengaturan lewat variabel lingkungan `ML_SERVICE_URL` dan `ML_MODEL_SHA256`.
```
python -m sync.ml                  # simulasi: jumlah jurnal yang menunggu
python -m sync.ml --apply          # kirim ke layanan ML dan simpan
python -m sync.ml --all --apply    # semua jurnal aktif
```

## Pertukaran dengan ML (berkas)
```
python utils\export.py
python scripts\import_ml_predictions.py <csv atau xlsx>          # simulasi
python scripts\import_ml_predictions.py <csv atau xlsx> --apply
```

## Tes
Gunakan database uji (bukan database utama): tes menulis dan menghapus baris.
```
python tests\test_parser.py [folder_listing]
python tests\test_runs.py
python tests\test_ml.py
python tests\test_profile.py
```

## Struktur
Lihat `docs/FILE_MAP.md`.
