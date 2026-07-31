

# 📊 Automated Google Sheets Report Generator

Sistem otomatisasi untuk mengambil data laporan sensor dari database **MySQL** lokal, mengolahnya ke format matriks per jam, dan memperbarui (*push*) data tersebut secara berkala ke **Google Sheets**.

---

## 🛠️ Prasyarat (Prerequisites)

Sebelum memulai, pastikan perangkat Anda sudah terinstal:

* **Python 3.10+**
* **MySQL Database**
* Akun **Google Cloud Platform (GCP)** dengan proyek aktif.

---

## 🔑 Langkah 1: Setup Kredensial Google Cloud Platform (GCP)

Jika Anda belum memiliki file kredensial Google API, ikuti langkah-langkah berikut:

1. **Buka Google Cloud Console**: Masuk ke [Google Cloud Console](https://console.cloud.google.com/).
2. **Buat Proyek Baru** (atau pilih proyek yang sudah ada).
3. **Aktifkan API**:
* Buka menu **APIs & Services** > **Library**.
* Cari dan aktifkan **Google Sheets API**.
* Cari dan aktifkan **Google Drive API**.


4. **Buat Service Account**:
* Masuk ke **APIs & Services** > **Credentials**.
* Klik **+ Create Credentials** > pilih **Service Account**.
* Isi nama service account (misal: `bot-laporan`), lalu klik **Create and Continue** hingga selesai.


5. **Unduh Key JSON**:
* Klik email *Service Account* yang baru saja dibuat.
* Masuk ke tab **Keys** > klik **Add Key** > **Create new key**.
* Pilih format **JSON**, lalu klik **Create**. File `.json` akan otomatis diunduh.
* Simpan dan ubah nama file tersebut menjadi `credentials.json` di komputer Anda.


6. **Bagikan Akses Google Sheets**:
* Buka file `credentials.json`, lalu salin nilai dari field `"client_email"` (contoh: `bot-laporan@project-id.iam.gserviceaccount.com`).
* Buka Google Sheets target Anda.
* Klik tombol **Bagikan / Share**, masukkan email Service Account tersebut, ubah peran menjadi **Editor**, lalu simpan.



---

## 🚀 Langkah 2: Setup Proyek Setelah `git clone`

Setelah melakukan *clone* repository ini, ikuti langkah-langkah instalasi berikut:

### 1. Clone Repository

```bash
git clone https://github.com/DhafinQ/auto-generate-google-sheet.git
cd auto-generate-google-sheet

```

### 2. Taruh File Kredensial GCP

Pindahkan file `credentials.json` yang sudah Anda unduh ke direktori utama proyek (*root folder*):

```text
auto-generate-google-sheet/
├── configs/
├──── example.json
├── credentials.json  <-- Letakkan di sini
├── .env.example
├── main.py
...

```

### 3. Buat dan Aktifkan Virtual Environment (`venv`)

* **Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1

```


* **Windows (CMD):**
```cmd
python -m venv venv
.\venv\Scripts\activate.bat

```


* **Linux / MacOS:**
```bash
python3 -m venv venv
source venv/bin/activate

```



### 4. Install Dependencies

Pastikan `venv` sudah aktif (ditandai dengan `(venv)` pada terminal), lalu jalankan:

```bash
pip install -r requirements.txt

```

---

## ⚙️ Langkah 3: Konfigurasi Environment (`.env`) dan configs

1. Salin file `.env.example` menjadi `.env`:
* **Linux/Mac:** `cp .env.example .env`
* **Windows:** `copy .env.example .env`


2. Sesuaikan konfigurasi di dalam file `.env` dengan kredensial database dan ID Google Sheet Anda:

```env
# Database Credentials
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASS=password_db_anda
DB_NAME=nama_database_anda

# Application Path
GOOGLE_CREDENTIALS_FILE=credentials.json

```

3. Sesuaikan konfigurasi configs di dalam file `configs/*.json` dengan data template spreadsheet yang akan dibuat:

Setiap laporan harian diatur melalui file konfigurasi berbasis JSON di dalam folder `configs/`. Anda dapat menduplikasi file `configs/example.json` dan menyimpannya dengan nama file baru (misalnya: `configs/config_produksi_distribusi.json`).

> **Catatan:** File dengan awalan nama `example` (seperti `example.json`) akan diabaikan secara otomatis oleh skrip pemroses.

#### Struktur & Format Properti JSON

```json
{
  "report_name": "Laporan Kualitas Proses Produksi",
  "enabled": true,
  "single_sheet_name_pattern": "{date}",
  "metadata": {
    "template_spreadsheet_id": "id_spreadsheet",
    "target_folder_id": "id_folder_spreadsheet_disimpan",
    "monthly_filename_pattern": "Laporan Kualitas Proses Produksi - {month_year}",
    "template_sheet_name": "template_kualitas_proses_produksi",
    "date_cell": { "row": 5, "col": 3 },
    "zero_as_off": false,
    "intervals": {
      "start_time": "07:00",
      "end_time": "07:00",
      "interval_step_hours": 1,
      "buffer_minutes": 10
    },
    "local_excel": {
      "enabled": true,
      "template_path": "./templates/excel/template_kualitas_proses_produksi.xlsx",
      "output_dir": "./output_reports",
      "filename_pattern": "Laporan_Kualitas_{date}.xlsx"
    }
  },
  "fixed_column_mapping": [
    {
      "target_column_index": 1,
      "target_col_letter": "B",
      "target_row": 10,
      "table": "Flow",
      "column": "Tot_In_WTP50LPS",
      "decimals": 0
    },
    {
      "target_column_index": 2,
      "target_col_letter": "C",
      "target_row": 10,
      "table": "Flow",
      "column": "In_WTP50LPS",
      "decimals": 2
    }
  ]
}

```

---

#### Penjelasan Parameter Konfigurasi:

##### **Properti Utama (Root Level)**

* **`report_name`** *(String)*: Nama/judul laporan untuk keperluan pencatatan ringkasan eksekusi (*log summary*).
* **`enabled`** *(Boolean)*: Atur `true` untuk mengaktifkan pemrosesan laporan, atau `false` untuk menonaktifkan sementara.
* **`single_sheet_name_pattern`** *(String)*: Pola penamaan tab/worksheet harian di Google Sheets. Gunakan variabel `{date}` untuk menyisipkan tanggal (contoh hasil: `2026-07-31`).

---

##### **Objek `metadata`**

* **`template_spreadsheet_id`** *(String)*: ID file Spreadsheet Google Drive yang digunakan sebagai master *template*.
* **`target_folder_id`** *(String)*: ID folder Google Drive tempat pencarian/penyimpanan file Spreadsheet bulanan.
* **`monthly_filename_pattern`** *(String)*: Format nama file bulanan di Google Drive. Gunakan variabel `{month_year}` untuk menyisipkan nama bulan dan tahun (contoh hasil: `Laporan Kualitas Proses Produksi - Juli 2026`).
* **`template_sheet_name`** *(String)*: Nama tab/worksheet di dalam master *template* yang akan diduplikasi menjadi tab harian.
* **`date_cell`** *(Object)*: Koordinat sel untuk menuliskan label tanggal laporan pada kop surat (`row`: baris, `col`: indeks kolom angka, misal `3` = kolom C).
* **`zero_as_off`** *(Boolean)*: Jika `true`, semua nilai sensor bernilai `0` akan otomatis diubah menjadi teks `"Off"`.
* **`intervals`** *(Object)*:
* **`start_time`**: Jam mulai siklus operasional harian (format `HH:MM`).
* **`end_time`**: Jam selesai siklus operasional harian (format `HH:MM`).
* **`interval_step_hours`**: Step interval data jam-jaman (misal `1` untuk per 1 jam, `2` untuk per 2 jam).
* **`buffer_minutes`**: Margin toleransi pencarian data mundur dari MySQL (rekomendasi: `10`–`60` menit).


* **`local_excel`** *(Object - Opsional)*:
* **`enabled`**: Atur `true` jika ingin membuat salinan *backup* file Excel (`.xlsx`) di penyimpanan lokal server.
* **`template_path`**: Path file template `.xlsx` lokal.
* **`output_dir`**: Folder tujuan penyimpan laporan Excel lokal.
* **`filename_pattern`**: Format nama file Excel lokal.



---

##### **Array `fixed_column_mapping`**

Mendefinisikan pemetaan dari kolom tabel MySQL ke kolom sel pada sheet/Excel:

* **`target_column_index`** *(Integer)*: Nomor urut unik penanda kolom data internal.
* **`target_col_letter`** *(String)*: Posisi huruf kolom target di Google Sheets/Excel (`"A"`, `"B"`, `"AA"`, dst.).
* **`target_row`** *(Integer)*: Posisi nomor baris awal penulisan baris pertama data.
* **`table`** *(String)*: Nama tabel sumber di MySQL (case-insensitive).
* **`column`** *(String)*: Nama kolom/field sensor di tabel MySQL.
* **`decimals`** *(Integer)*: Jumlah pembulatan angka desimal (masukkan `0` untuk bilangan bulat `int`).

> **Catatan ID Template Spreadsheet:** URL Google Sheet Anda berbentuk `(https://docs.google.com/spreadsheets/d/ID_SPREADSHEET_ANDA/edit)`. Salin bagian acak huruf/angka tersebut ke `template_spreadsheet_id`.> 

> **Catatan ID Folder:** URL Folder Google Drive Anda berbentuk `(https://drive.google.com/drive/folders/ID_FOLDER_ANDA)`. Salin bagian acak huruf/angka tersebut ke properti `target_folder_id`.>


---

## ▶️ Cara Menjalankan Script

Jalankan script utama Python:

```bash
python run_all_reports.py

```