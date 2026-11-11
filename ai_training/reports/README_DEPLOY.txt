S-CLIPS v2.7-LinearSVM-Calibrated-Lexicon-16768
Dibuat           : 2026-11-10
Data             : journals_classified_v2.6.xlsx sheet 2_Full_16768_Jurnal (asal: journals_export_20261105_161058_1.csv)
                   16.768 jurnal aktif, 14.983 bersubjek SINTA
Model            : sclips_models_v2.7.pkl (22,0 MB)
SHA-256 model    : 5e9841f96ba473a6faefe1d7a2b853e6c3393b3ccc92960c2f1a23c79886fd37   (sudah tertanam di sclips_ml_service.py)
Python / sklearn : scikit-learn 1.6.1, numpy 2.4.6, scipy 1.16.3 (sama dengan v2.6)

======================================================================
APA YANG BERUBAH DARI v2.6
======================================================================
1. TIDAK ADA LAGI LABEL "Unknown". Semua 16.768 jurnal mendapat subjek SINTA, rumpun Scopus dan
   bidang Scopus-27. Semua jurnal yang punya nama penerbit mendapat tipe penerbit; 17 jurnal tanpa nama
   penerbit (kosong / "Unknown") sengaja tidak diberi tipe & ukuran (null).
   (v2.6: 1.102 subjek Unknown, 36 tipe penerbit Unknown, 17 kosong.)
2. Model subjek SINTA dilatih ulang dan diperkuat:
   - kamus akar kata bidang ilmu (39 kelompok; Indonesia, Inggris, Arab, Latin/Belanda), dicocokkan juga di
     dalam kata bentukan (mis. Farmanesia -> farma, Iktiologi, Respirologi, Juridisch, Tanzhimuna);
   - petunjuk dari sebaran subjek jurnal lain milik penerbit yang sama;
   - dilatih dari SEMUA subjek SINTA tiap jurnal (bukan hanya satu subjek utama hasil aturan).
3. Keyakinan (confidence) subjek kini = peluang label yang ditampilkan memang subjek SINTA jurnal itu,
   dikalibrasi out-of-fold. Label yang ditampilkan SELALU >= 70%:
   - satu subjek bila keyakinannya >= 70%;
   - bila belum, dua subjek teratas ("Education, Social") dengan peluang salah satunya benar >= 70%.
4. Scopus-4 diturunkan dari probabilitas subjek SINTA -> selalu konsisten (tidak ada lagi "hierarki tidak konsisten").
   Scopus-27 dibatasi ke bidang yang sah untuk subjek terpilih.
5. Multidisiplin: jurnal yang SUDAH punya subjek SINTA dengan >= 4 subjek ditampilkan "Multidisciplinary"
   (2.135 jurnal). Model TIDAK memprediksi Multidisciplinary untuk jurnal tanpa subjek: hasil uji menunjukkan
   kelas ini tidak dapat dipelajari dari judul (model hanya memilihnya untuk < 1% jurnal), dan judul yang sulit
   dikenali tidak lebih multidisiplin daripada judul lain.
6. Tipe penerbit tanpa Unknown:
   - nama tanpa kata dikenal & tanpa aturan kelembagaan -> COM ("aturan_default_independen", keyakinan 74,3% =
     kecocokan aturan ini dengan tipe penerbit lama SINTA pada 513 jurnal sejenis), 34 jurnal;
   - press kampus yang namanya digabung (Unpadpress, Staiqodpress) -> HEI;
   - tanpa nama penerbit (kosong, "-", atau "Unknown", mis. publisher id 73; 17 jurnal) -> predicted_publisher_type,
     publisher_classification_confidence, publisher_size = null, publisher_type_source = "tanpa_penerbit",
     catatan "tanpa_nama_penerbit_tipe_tidak_diberikan". Subjek tetap diprediksi. Status tidak menjadi Needs Review
     karena hal ini. (Perilaku lama, label mayoritas HEI: set env SCLIPS_ASSIGN_TYPE_WITHOUT_PUBLISHER=1.)
7. Ambang Needs Review = 70% untuk subjek & tipe penerbit. Needs Review turun dari 3.226 (v2.6) menjadi 129
   jurnal (0,8%), seluruhnya karena tipe penerbit (129 keyakinan < 70%, 41 di antaranya juga konflik aturan vs model).
8. Model TIDAK perlu dilatih ulang ketika ada jurnal baru. Jurnal baru langsung diklasifikasikan oleh model yang sama.

======================================================================
ISI PAKET
======================================================================
- sclips_models_v2.7.pkl + sclips_ml_service.py -> HARUS satu pasang (service menolak start bila SHA tidak cocok)
- requirements.txt                 -> versi library yang dikunci (sama dengan v2.6)
- journals_classified_v2.7.xlsx    -> hasil 16.768 jurnal. Sheet 1 = output API persis untuk payload Data Mining
                                      (POST /classify/predict, tanpa subject_sinta, dengan publisher_counts)
    0_Daftar_Isi         1_Untuk_Data_Mining      2_Full_16768_Jurnal (+ data asal, contoh tampilan katalog, hasil v2.6)
    3_Prediksi_Tanpa_Subjek (1.785)   4_Needs_Review (129)   5_Ringkasan   6_Evaluasi_Model
    7_Keandalan_Keyakinan   8_Presisi_Per_Subjek   9_Kamus_Akar_Kata   10_Eks_Unknown_v2.6 (1.102)
    11_Confusion_Matrix     12_Kamus_Kolom
- evaluation_report_v2.7.json      -> laporan evaluasi lengkap
- reliability_v2.7.png, v26_vs_v27.png, cm_sinta_10_v2.7.png -> gambar untuk laporan
- train_v27.py                     -> skrip pelatihan (butuh journals_classified_v2.6.xlsx & sclips_models_v2.6.pkl
                                      di folder yang sama, atau set SCLIPS_TRAIN_XLSX / SCLIPS_V26_PKL)

======================================================================
UNTUK FULLSTACK
======================================================================
- Ganti sclips_ml_service.py dan .pkl dengan versi v2.7 (keduanya), install requirements.txt (tidak berubah).
- Endpoint sama dengan v2.6: GET /classify/health, POST /classify/predict, POST /classify/predict-async,
  GET /classify/tasks/{task_id}, GET /classify/tasks.
- Input baru (opsional, disarankan): "subject_sinta" per jurnal = string subjek SINTA asli, mis. "Education, Science".
- Kolom baru di output:
    subject_display             -> PAKAI INI UNTUK TAMPILAN SUBJEK DI KATALOG
                                   (subjek SINTA asli bila ada; >= 4 subjek -> "Multidisciplinary"; selain itu label ML)
    subject_display_id          -> versi Bahasa Indonesia
    subject_display_source      -> sinta | sinta_multidisiplin | ml   (tampilkan lencana "Prediksi" bila ml)
    subject_display_confidence  -> keyakinan % bila dari ML (selalu >= 70), kosong bila dari SINTA
    subject_label / _id / _level / _confidence -> label ML murni (subjek | dua_subjek | rumpun)
    notes                       -> catatan informatif (tidak mengubah status)
- predicted_subject_scopus_27_id selalu terisi (19 nilai: 18 bidang + "Multidisiplin") -> aman untuk filter.
- predicted_subject_scopus bernilai "Multidisciplinary" hanya bila subject_sinta dikirim dan berisi >= 4 subjek.
  Tanpa subject_sinta (payload Data Mining) semua kolom predicted_* murni hasil ML.
- Label subjek untuk ditampilkan dari ML = predicted_subject_sinta_multilabel (selalu >= 70%).
- Tidak ada lagi nilai "Unknown"/"Tidak Diketahui". predicted_publisher_type & publisher_size bisa null hanya untuk
  jurnal tanpa nama penerbit (publisher_type_source = "tanpa_penerbit").

======================================================================
UNTUK DATA MINING (integrasi dengan scope sinkronisasi)
======================================================================
Panggil lewat HTTP: POST /classify/predict, batch <= 1.000 jurnal, TANPA ?background=true (respons 200 + results).
Cek dulu GET /classify/health -> model_sha256 harus = 5e9841f96ba473a6faefe1d7a2b853e6c3393b3ccc92960c2f1a23c79886fd37

Setelah setiap sinkronisasi (manual maupun terjadwal):
  - scope "update" (perbarui data jurnal yang ada)   -> klasifikasikan ULANG SEMUA jurnal aktif
  - scope "full"   (yang ada + jurnal baru)          -> klasifikasikan ULANG SEMUA jurnal aktif
  - scope per ID   (hanya jurnal dengan ID tertentu) -> klasifikasikan jurnal ID tersebut saja
Alasan klasifikasi ulang semua: cepat (16.768 jurnal sekitar 25 detik, 17 batch), hasil deterministik (jurnal
yang tidak berubah mendapat hasil yang sama persis), dan ukuran penerbit serta subject_display ikut segar bila
jumlah jurnal per penerbit atau subjek SINTA berubah. Tidak perlu melacak kolom mana yang berubah.

Payload per jurnal: journal_id, journal_title (wajib), publisher_name_clean / publisher_name_raw, publisher_id,
subject_sinta (subjek SINTA asli; kosongkan bila tidak ada).
Kirim "publisher_counts" {"<publisher_id>": jumlah_jurnal} dari SELECT publisher_id, COUNT(*) ... GROUP BY publisher_id
(WAJIB untuk scope per ID agar ukuran penerbit benar).
Simpan SEMUA kolom output, termasuk subject_display*, subject_label*, processing_status, review_reasons, model_version.
422 = payload tidak valid (perbaiki data, jangan retry). 500 = retry dengan jeda. Timeout cukup 30 detik.

======================================================================
EVALUASI (data uji 20% yang tidak dipakai melatih model maupun kalibrator; diuji lewat predict_batch service)
======================================================================
                                         Uji per judul      Uji per penerbit baru
  Jurnal uji                                 2.977               3.267
  Label "Unknown"                            0                   0
  Label dengan keyakinan >= 70%              100%                99,97%
  Label yang ditampilkan benar               89,65%              89,47%
  Subjek teratas termasuk subjek SINTA       86,90%              86,38%
  Label satu subjek: cakupan / benar         87,0% / 90,3%       83,6% / 90,7%
  Label dua subjek: cakupan / salah satu benar  13,0% / 85,2%    16,2% / 83,4%
  Judul eks-Unknown v2.6: label benar        74,5% (n=204)       77,8% (n=212)
Keandalan keyakinan (uji per judul): pita 70-80% -> benar 75,6%; 80-90% -> 86,8%; 90-100% -> 95,9%.
Pembanding pada split yang sama: konfigurasi v2.6 = subjek teratas benar 83,3%, judul eks-Unknown 62,3%
(dan v2.6 memberi Unknown untuk judul tersebut).
Definisi "benar": satu subjek -> termasuk subjek SINTA jurnal; dua subjek -> minimal satu termasuk.

BATASAN
- Humanities tetap kelas terlemah (presisi subjek teratas 54-65%), sering tertukar dengan Education/Social.
- Model tipe penerbit dan Scopus-27 sama dengan v2.6 (silver label); metriknya lihat evaluation_report_v2.6.json.
- Pada penerbit yang benar-benar baru, pita keyakinan 80-90% sedikit terlalu yakin (rata-rata 83,7% vs benar 80,3%).
- Aturan bawaan COM (34 jurnal) adalah tebakan berbasis statistik, bukan dari bukti nama penerbit;
  ditandai di publisher_type_source = "aturan_default_independen".
