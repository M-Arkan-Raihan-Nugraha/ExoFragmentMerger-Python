# Exo Fragment Merger

Utility untuk menggabungkan file `.exo` bernomor menjadi MP4, dengan pilihan subtitle yang dapat di-burn-in atau tanpa subtitle.

## Persyaratan

- Python 3.10 atau lebih baru
- FFmpeg tersedia di `PATH` atau diberikan melalui `--ffmpeg`
- Untuk burn-in subtitle: FFmpeg dibangun dengan `libass` dan encoder `libx264`

Tidak ada package Python tambahan yang diperlukan.

## Penggunaan

Untuk penggunaan yang lebih mudah, jalankan GUI desktop:

```powershell
python -m app
```

Di GUI, pilih folder sumber, pilih mode **Satu video** atau **Banyak episode**, pilih subtitle, lalu tentukan output. FFmpeg tetap harus tersedia di `PATH`.

Fragmen dan subtitle dicari secara rekursif di folder `--input-dir`. Nomor di awal nama file `.exo` menentukan urutan penggabungan.

```powershell
# Lihat semua subtitle yang tersedia
python -m app.exo_merger --input-dir .\data\input\episode_01 --list-subtitles

# Pilih bahasa melalui kode ekstensi
python -m app.exo_merger --input-dir .\data\input\episode_01 --subtitle en --output .\data\output\video_english.mp4

# Pilih file tertentu, termasuk bila ada lebih dari satu subtitle bahasa yang sama
python -m app.exo_merger --input-dir .\data\input\episode_01 --subtitle subtitle_indo.vtt --output .\data\output\video_indonesia.mp4

# Hasilkan video tanpa subtitle
python -m app.exo_merger --input-dir .\data\input\episode_01 --subtitle none --output .\data\output\video_no_subtitle.mp4

# Timpa output yang sudah ada secara eksplisit
python -m app.exo_merger --input-dir .\data\input\episode_01 --subtitle in_ID --output .\data\output\video_hardsub_final.mp4 --overwrite
```

Jika dijalankan di terminal interaktif dan ada beberapa subtitle, program menampilkan menu. Tanpa input pilihan, program memilih `.in_ID` bila tersedia; di mode non-interaktif gunakan `--subtitle` untuk memilih bahasa atau file secara eksplisit.

## Banyak episode

Gunakan satu subfolder langsung untuk setiap episode:

```text
series/
├── Episode 01/
│   └── downloads/0/*.exo ...
├── Episode 02/
│   └── downloads/0/*.exo ...
└── Episode 03/
    └── downloads/0/*.exo ...
```

Proses semuanya sekaligus:

```powershell
python -m app.exo_merger --input-dir .\series --batch --subtitle in_ID --output-dir .\hasil
```

Hasilnya menjadi `hasil/Episode_01.mp4`, `hasil/Episode_02.mp4`, dan seterusnya. Fragmen boleh berada di subfolder lebih dalam; yang penting folder episode adalah subfolder langsung dari `--input-dir`. Tanpa `--batch`, perilaku lama tetap berlaku dan seluruh fragmen di bawah satu folder dianggap satu episode.

## Struktur proyek

```text
app/                       kode aplikasi
tests/                     unit test
data/input/episode_01/     fragmen dan subtitle sumber
data/output/               video hasil
docs/                      dokumentasi tambahan
```

Entry point production tersedia melalui `python -m app`. Setelah package di-install, gunakan command `exo-merger-gui` untuk GUI dan `exo-merger` untuk CLI. Episode baru sebaiknya dibuat sebagai subfolder baru di `data/input/`.

GUI menyediakan **Scan & validasi**, progress proses, pembatalan FFmpeg, dan opsi **Lewati hasil yang sudah ada** untuk melanjutkan batch yang pernah terhenti. Untuk membuat aplikasi Windows:

```powershell
python -m pip install pyinstaller
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

Hasil portable adalah satu file `dist/ExoFragmentMerger.exe`. FFmpeg sudah dibundel di dalam executable, jadi user tidak perlu memasang FFmpeg, mengatur `PATH`, atau membawa folder pendamping.

## Opsi

- `-i, --input-dir`: folder pencarian fragmen dan subtitle; default `.`.
- `-s, --subtitle`: kode bahasa seperti `ar`, `en`, `es`, `fil`, `in_ID`, `pt`, nama file subtitle, atau `none`.
- `--list-subtitles`: tampilkan subtitle yang ditemukan tanpa memproses video.
- `-o, --output`: lokasi MP4; default `video_hardsub_final.mp4`.
- `--overwrite`: izinkan mengganti output yang sudah ada. Tanpa opsi ini, output lama dilindungi.
- `--skip-existing`: lewati output yang sudah ada sehingga batch dapat dilanjutkan.
- `--allow-gaps`: lanjutkan meskipun ada indeks segmen yang hilang. Secara default gap dan nomor duplikat menghentikan proses.
- `--batch`: proses setiap subfolder langsung sebagai satu episode.
- `--output-dir`: folder hasil untuk mode `--batch`; default-nya folder berdasarkan `--output`.
- `--preset`: preset `libx264`; default `ultrafast`.
- `--crf`: kualitas `libx264` dari 0 sampai 51; default `23`.
- `--ffmpeg`: path executable FFmpeg; default `ffmpeg`.

Video dengan subtitle akan meng-encode ulang gambar agar teks menjadi permanen. Audio disalin. Tanpa subtitle, stream audio/video disalin tanpa re-encode.

Pemrosesan menggunakan folder sementara di sebelah file output dan baru mengganti output setelah FFmpeg berhasil. Folder sementara dibersihkan otomatis jika proses selesai atau gagal.

## Tes

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```
