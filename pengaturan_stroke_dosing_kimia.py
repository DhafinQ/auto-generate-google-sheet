from datetime import datetime, timedelta
import json
import os
from dotenv import load_dotenv
import gspread
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, inspect

# 1. Load Environment Variables (.env)
load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "")
DB_NAME = os.getenv("DB_NAME", "db_sensor")
DB_PORT = os.getenv("DB_PORT", 3306)
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

# Variable Dinamis dari Orchestrator (run_all_reports.py)
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
CONFIG_FILE = os.getenv("CONFIG_FILE", "config_dosing_chlorine.json")

# Mapping Bahasa Indonesia untuk Hari & Bulan
HARI_INDONESIA = {
    "Monday": "Senin",
    "Tuesday": "Selasa",
    "Wednesday": "Rabu",
    "Thursday": "Kamis",
    "Friday": "Jumat",
    "Saturday": "Sabtu",
    "Sunday": "Minggu",
}

BULAN_INDONESIA = {
    1: "Januari",
    2: "Februari",
    3: "Maret",
    4: "April",
    5: "Mei",
    6: "Juni",
    7: "Juli",
    8: "Agustus",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Desember",
}


def get_db_connection():
  db_url = (
      f"mysql+mysqlconnector://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
  )
  return create_engine(db_url)


def process_fixed_snapshot_data(
    engine, column_mappings, yesterday_str, today_str
):
  """Menarik data snapshot dari KEMARIN jam 07:00 s.d. HARI INI jam 07:00 (Pas 25 Baris)."""
  start_cutoff = f"{yesterday_str} 06:50:00"
  end_cutoff = f"{today_str} 07:10:00"

  inspector = inspect(engine)

  # Target jam laporan: 07:00 kemarin s.d. 07:00 hari ini (25 Baris: Row 10 - Row 34)
  target_dt = pd.date_range(
      start=f"{yesterday_str} 07:00:00",
      end=f"{today_str} 07:00:00",
      freq="1h",
  )

  df_targets = pd.DataFrame({"TargetTime": target_dt})
  df_targets["Jam"] = df_targets["TargetTime"].dt.strftime("%H:00")

  df_master = pd.DataFrame({"Jam": df_targets["Jam"]})

  # Grouping mapping berdasarkan nama tabel
  tables_group = {}
  for item in column_mappings:
    tbl = item["table"]
    col = item["column"]
    idx = item["target_column_index"]
    letter = item["target_col_letter"]
    decimals = item.get("decimals", 0)

    if tbl not in tables_group:
      tables_group[tbl] = []
    tables_group[tbl].append((col, idx, letter, decimals))

  all_db_tables = inspector.get_table_names()

  for table_name, mappings in tables_group.items():
    matched_table = next(
        (t for t in all_db_tables if t.lower() == table_name.lower()), None
    )
    if not matched_table:
      print(f" Warning: Tabel `{table_name}` tidak ditemukan di database!")
      continue

    existing_cols_map = {
        c["name"].lower(): c["name"]
        for c in inspector.get_columns(matched_table)
    }

    valid_mappings = []
    for target_col_name, idx, letter, decimals in mappings:
      real_db_col = existing_cols_map.get(target_col_name.lower())
      if real_db_col:
        valid_mappings.append((real_db_col, idx, letter, decimals))

    if not valid_mappings:
      continue

    select_cols = ", ".join([f"`{m[0]}`" for m in valid_mappings])
    query = f"""
            SELECT `LocalTimestamp`, {select_cols}
            FROM `{matched_table}`
            WHERE `LocalTimestamp` >= '{start_cutoff}' 
              AND `LocalTimestamp` <= '{end_cutoff}'
            ORDER BY `LocalTimestamp` ASC
        """

    try:
      df_db = pd.read_sql(query, engine)
      if df_db.empty:
        continue

      df_db["LocalTimestamp"] = pd.to_datetime(df_db["LocalTimestamp"])

      # Logic Snapshot (Backward Lookup)
      df_snapshot = pd.merge_asof(
          df_targets,
          df_db,
          left_on="TargetTime",
          right_on="LocalTimestamp",
          direction="backward",
      )

      # Pembulatan & Formatting Dinamis (Nilai 0 Tetap Ditulis Angka 0)
      for real_db_col, col_index, letter, decimals in valid_mappings:
        col_master_key = f"COL_{col_index}"
        series_numeric = pd.to_numeric(
            df_snapshot[real_db_col], errors="coerce"
        )

        if decimals == 0:
          processed_series = np.ceil(series_numeric)
          df_master[col_master_key] = (
              processed_series.fillna("-")
              .apply(lambda x: int(x) if isinstance(x, (int, float)) else x)
          )
        else:
          factor = 10**decimals
          processed_series = np.ceil(series_numeric * factor) / factor
          df_master[col_master_key] = processed_series.fillna("-")

    except Exception as e:
      print(f" Error query tabel {matched_table}: {e}")

  return df_master


def main():
  print(
      f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Memulai Report Dosing &"
      " Chlorine Generator..."
  )

  if not SPREADSHEET_ID:
    print(
        " Error: `SPREADSHEET_ID` tidak ditemukan di environment variable!"
    )
    return

  now = datetime.now()
  today_date = now.date()
  yesterday_date = today_date - timedelta(days=1)

  today_str = today_date.strftime("%Y-%m-%d")
  yesterday_str = yesterday_date.strftime("%Y-%m-%d")

  print(
      f" Periode Laporan: {yesterday_str} 07:00:00 s/d {today_str} 07:00:00"
      " (25 Jam)"
  )
  print(f" Config File    : {CONFIG_FILE}")
  print(f" Spreadsheet ID : {SPREADSHEET_ID}")

  if not os.path.exists(CONFIG_FILE):
    print(f" File config `{CONFIG_FILE}` tidak ditemukan!")
    return

  with open(CONFIG_FILE, "r") as file:
    config = json.load(file)

  column_mappings = config.get("fixed_column_mapping", [])
  TEMPLATE_SHEET_NAME = config.get(
      "template_sheet_name", "template_pengaturan_stroke_pompa_bahan_kimia"
  )

  # Koneksi Google Sheets
  try:
    gc = gspread.service_account(filename=CREDENTIALS_FILE)
    sh = gc.open_by_key(SPREADSHEET_ID)
  except Exception as e:
    print(f" Gagal terhubung ke Google Sheets: {e}")
    return

  target_sheet_name = f"Laporan_Dosing_{yesterday_str}"

  try:
    template_worksheet = sh.worksheet(TEMPLATE_SHEET_NAME)
  except gspread.exceptions.WorksheetNotFound:
    print(
        f" Sheet Template '{TEMPLATE_SHEET_NAME}' tidak ditemukan di Google"
        " Sheets!"
    )
    return

  # Hapus sheet harian lama jika ada
  try:
    old_sheet = sh.worksheet(target_sheet_name)
    sh.del_worksheet(old_sheet)
    print(f" Sheet harian lama '{target_sheet_name}' dihapus.")
  except gspread.exceptions.WorksheetNotFound:
    pass

  # Duplikasi Template
  print(f" Menduplikasi '{TEMPLATE_SHEET_NAME}' -> '{target_sheet_name}'...")
  new_worksheet = template_worksheet.duplicate(
      new_sheet_name=target_sheet_name
  )

  # Update Tanggal di Kop Surat (Sel B6:C6 Merged) -> "Senin, 27 Juli 2026"
  hari_nama = HARI_INDONESIA.get(yesterday_date.strftime("%A"), "")
  bulan_nama = BULAN_INDONESIA.get(yesterday_date.month, "")
  formatted_laporan_date = (
      f"{hari_nama}, {yesterday_date.day} {bulan_nama} {yesterday_date.year}"
  )

  new_worksheet.update_cell(5, 3, formatted_laporan_date)

  # Tarik Data Snapshot dari MySQL
  engine = get_db_connection()
  print("\n Memproses data snapshot dari MySQL...")
  df_master = process_fixed_snapshot_data(
      engine, column_mappings, yesterday_str, today_str
  )

  # PUSH DATA PER KOLOM (Sesuai Row 10 s.d 34 -> Pas 25 Baris)
  print(" Menulis data ke kolom target di Google Sheets...")
  batch_updates = []

  for item in column_mappings:
    idx = item["target_column_index"]
    col_letter = item["target_col_letter"]
    col_key = f"COL_{idx}"

    if col_key in df_master.columns:
      # Ambil 25 baris data untuk kolom ini
      values_list = [[v] for v in df_master[col_key].tolist()]
      range_str = f"{col_letter}10:{col_letter}34"

      batch_updates.append({"range": range_str, "values": values_list})

  if batch_updates:
    new_worksheet.batch_update(batch_updates)
    print(f" Berhasil mengupdate {len(batch_updates)} kolom target!")

  print(
      f"\n [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Selesai! Laporan"
      f" Dosing berhasil digenerate di sheet: '{target_sheet_name}'"
  )


if __name__ == "__main__":
  main()