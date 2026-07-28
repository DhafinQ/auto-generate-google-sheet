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

# 2. Variable Dinamis dari Orchestrator (run_all_reports.py)
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
CONFIG_FILE = os.getenv("CONFIG_FILE", "config_produksi_distribusi.json")


def get_db_connection():
  db_url = (
      f"mysql+mysqlconnector://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
  )
  return create_engine(db_url)


def process_fixed_snapshot_data(
    engine, column_mappings, yesterday_str, today_str
):
  """Menarik data snapshot dari KEMARIN jam 07:00 s.d. HARI INI jam 06:00 (Pas 24 Baris)."""
  start_cutoff = f"{yesterday_str} 06:50:00"
  end_cutoff = f"{today_str} 07:00:00"

  inspector = inspect(engine)

  # Target jam laporan: 07:00 kemarin s.d. 06:00 hari ini (24 Baris)
  target_dt = pd.date_range(
      start=f"{yesterday_str} 07:00:00",
      end=f"{today_str} 06:00:00",
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
    decimals = item.get("decimals", 4)

    if tbl not in tables_group:
      tables_group[tbl] = []
    tables_group[tbl].append((col, idx, decimals))

  all_db_tables = inspector.get_table_names()

  for table_name, mappings in tables_group.items():
    matched_table = next(
        (t for t in all_db_tables if t.lower() == table_name.lower()), None
    )
    if not matched_table:
      continue

    existing_cols_map = {
        c["name"].lower(): c["name"]
        for c in inspector.get_columns(matched_table)
    }

    valid_mappings = []
    for target_col_name, idx, decimals in mappings:
      real_db_col = existing_cols_map.get(target_col_name.lower())
      if real_db_col:
        valid_mappings.append((real_db_col, idx, decimals))

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

      # Pembulatan Ceil Dinamis
      for real_db_col, col_index, decimals in valid_mappings:
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

  expected_cols = [f"COL_{i}" for i in range(1, 15)]
  for col in expected_cols:
    if col not in df_master.columns:
      df_master[col] = "-"

  return df_master[expected_cols].fillna("-")


def main():
  print(
      f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Memulai Automatic Daily"
      " Report Generator..."
  )

  # Validasi SPREADSHEET_ID
  if not SPREADSHEET_ID:
    print(
        " Error: `SPREADSHEET_ID` tidak ditemukan di environment variable!"
    )
    return

  # Tanggal Dinamis
  now = datetime.now()
  today_date = now.date()
  yesterday_date = today_date - timedelta(days=1)

  today_str = today_date.strftime("%Y-%m-%d")
  yesterday_str = yesterday_date.strftime("%Y-%m-%d")

  print(f"Periode Laporan: {yesterday_str} 07:00:00 s/d {today_str} 06:00:00 (24 Jam)")
  print(f"Config File    : {CONFIG_FILE}")
  print(f"Spreadsheet ID : {SPREADSHEET_ID}")

  TEMPLATE_SHEET_NAME = "template_produksi_distribusi"

  if not os.path.exists(CONFIG_FILE):
    print(f" File config `{CONFIG_FILE}` tidak ditemukan!")
    return

  with open(CONFIG_FILE, "r") as file:
    config = json.load(file)

  column_mappings = config.get("fixed_column_mapping", [])

  # Koneksi Google Sheets
  try:
    gc = gspread.service_account(filename=CREDENTIALS_FILE)
    sh = gc.open_by_key(SPREADSHEET_ID)
  except Exception as e:
    print(f" Gagal terhubung ke Google Sheets: {e}")
    return

  target_sheet_name = f"Laporan_{today_str}"

  try:
    template_worksheet = sh.worksheet(TEMPLATE_SHEET_NAME)
  except gspread.exceptions.WorksheetNotFound:
    print(
        f" Sheet Template '{TEMPLATE_SHEET_NAME}' tidak ditemukan di Google"
        " Sheets!"
    )
    return

  # Hapus sheet lama jika sudah ada
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

  # Update Tanggal di Kop
  formatted_date_label = f"{today_date.strftime('%d-%m-%Y')}"
  new_worksheet.update_cell(6, 3, f"Tanggal: {formatted_date_label}")

  # Tarik Data Snapshot (24 Baris)
  engine = get_db_connection()
  print("\n Memproses data snapshot dari MySQL...")
  df_data = process_fixed_snapshot_data(
      engine, column_mappings, yesterday_str, today_str
  )

  # Pisahkan 2 Blok
  block1_cols = [f"COL_{i}" for i in range(1, 11)]
  data_block1 = df_data[block1_cols].values.tolist()

  block2_cols = [f"COL_{i}" for i in range(11, 15)]
  data_block2 = df_data[block2_cols].values.tolist()

  # Push ke Range Presisi B11:K34 dan O11:R34 (Tepat 24 Baris)
  print(" Menulis Blok 1 (Kolom 1 - 10) ke range B11:K34...")
  new_worksheet.update(values=data_block1, range_name="B11:K34")

  print(" Menulis Blok 2 (Kolom 11 - 14) ke range O11:R34...")
  new_worksheet.update(values=data_block2, range_name="O11:R34")

  print(
      f"\n [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Selesai! Laporan"
      f" berhasil digenerate di sheet: '{target_sheet_name}'"
  )


if __name__ == "__main__":
  main()