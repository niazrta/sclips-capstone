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
python -m sync --scope new            # dry-run; tambah --apply untuk menulis
python -m sync --scope update
python -m sync --scope full
python -m sync.worker                 # penjadwal dan pengambil antrean
```
Tanpa `--apply`, tidak ada yang ditulis. Opsi uji: `--from-dir` (baca salinan listing), `--ids`, `--limit`. Definisi lengkap: `docs/SINKRONISASI.md`.

## Pertukaran dengan ML
```
python utils\export.py
python scripts\import_ml_predictions.py <csv>          # dry-run
python scripts\import_ml_predictions.py <csv> --apply
```

## Tes
```
python tests\test_parser.py [folder_listing]
python tests\test_runs.py
```

## Struktur
Lihat `docs/FILE_MAP.md`.