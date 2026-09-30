````markdown
# S-CLIPS — Data Mining Module

Modul scraping, cleansing, dan penyimpanan data jurnal SINTA untuk sistem S-CLIPS (SINTA Classification & Information Platform System). Modul ini bertanggung jawab mengakuisisi data jurnal Indonesia dari basis data SINTA, membersihkannya, dan menyimpannya ke PostgreSQL sebagai sumber data bagi modul Machine Learning (klasifikasi) dan Full Stack (dashboard).

## Struktur Project

```text
sclips-datamining/

├── scraper/          # Scraping SINTA (BeautifulSoup) + text cleansing
│   ├── sinta_scraper.py
│   ├── cleaner.py
│   └── scheduler.py
│
├── db/               # SQLAlchemy models, koneksi, upsert logic
│   ├── models.py
│   ├── session.py
│   └── upsert.py
│
├── migrations/       # Alembic migrations
│
├── utils/            # Logger, export CSV
│   ├── logger.py
│   └── export.py
│
├── scripts/           # Maintenance tools (backfill, fix data)
│   ├── backfill_subject.py
│   └── fix_publisher_names.py
│
├── config.py
├── main.py            # Entry point utama: scrape + simpan ke DB
├── requirements.txt
└── .env.example
````

## Setup

1. Clone repo dan masuk ke folder ini.

2. Buat virtual environment:

```bash
python -m venv venv
```

3. Aktifkan virtual environment (Windows):

```powershell
venv\Scripts\activate
```

4. Install dependencies:

```bash
pip install -r requirements.txt
```

5. Copy `.env.example` menjadi `.env`, lalu isi dengan kredensial database kamu sendiri:

```env
DATABASE_URL=postgresql://postgres:password_kamu@localhost:5432/sclips_db
SINTA_BASE_URL=https://sinta.kemdiktisaintek.go.id
SCRAPE_DELAY_SECONDS=2
LOG_LEVEL=INFO
```

6. Buat database PostgreSQL kosong dengan nama sesuai `.env` (misalnya `sclips_db`).

7. Jalankan migration untuk membuat tabel:

```bash
alembic upgrade head
```

## Cara Menjalankan

**Full scraping (proses utama — scrape semua jurnal SINTA dan simpan ke database):**

```bash
python main.py
```

Proses ini berjalan lama (~10–11 jam untuk seluruh data SINTA) karena menerapkan delay antar-request untuk menghormati server SINTA (politeness policy). Progress disimpan per jurnal, sehingga data yang sudah berhasil diproses tetap tersimpan jika proses dihentikan dengan `Ctrl+C`.

**Maintenance scripts (dijalankan sesuai kebutuhan):**

```bash
python scripts/backfill_subject.py       # Isi ulang kolom subject yang kosong tanpa full re-scrape
python scripts/fix_publisher_names.py    # Perbaiki normalisasi nama publisher pada data yang sudah ada
```

## Skema Database

| Tabel                    | Isi                                                                  | Diisi oleh                                                                                                                        |
| ------------------------ | -------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `publishers`             | Penerbit/institusi jurnal (nama asli & hasil normalisasi)            | Data Mining; kolom `type` (HEI/GOV/SOC/COM) diisi ML Engineer                                                                     |
| `journals`               | Metadata jurnal: nama, ISSN, current_rank, subject, status aktif     | Data Mining; subject dari SINTA dapat digunakan sebagai data awal/ground truth dan hasil klasifikasi ML dapat diperbarui kemudian |
| `journal_rank_histories` | Riwayat peringkat SINTA (S1–S6) per tahun, per jurnal                | Data Mining                                                                                                                       |
| `scraping_logs`          | Log tiap run scraping: jumlah insert/update/skip/flag, status, error | Data Mining                                                                                                                       |

Kolom `is_active` dan `status` (`active`/`inactive`/`unverified`) menandai jurnal yang sudah tidak ditemukan lagi di SINTA — data tidak dihapus, hanya ditandai (flagging), sesuai desain sistem.

## Untuk Full Stack Developer

Koneksi ke database dilakukan langsung (read-only), bukan lewat file export. Hubungi Data Mining Engineer untuk kredensial akses read-only ke database `sclips_db`. Gunakan filter:

```sql
is_active = true AND status = 'active'
```

untuk menampilkan hanya jurnal yang masih valid.

## Untuk ML Engineer

Data untuk training tersedia lewat export CSV (`utils/export.py`), berisi jurnal aktif beserta metadata penerbitnya. Subject yang diperoleh dari SINTA dapat digunakan sebagai data awal/label untuk proses klasifikasi. Hasil klasifikasi (`journals.subject` dan `publishers.type`) dapat di-update kembali ke database yang sama agar otomatis tersinkron dengan dashboard Full Stack.

## Known Limitations

* Normalisasi nama publisher menggunakan heuristik berbasis panjang kata untuk mendeteksi akronim (≤5 huruf dianggap akronim, dipertahankan uppercase). Pendekatan ini tidak sempurna 100% untuk seluruh variasi nama institusi di Indonesia, namun `raw_name` (nama asli sebelum normalisasi) tetap disimpan sebagai cadangan.
* `current_rank` diasumsikan dari kolom tahun terakhir pada tabel riwayat akreditasi SINTA. Sudah divalidasi untuk kasus jurnal yang berpindah tier (contoh: S4→S3), namun belum diuji untuk seluruh variasi format tabel yang mungkin ada.
* Scope data mencakup jurnal dan penerbit (affiliation) sesuai spesifikasi awal. Data departemen, penulis (author), dan Scopus quartile belum termasuk dalam scope saat ini.

```
```
