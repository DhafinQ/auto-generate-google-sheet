from datetime import datetime, timedelta
import glob
import json
import os
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
import gspread
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, inspect

# 1. Load Environment Variables Global (.env)
load_dotenv()
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "")
DB_NAME = os.getenv("DB_NAME", "db_sensor")
DB_PORT = os.getenv("DB_PORT", 3306)
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

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


def col_letter_to_index(col_letter):
  num = 0
  for c in col_letter.upper():
    num = num * 26 + (ord(c) - ord("A") + 1)
  return num


def index_to_col_letter(col_idx):
  result = ""
  while col_idx > 0:
    col_idx, remainder = divmod(col_idx - 1, 26)
    result = chr(65 + remainder) + result
  return result


def group_contiguous_columns(column_mappings):
  if not column_mappings:
    return []

  sorted_mappings = sorted(
      column_mappings, key=lambda x: col_letter_to_index(x["target_col_letter"])
  )
  groups = []
  current_group = [sorted_mappings[0]]

  for prev, curr in zip(sorted_mappings[:-1], sorted_mappings[1:]):
    prev_idx = col_letter_to_index(prev["target_col_letter"])
    curr_idx = col_letter_to_index(curr["target_col_letter"])

    if (
        curr_idx == prev_idx + 1
        and int(curr["target_row"]) == int(prev["target_row"])
    ):
      current_group.append(curr)
    else:
      groups.append(current_group)
      current_group = [curr]

  if current_group:
    groups.append(current_group)
  return groups


def get_or_create_monthly_spreadsheet(gc, metadata, target_date):
  """Mencari file bulanan. Jika belum ada, buat spreadsheet baru via gspread/Sheets API."""
  template_spreadsheet_id = metadata.get("template_spreadsheet_id")
  target_folder_id = metadata.get("target_folder_id")
  monthly_pattern = metadata.get(
      "monthly_filename_pattern", "Laporan - {month_year}"
  )

  month_name = BULAN_INDONESIA.get(target_date.month, "")
  month_year_str = f"{month_name} {target_date.year}"
  target_filename = monthly_pattern.replace("{month_year}", month_year_str)

  creds = service_account.Credentials.from_service_account_file(
      CREDENTIALS_FILE, scopes=["https://www.googleapis.com/auth/drive"]
  )
  drive_service = build("drive", "v3", credentials=creds)

  query = (
      f"name = '{target_filename}' and '{target_folder_id}' in parents and"
      " mimeType = 'application/vnd.google-apps.spreadsheet' and trashed ="
      " false"
  )
  results = (
      drive_service.files().list(q=query, fields="files(id, name)").execute()
  )
  files = results.get("files", [])

  if files:
    found_id = files[0]["id"]
    print(
        f"    📁 Found existing monthly file: '{target_filename}' (ID:"
        f" {found_id})"
    )
    return found_id

  print(f"    ✨ Membuka/Membuat File Bulanan Baru -> '{target_filename}'...")

  new_sh = gc.create(target_filename, folder_id=target_folder_id)
  new_id = new_sh.id

  master_sh = gc.open_by_key(template_spreadsheet_id)
  template_sheet_name = metadata.get("template_sheet_name")

  template_ws = master_sh.worksheet(template_sheet_name)
  template_ws.copy_to(new_id)

  try:
    default_sheet = new_sh.worksheet("Sheet1")
    new_sh.del_worksheet(default_sheet)
  except Exception:
    pass

  print(f"    🎉 File bulanan berhasil dibuat & disiapkan! (ID: {new_id})")
  return new_id


def process_fixed_snapshot_data(
    engine, column_mappings, metadata, yesterday_str, today_str
):
  """Memproses pemetaan kolom snapshot per jam (statis)."""
  if not column_mappings:
    return pd.DataFrame()

  intervals = metadata.get(
      "intervals",
      {
          "start_time": "07:00",
          "end_time": "07:00",
          "interval_step_hours": 1,
          "buffer_minutes": 10,
      },
  )
  zero_as_off = metadata.get("zero_as_off", False)

  start_time = intervals.get("start_time", "07:00")
  end_time = intervals.get("end_time", "07:00")
  step_hours = intervals.get("interval_step_hours", 1)
  buffer_minutes = intervals.get("buffer_minutes", 10)

  start_dt_str = f"{yesterday_str} {start_time}:00"
  end_dt_str = f"{today_str} {end_time}:00"

  start_cutoff = (
      pd.to_datetime(start_dt_str) - timedelta(minutes=buffer_minutes)
  ).strftime("%Y-%m-%d %H:%M:%S")
  end_cutoff = (
      pd.to_datetime(end_dt_str) + timedelta(minutes=buffer_minutes)
  ).strftime("%Y-%m-%d %H:%M:%S")

  target_dt = pd.date_range(
      start=start_dt_str, end=end_dt_str, freq=f"{step_hours}h"
  )
  df_targets = pd.DataFrame({"TargetTime": target_dt})
  df_master = pd.DataFrame(
      {"Jam": df_targets["TargetTime"].dt.strftime("%H:%M")}
  )

  tables_group = {}
  for item in column_mappings:
    tbl = item["table"]
    if tbl not in tables_group:
      tables_group[tbl] = []
    tables_group[tbl].append((
        item["column"],
        item["target_column_index"],
        item.get("decimals", 0),
    ))

  inspector = inspect(engine)
  all_db_tables = inspector.get_table_names()

  for table_name, mappings in tables_group.items():
    matched_table = next(
        (t for t in all_db_tables if t.lower() == table_name.lower()), None
    )
    if not matched_table:
      continue

    existing_cols = {
        c["name"].lower(): c["name"]
        for c in inspector.get_columns(matched_table)
    }
    valid_mappings = [
        (existing_cols[c.lower()], idx, dec)
        for c, idx, dec in mappings
        if c.lower() in existing_cols
    ]

    if not valid_mappings:
      continue

    select_cols = ", ".join([f"`{m[0]}`" for m in valid_mappings])
    query = f"SELECT `LocalTimestamp`, {select_cols} FROM `{matched_table}` WHERE `LocalTimestamp` >= '{start_cutoff}' AND `LocalTimestamp` <= '{end_cutoff}' ORDER BY `LocalTimestamp` ASC"

    try:
      df_db = pd.read_sql(query, engine)
      if df_db.empty:
        continue
      df_db["LocalTimestamp"] = pd.to_datetime(df_db["LocalTimestamp"])

      df_snapshot = pd.merge_asof(
          df_targets,
          df_db,
          left_on="TargetTime",
          right_on="LocalTimestamp",
          direction="backward",
          tolerance=pd.Timedelta(minutes=buffer_minutes),
      )

      for real_col, idx, decimals in valid_mappings:
        col_key = f"COL_{idx}"
        series = pd.to_numeric(df_snapshot[real_col], errors="coerce")

        if decimals == 0:
          proc = np.ceil(series).fillna("-")
          proc = proc.apply(
              lambda x: int(x) if isinstance(x, (int, float)) else x
          )
        else:
          factor = 10**decimals
          proc = (np.ceil(series * factor) / factor).fillna("-")

        if zero_as_off:
          proc = proc.apply(
              lambda x: "Off" if x in [0, "0", 0.0, "0.0"] else x
          )

        df_master[col_key] = proc

    except Exception as e:
      print(f"❌ Error query {matched_table}: {e}")

  for item in column_mappings:
    col_key = f"COL_{item['target_column_index']}"
    if col_key not in df_master.columns:
      df_master[col_key] = "-"

  return df_master


def process_dynamic_event_data(
    engine, event_config, yesterday_str, today_str, metadata
):
  """Memproses tabel custom/dynamic event (misal Backwash Filter) dari multi tabel."""
  intervals = metadata.get(
      "intervals",
      {
          "start_time": "07:00",
          "end_time": "07:00",
      },
  )
  start_time = intervals.get("start_time", "07:00")
  end_time = intervals.get("end_time", "07:00")

  start_cutoff = f"{yesterday_str} {start_time}:00"
  end_cutoff = f"{today_str} {end_time}:00"

  tables = event_config.get("tables_pattern", [])
  output_cols_cfg = event_config.get("output_columns", [])

  inspector = inspect(engine)
  all_db_tables = inspector.get_table_names()

  all_events = []

  for tbl in tables:
    matched_table = next(
        (t for t in all_db_tables if t.lower() == tbl.lower()), None
    )
    if not matched_table:
      continue

    # Ekstrak WTP dan Nomor Filter dari nama tabel (misal "250_FT1_BW_IND")
    parts = tbl.split("_")
    wtp_val = parts[0] if len(parts) > 0 else "-"
    filter_val = parts[1] if len(parts) > 1 else "-"

    query = f"""
            SELECT * FROM `{matched_table}` 
            WHERE `LocalTimestamp` >= '{start_cutoff}' 
              AND `LocalTimestamp` <= '{end_cutoff}'
            ORDER BY `LocalTimestamp` ASC
        """
    try:
      df_db = pd.read_sql(query, engine)
      if df_db.empty:
        continue

      for _, row in df_db.iterrows():
        row_data = []
        raw_ts = row["LocalTimestamp"]

        for col_cfg in output_cols_cfg:
          c_type = col_cfg.get("type")

          if c_type == "TIMESTAMP_FORMAT":
            dt = pd.to_datetime(raw_ts)
            row_data.append(dt.strftime(col_cfg.get("format", "%H:%M")))

          elif c_type == "TABLE_NAME_SPLIT":
            idx = col_cfg.get("index", 0)
            row_data.append(wtp_val if idx == 0 else filter_val)

          elif c_type == "DB_COLUMN":
            col_name = col_cfg.get("column")
            val = row.get(col_name, "-")
            dec = col_cfg.get("decimals", 0)
            if pd.notnull(val) and val != "-":
              try:
                row_data.append(int(val) if dec == 0 else round(float(val), dec))
              except ValueError:
                row_data.append(val)
            else:
              row_data.append("-")

          elif c_type == "EXPRESSION_SUM":
            sum_cols = col_cfg.get("sum_columns", [])
            total_sum = sum([float(row.get(c, 0) or 0) for c in sum_cols])
            dec = col_cfg.get("decimals", 0)
            row_data.append(int(total_sum) if dec == 0 else round(total_sum, dec))

          else:
            row_data.append("-")

        # Simpan tuple: (LocalTimestamp murni untuk sorting, list data sel)
        all_events.append((pd.to_datetime(raw_ts), row_data))

    except Exception as e:
      print(f"❌ Error query event tabel `{tbl}`: {e}")

  # Urutkan seluruh kejadian berdasarkan urutan waktu (Timestamp ASC)
  all_events.sort(key=lambda x: x[0])
  return [item[1] for item in all_events]


def process_report_config(config_file_path, engine, gc):
  """Memproses 1 file konfigurasi JSON (Mendukung Fixed & Dynamic Event Mapping)."""
  with open(config_file_path, "r") as f:
    config = json.load(f)

  column_mappings = config.get("fixed_column_mapping", [])
  dynamic_event_mappings = config.get("dynamic_event_mapping", [])
  metadata = config.get("metadata", {})
  sheet_pattern = config.get("single_sheet_name_pattern", "{date}")
  template_name = metadata.get("template_sheet_name", "template_sheet")
  date_cell = metadata.get("date_cell", {"row": 5, "col": 3})

  now = datetime.now()
  today_date = (now + timedelta(days=1)).date()
  yesterday_date = today_date - timedelta(days=1)
  today_str = today_date.strftime("%Y-%m-%d")
  yesterday_str = yesterday_date.strftime("%Y-%m-%d")

  # 1. Dynamic Lookup/Create Monthly Spreadsheet ID
  monthly_spreadsheet_id = get_or_create_monthly_spreadsheet(
      gc, metadata, yesterday_date
  )

  # 2. Target Sheet Harian
  target_sheet_name = sheet_pattern.replace("{date}", yesterday_str)

  sh = gc.open_by_key(monthly_spreadsheet_id)

  try:
    template_ws = sh.worksheet(template_name)
  except gspread.exceptions.WorksheetNotFound:
    raise ValueError(
        f"Template sheet '{template_name}' tidak ditemukan di Spreadsheet!"
    )

  # Hapus sheet harian lama jika ada (re-run)
  try:
    sh.del_worksheet(sh.worksheet(target_sheet_name))
  except gspread.exceptions.WorksheetNotFound:
    pass

  # Duplikasi Tab Template
  new_ws = template_ws.duplicate(new_sheet_name=target_sheet_name)

  # Update Tanggal Kop Surat
  hari = HARI_INDONESIA.get(yesterday_date.strftime("%A"), "")
  bulan = BULAN_INDONESIA.get(yesterday_date.month, "")
  formatted_date = f"{hari}, {yesterday_date.day} {bulan} {yesterday_date.year}"
  new_ws.update_cell(
      date_cell.get("row", 5), date_cell.get("col", 3), formatted_date
  )

  # -------------------------------------------------------------
  # A. PROSES FIXED COLUMN MAPPING (Snapshot Per Jam)
  # -------------------------------------------------------------
  if column_mappings:
    df_data = process_fixed_snapshot_data(
        engine, column_mappings, metadata, yesterday_str, today_str
    )
    if not df_data.empty:
      groups = group_contiguous_columns(column_mappings)
      for g in groups:
        start_c, end_c = g[0]["target_col_letter"], g[-1]["target_col_letter"]
        start_r = int(g[0]["target_row"])
        end_r = start_r + len(df_data) - 1
        range_str = f"{start_c}{start_r}:{end_c}{end_r}"

        keys = [f"COL_{item['target_column_index']}" for item in g]
        new_ws.update(values=df_data[keys].values.tolist(), range_name=range_str)

  # -------------------------------------------------------------
  # B. PROSES DYNAMIC EVENT MAPPING (Backwash Filter Event)
  # -------------------------------------------------------------
  if dynamic_event_mappings:
    for event_cfg in dynamic_event_mappings:
      event_rows = process_dynamic_event_data(
          engine, event_cfg, yesterday_str, today_str, metadata
      )

      if event_rows:
        start_r = int(event_cfg.get("target_start_row", 10))
        end_r = start_r + len(event_rows) - 1
        start_col = event_cfg.get("columns_start_letter", "A")

        # Hitung huruf kolom akhir secara dinamis
        end_col_idx = col_letter_to_index(start_col) + len(event_rows[0]) - 1
        end_col = index_to_col_letter(end_col_idx)

        range_str = f"{start_col}{start_r}:{end_col}{end_r}"
        new_ws.update(values=event_rows, range_name=range_str)
        print(f"    ✨ Log Event '{event_cfg.get('event_name')}' berhasil ditulis: {len(event_rows)} baris!")


def main():
  print("=" * 70)
  print(
      f"🚀 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] MEMULAI OTOMATISASI"
      " GENERATOR LAPORAN HARIAN"
  )
  print("=" * 70)

  engine = get_db_connection()
  gc = gspread.service_account(filename=CREDENTIALS_FILE)

  BASE_DIR = os.path.dirname(os.path.abspath(__file__))
  config_folder = os.path.join(BASE_DIR, "configs")
  json_files = glob.glob(os.path.join(config_folder, "*.json"))

  valid_files = [
      f for f in json_files if not os.path.basename(f).startswith("example")
  ]

  active_reports = []
  for filepath in valid_files:
    try:
      with open(filepath, "r") as f:
        cfg = json.load(f)
        if cfg.get("enabled", False):
          active_reports.append((filepath, cfg))
    except Exception as e:
      print(f"⚠️ Warning: Gagal membaca file {filepath}: {e}")

  print(
      f"📋 Ditemukan {len(active_reports)} laporan aktif yang akan diproses.\n"
  )

  summary = []

  for idx, (filepath, cfg) in enumerate(active_reports, start=1):
    report_name = cfg.get("report_name", os.path.basename(filepath))
    print(f"[{idx}/{len(active_reports)}] Memproses: '{report_name}'...")
    print(f"    📄 Config: {os.path.basename(filepath)}")

    try:
      process_report_config(filepath, engine, gc)
      print("    ✅ Berhasil!\n")
      summary.append((report_name, "SUCCESS"))
    except Exception as e:
      print(f"    ❌ Gagal memproses laporan!")
      print(f"    ⚠️ Detail Error: {e}\n")
      summary.append((report_name, "FAILED"))

  print("=" * 70)
  print("📊 RINGKASAN EKSEKUSI LAPORAN HARIAN")
  print("=" * 70)
  for name, status in summary:
    status_icon = "🟢" if status == "SUCCESS" else "🔴"
    print(f"{status_icon} {name:<50} : {status}")
  print("=" * 70 + "\n")


if __name__ == "__main__":
  main()