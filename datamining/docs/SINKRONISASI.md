# Sinkronisasi Data SINTA: Definisi dan Prosedur

Status: diimplementasikan. Diuji pada salinan database dan pada database utama (Nov 2026).

## 1. Tujuan
Basis data S-CLIPS harus akurat terhadap SINTA. Acuan kebenaran adalah situs SINTA. Sinkronisasi membandingkan data kita dengan SINTA, memperbaiki perbedaannya, dan mencatat setiap perubahan. Data disimpan apa adanya dari SINTA, termasuk kekurangannya, sebagai bukti kualitas metadata sumber.

## 2. Sumber data
Alamat dirakit dari `SINTA_BASE_URL`, tidak tertanam di kode.

| Sumber | Halaman | Waktu (terukur) | Isi |
| --- | --- | --- | --- |
| listing | daftar jurnal, 1.677 halaman | sekitar 65 menit | nama, ISSN, penerbit dan tautan afiliasi, subject, badge, tautan, indeksasi, metrik |
| profil | satu jurnal | sekitar 2 detik per jurnal | riwayat akreditasi per tahun (satu-satunya sumber) |

Jeda antar permintaan 2 detik. robots.txt SINTA tidak melarang akses (`Disallow` kosong, diperiksa 8 November 2026).

## 3. Dua cakupan
Satu program (`python -m sync --scope ...`), dipanggil dengan cakupan berbeda. Beda cakupan hanya pada apa yang boleh ditulis. `full` dijalankan lebih jarang daripada `update`.

| Cakupan | Dilakukan | Tidak dilakukan |
| --- | --- | --- |
| `update` | Bandingkan field jurnal yang sudah ada dengan listing, perbarui yang berbeda. Bila badge berubah, ambil profil untuk riwayat. | Tidak memasukkan jurnal baru, tidak menandai hilang. |
| `full` | `update`, ditambah jurnal baru (profil diambil) dan penanganan jurnal hilang, dari satu pembacaan listing. Jurnal `unverified` yang masih absen menjadi `inactive`. | Tidak menghapus apa pun. |

**Update per jurnal.** `python -m sync --scope update --ids <ID> --profile` hanya membuka profil jurnal itu (sekitar 2 detik) dan tidak membaca listing. Profil hanya memuat riwayat akreditasi, sehingga hanya itu yang diperbarui; kolom dari listing diperbarui oleh `update`. Tanpa `--profile`, `--ids` membatasi hasil `update` pada ID itu, tetapi listing tetap dibaca penuh.

**Cara menjalankan.** Tiga jalur masuk berakhir di fungsi yang sama (`engine.run`): jadwal (`sync_schedules`), permintaan manual (satu baris `sync_runs` berstatus `queued`, berisi cakupan, `target_id`, `source`, dan `run_ml_predict`), dan terminal.

Setiap run tercatat sebagai satu baris `sync_runs` dengan cakupannya.

## 4. Prosedur
1. Baca sumber. 2. Periksa kelengkapan: tidak ada halaman gagal, jumlah baris sama dengan Total Records, ID unik. Bila tidak lengkap, run `paused` dan tidak ada yang ditulis. 3. Bandingkan berdasarkan ID SINTA. 4. Tentukan tindakan sesuai cakupan. 5. Tulis, satu transaksi per jurnal, dan catat di `sync_changes`. 6. Tutup run dengan hasilnya.

## 5. Aturan perbedaan data
| Data | Aturan |
| --- | --- |
| Nama, subject, penerbit | Ikuti SINTA persis. Spasi ganda dirapikan jadi satu, huruf tidak diubah. Penerbit bernama `-` = tanpa penerbit. |
| ISSN | Disimpan apa adanya (awalan `P`/`E`, `x` kecil, kurang dari 8 karakter). Pemisah antar-kelompok menjadi `-`. Kolom status: `valid`, `short`, `invalid`, `none`. Tidak ada digit yang ditambah. |
| Tautan | Penanda kosong SINTA (`#!`, `-`, cover folder kosong) disimpan NULL. Spasi di tepi dibuang. |
| Badge | Disimpan apa adanya di `rank_badge`. NA = tidak terakreditasi. |
| Metrik | Ditimpa; `metrics_updated_at` diisi. |
| Riwayat akreditasi | Tahun baru ditambah, tahun berbeda diperbarui, tidak ada yang dihapus atau dibuat sendiri. |
| Kosong di SINTA | Dikosongkan dan dicatat. |
| Kolom prediksi ML, tipe dan ukuran penerbit | Tidak disentuh oleh proses sinkronisasi (`engine`). Hanya modul prediksi (`sync/ml.py`) yang menulisnya, dan kolom `subject` tidak pernah ditimpa. |
| Jurnal baru | Masuk `active`; penerbit baru dibuat tanpa tipe. |

## 6. Jurnal hilang
Berlaku pada cakupan `full`.
1. Hanya diproses bila listing lengkap.
2. Lebih dari 100 kandidat (aktif di database, absen di listing): run `paused`, tidak diperiksa.
3. Selain itu, sebuah jurnal kontrol dibuka dulu; bila tidak terbuka normal, tidak ada alihan yang dipercaya. Lalu profil tiap kandidat dibuka tanpa mengikuti alihan: dialihkan berarti terkonfirmasi, terbuka normal berarti tidak ditandai.
4. Terkonfirmasi 1 sampai 20: status `unverified` dan nonaktif. Lebih dari 20: tidak ada yang ditandai, run `paused`, daftar tercatat di `sync_changes` (`kandidat_hilang`).
5. `unverified` yang masih absen dan masih dialihkan menjadi `inactive`.
6. Jurnal `unverified` yang muncul lagi di listing diaktifkan kembali.

Batas 20 dan 100 adalah parameter, bukan klaim literatur: total SINTA hanya turun 4 jurnal dalam sebulan.

## 7. Pencatatan dan penjadwalan
- `sync_runs`: cakupan, pemicu (`scheduled`/`manual`), `target_id`, `source`, `run_ml_predict`, status, detak, hitungan, pesan.
- `sync_changes`: run, jurnal, field, nilai lama, nilai baru.
- `sync_schedules`: jadwal harian, mingguan, bulanan, atau tanggal tertentu, dengan zona waktu; kolom `after_ml_predict` menentukan apakah prediksi ML dijalankan setelah run. Dua jadwal awal (nonaktif): `update` harian 02:00 dan `full` Sabtu 02:00 WIB. Jam bisa diubah admin.
- Worker (`python -m sync.worker`) tiap 30 detik: memulihkan run macet (detak berhenti lebih dari 10 menit), membuat run dari jadwal jatuh tempo, mengambil run `queued` (tombol manual), lalu menjalankan prediksi ML bila diminta.
- Hanya satu run aktif sekaligus (indeks unik di database).
- Sepuluh halaman gagal beruntun menghentikan run.

## 8. Pengukuran per run
Setiap run mencatat di `sync_runs`: `duration_seconds`, `http_requests`, `bytes_downloaded` (perkiraan dari ukuran halaman), `cpu_avg_percent` dan `cpu_peak_percent` (persen satu inti, nilai di atas 100 berarti lebih dari satu inti), `ram_peak_mb`, `db_size_mb`, dan `host_info` (JSON: sistem operasi, versi Python, jumlah inti CPU, total RAM). CPU dan RAM diukur dengan pustaka `psutil` setiap 2 detik; tanpa `psutil`, run tetap berjalan tanpa nilai CPU dan RAM. Untuk run yang sangat singkat, nilai CPU kurang akurat.

## 9. Prediksi ML setelah sinkronisasi
Hanya berjalan setelah run berstatus `success` dan bila `run_ml_predict` aktif. Layanan ML dipanggil lewat HTTP (`POST /classify/predict`, batch 1.000, batas waktu 30 detik, ulang 3 kali untuk kesalahan server, tanpa ulang untuk 422).
- `update` dan `full`: semua jurnal aktif diklasifikasikan ulang, karena ukuran penerbit bergantung pada jumlah jurnal per penerbit.
- Update satu jurnal: hanya jurnal itu.
- Hash model diperiksa lewat `GET /classify/health` terhadap `ML_MODEL_SHA256`; bila berbeda, prediksi ditolak. Alamat layanan diatur di `ML_SERVICE_URL`; bila kosong, prediksi dilewati dan dicatat.
- Hasil disimpan di `journals.predicted_*` (termasuk `predicted_status`, `predicted_review_reasons`, `predicted_model_version`) dan tipe penerbit di `publishers`. Penerbit "Unknown" (id 73) dan jurnal tanpa penerbit tidak diberi tipe. Kolom `subject` (subjek asli SINTA) tidak pernah diubah.
- Kegagalan ML dicatat di `error_message` run dan tidak mengubah status sinkronisasi.

## 10. Yang teruji dan belum
Teruji: `update` dan `full` pada database utama (0 perubahan terhadap salinan listing terbaru), update per jurnal lewat profil (simulasi pada SINTA asli untuk jurnal 3856; penulisan diuji dengan jaringan tiruan), worker (antrean manual, jadwal harian), jadwal mingguan (perhitungan), pencatatan pengukuran, klien ML (dengan layanan tiruan). Logika jurnal baru, muncul lagi, dan hilang (termasuk 25 dan 120 kandidat dan listing bolong) diuji saat cakupannya masih bernama `new`; belum diulang setelah digabung ke `full`.
Belum teruji: klien ML terhadap layanan ML sungguhan, profil yang masih terbuka padahal tidak ada di listing, gagal unduh dari jaringan, respons 429 sungguhan, jadwal bulanan dan tanggal, worker berjalan berjam-jam, eskalasi lebih dari 20 jurnal.

## 11. Hal terbuka
- Update per jurnal hanya memperbarui riwayat akreditasi, karena profil tidak memuat kolom listing.
- Aksi admin untuk jurnal yang dicurigai hilang.
- Jadwal cron, hierarki fakultas ke universitas, ISSN yang kurang dari 8 karakter (diduga lengkap di Garuda).
- Ambang 20 dan 100, jam 02:00, dan frekuensi menunggu konfirmasi dosen.
