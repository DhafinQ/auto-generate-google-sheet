

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
git clone https://github.com/username/repository-name.git
cd repository-name

```

### 2. Taruh File Kredensial GCP

Pindahkan file `credentials.json` yang sudah Anda unduh ke direktori utama proyek (*root folder*):

```text
repository-name/
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

## ⚙️ Langkah 3: Konfigurasi Environment (`.env`)

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

# Google Sheets Configuration
SPREADSHEET_ID=1a2b3c4d5e6f...  # Ambil ID dari URL Google Sheet Anda
WORKSHEET_NAME=Laporan_Harian

# Application Path
GOOGLE_CREDENTIALS_FILE=credentials.json

```

> **Catatan ID Spreadsheet:** URL Google Sheet Anda berbentuk `[https://docs.google.com/spreadsheets/d/ID_SPREADSHEET_ANDA/edit](https://docs.google.com/spreadsheets/d/ID_SPREADSHEET_ANDA/edit)`. Salin bagian acak huruf/angka tersebut ke `SPREADSHEET_ID`.

---

## ▶️ Cara Menjalankan Script

Jalankan script utama Python:

```bash
python main.py

```