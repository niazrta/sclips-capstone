# Sinkronisasi Data SINTA: Definisi dan Prosedur

Status: diimplementasikan. Diuji pada salinan database dan pada database utama (Nov 2026).

## 1. Tujuan
Basis data S-CLIPS harus akurat terhadap SINTA. Acuan kebenaran adalah situs SINTA. Sinkronisasi membandingkan data kita dengan SINTA, memperbaiki perbedaannya, dan mencatat setiap perubahan.

## 2. Sumber data
Alamat dirakit dari `SINTA_BASE_URL`, tidak tertanam di kode.

| Sumber | Halaman | Waktu (terukur) | Isi |
| --- | --- | --- | --- |
| listing | daftar jurnal, 1.677 halaman | sekitar 65 menit | nama, ISSN, penerbit dan tautan afiliasi, subject, badge, tautan, indeksasi, metrik |
| profil | satu jurnal | sekitar 2 detik per jurnal | riwayat akreditasi per tahun (satu-satunya sumber) |

Jeda antar permintaan 2 detik. robots.txt SINTA tidak melarang akses (`Disallow` kosong, diperiksa 8 November 2026).

## 3. Tiga cakupan
Satu program (`python -m sync --scope ...`), dipanggil dengan cakupan berbeda. Beda cakupan hanya pada apa yang boleh ditulis.

| Cakupan | Dilakukan | Tidak dilakukan |
| --- | --- | --- |
| `new` | Bandingkan Total Records halaman 1 dengan jumlah jurnal aktif. Bila beda, baca listing penuh, masukkan jurnal baru (profil diambil), tandai yang hilang. | Tidak mengubah field jurnal yang ada. |
| `update` | Bandingkan field jurnal yang sudah ada dengan listing, perbarui yang berbeda. Bila badge berubah, ambil profil untuk riwayat. | Tidak memasukkan jurnal baru, tidak menandai hilang. |
| `full` | `new` dan `update` dari satu pembacaan listing. Jurnal `unverified` yang masih absen menjadi `inactive`. | Tidak menghapus apa pun. |

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
| Kolom prediksi ML, tipe dan ukuran penerbit | Tidak pernah disentuh sinkronisasi. |
| Jurnal baru | Masuk `active`; penerbit baru dibuat tanpa tipe. |

## 6. Jurnal hilang
1. Hanya diproses bila listing lengkap.
2. Lebih dari 100 kandidat (aktif di database, absen di listing): run `paused`, tidak diperiksa.
3. Selain itu, sebuah jurnal kontrol dibuka dulu; bila tidak terbuka normal, tidak ada alihan yang dipercaya. Lalu profil tiap kandidat dibuka tanpa mengikuti alihan: dialihkan berarti terkonfirmasi, terbuka normal berarti tidak ditandai.
4. Terkonfirmasi 1 sampai 20: status `unverified` dan nonaktif. Lebih dari 20: tidak ada yang ditandai, run `paused`, daftar tercatat di `sync_changes` (`kandidat_hilang`).
5. Pada `full`, `unverified` yang masih absen dan masih dialihkan menjadi `inactive`.
6. Jurnal `unverified` yang muncul lagi di listing diaktifkan kembali.

Batas 20 dan 100 adalah parameter, bukan klaim literatur: total SINTA hanya turun 4 jurnal dalam sebulan.

## 7. Pencatatan dan penjadwalan
- `sync_runs`: cakupan, pemicu (`scheduled`/`manual`), status, detak, hitungan, pesan.
- `sync_changes`: run, jurnal, field, nilai lama, nilai baru.
- `sync_schedules`: jadwal harian, mingguan, bulanan, atau tanggal tertentu, dengan zona waktu. Dua jadwal awal (nonaktif): `new` harian 02:00 dan `full` Sabtu 02:00 WIB. Jam bisa diubah admin.
- Worker (`python -m sync.worker`) tiap 30 detik: memulihkan run macet (detak berhenti lebih dari 10 menit), membuat run dari jadwal jatuh tempo, mengambil run `queued` (tombol manual).
- Hanya satu run aktif sekaligus (indeks unik di database).
- Sepuluh halaman gagal beruntun menghentikan run.

## 8. Yang teruji dan belum
Teruji: `new` (jurnal baru, muncul lagi, 25 dan 120 kandidat, listing bolong), `update` (termasuk jalur profil), `full` (database utama, 0 perubahan terhadap SINTA 8 November), worker (antrean manual, jadwal harian), jadwal mingguan (perhitungan).
Belum teruji: profil yang masih terbuka padahal tidak ada di listing, gagal unduh dari jaringan, respons 429 sungguhan, jadwal bulanan dan tanggal, worker berjalan berjam-jam, eskalasi lebih dari 20 jurnal.

## 9. Hal terbuka
- Pemicu prediksi ML setelah sinkronisasi (menunggu ML dan FS).
- Aksi admin untuk jurnal yang dicurigai hilang.
- Jadwal cron, hierarki fakultas ke universitas, ISSN yang kurang dari 8 karakter (diduga lengkap di Garuda).
- Ambang 20 dan 100, jam 02:00, dan frekuensi menunggu konfirmasi dosen.