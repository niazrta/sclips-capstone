# Sinkronisasi Data SINTA: Definisi dan Prosedur

Status: rancangan untuk disetujui. Kode sinkronisasi belum berjalan.

## 1. Tujuan
Basis data S-CLIPS harus akurat terhadap SINTA. Acuan kebenaran adalah situs SINTA. Sinkronisasi membandingkan data kita dengan SINTA, memperbaiki perbedaannya, dan mencatat setiap perubahan.

## 2. Sumber data
Alamat dirakit dari `SINTA_BASE_URL`, tidak tertanam di kode.

| Sumber | Halaman | Waktu | Isi |
| --- | --- | --- | --- |
| `listing` | daftar jurnal, 1.677 halaman | sekitar 70 menit (terukur pada audit) | nama, ISSN, penerbit dan tautan afiliasi, subject, badge peringkat, tautan, indeksasi, metrik |
| `profile` | satu jurnal | sekitar 2 detik per jurnal; semua jurnal sekitar 12 jam (hitungan, belum terukur) | riwayat akreditasi per tahun |

## 3. Cakupan
| Cakupan | Dilakukan | Tidak dilakukan |
| --- | --- | --- |
| `new` | Bandingkan daftar ID. Masukkan jurnal yang belum ada, ambil profilnya, antre prediksi ML. | Tidak mengubah jurnal yang ada. Tidak menandai yang hilang. |
| `update` | Bandingkan field jurnal yang sudah ada dengan listing, lalu perbarui yang berbeda. Profil diambil untuk jurnal yang belum pernah diambil atau badge-nya berubah (opsional: `--profile-batch N` untuk yang paling lama). | Tidak memasukkan jurnal baru. Tidak menandai yang hilang. |
| `full` | `new` + `update` + profil semua jurnal + penandaan jurnal yang hilang. | Tidak menghapus apa pun. |

Disarankan: `new` mingguan, `update` bulanan, `full` satu sampai tiga bulan sekali.

## 5. Prosedur (sama untuk semua cakupan)
1. Kumpulkan data dari sumber.
2. Periksa kelengkapan: semua halaman terambil (yang gagal diulang), jumlah baris sama dengan Total Records di header, ID unik.
3. Bandingkan dengan database berdasarkan ID SINTA.
4. Tentukan tindakan sesuai cakupan dan aturan bagian 4.
5. Terapkan, satu transaksi per jurnal, dan tulis `sync_changes`.
6. Laporkan di `sync_runs`.

Kalau listing tidak lengkap, penandaan jurnal hilang tidak dijalankan.

## 4. Aturan perbedaan
| Data | Bila berbeda dari SINTA |
| --- | --- |
| Nama, penerbit, subject | SINTA menang. Nilai lama dan baru dicatat. |
| ISSN | `*_raw` selalu sama dengan SINTA. `e_issn`/`p_issn` diisi hanya bila valid. |
| Metrik dan tautan | Ditimpa, `metrics_updated_at` diisi. |
| `rank_badge` | Ditimpa (peringkat resmi, `NA` = tidak terakreditasi). |
| Riwayat akreditasi | Tahun baru ditambah, tahun berbeda diperbarui, tidak ada yang dihapus. Baris yang tidak ada di SINTA tidak dibuat. Selisih badge dan riwayat terakhir dicatat. |
| Kosong di SINTA | Dikosongkan bila teks sumber memang kosong atau penanda (`0`, `-`). Bila teks ada tapi gagal diparse, nilai lama dipertahankan dan diberi peringatan. |
| Jurnal baru | Masuk sebagai `active`, antre prediksi ML. |
| Jurnal hilang | `unverified` dan nonaktif. Menjadi `inactive` setelah dua sinkron `full` berturut-turut. Hanya pada `full` yang lengkap. |

## 6. Data yang disimpan
- Identitas: `id` (ID SINTA), nama, `e_issn`/`p_issn` dan `*_raw`, subject.
- Penerbit: nama persis dari SINTA, `sinta_affiliation_id` (ID dari tautan, apa adanya).
- Peringkat: `rank_badge`, riwayat akreditasi per tahun.
- Tautan: website, editor, Google Scholar, `garuda_id` (URL Garuda dirakit dari ID).
- Indeksasi dan metrik: `scopus_indexed`, `garuda_indexed`, impact, h5-index, citations 5yr, citations.
- Waktu: `last_seen_at`, `metrics_updated_at`, `last_detail_scraped_at`.

Tidak disentuh sinkronisasi: kolom `predicted_*`, `publishers.type`, `publisher_size`, `type_confidence`, `journal_id_map`.

## 7. Pencatatan
- `sync_runs`: cakupan, pemicu (`scheduled` atau `manual`), `requested_by`, target ID, hasil, dan detak.
- `sync_changes`: run, jurnal, kolom, nilai lama, nilai baru.
- Sinkron manual memilih cakupan dan tercatat di `sync_runs`.

## 8. Pemanggilan (satu program)
```
python -m sync --scope new
python -m sync --scope update --source listing
python -m sync --scope update --source profile --id 671
python -m sync --scope full
```
Worker memanggil fungsi yang sama dengan parameter dari jadwal.

## 9. Pengaman
- Hanya satu run aktif pada satu waktu (indeks unik di database).
- Tidak ada penghapusan data.
- Penandaan hilang dibatalkan bila lebih dari 1% jurnal aktif hilang sekaligus (batas usulan, belum diuji).
- Berhenti setelah 10 kegagalan beruntun, lanjut dari progres tersimpan.
- Jeda 2 detik antar permintaan, jadwal di jam sepi.
- Run dengan detak berhenti lebih dari 10 menit ditandai gagal.

## 10. Hal terbuka
- Pemicu prediksi ML setelah sinkronisasi (dibahas dengan ML).
- Batas 1% dan ukuran batch profil adalah usulan.
- Hierarki fakultas ke universitas belum dipetakan.