from datetime import datetime
import json
import os
from dotenv import load_dotenv
import gspread
from gspread_formatting import CellFormat, TextFormat, format_cell_range
from layout_builder import build_footer_signatures, build_header_kop
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, inspect

# 1. Load Environment Variables
load_dotenv()
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "")
DB_NAME = os.getenv("DB_NAME", "db_sensor")
DB_PORT = os.getenv("DB_PORT", 3306)
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")


def get_db_connection():
  """Membuat koneksi ke database MySQL menggunakan SQLAlchemy"""
  db_url = (
      f"mysql+mysqlconnector://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
  )
  return create_engine(db_url)


def process_all_reports_unified(engine, reports):
  """Menarik data snapshot terakhir mendekati setiap jam dengan kustomisasi label tabel dan kolom."""
  start_time = "2026-06-24 07:00:00"
  end_time = "2026-06-25 06:59:59"

  inspector = inspect(engine)

  # 1. Target jam presisi (2026-06-24 07:00 s.d. 2026-06-25 06:00)
  target_dt = pd.date_range(
      start="2026-06-24 07:00:00", end="2026-06-25 06:00:00", freq="1h"
  )
  df_targets = pd.DataFrame({"TargetTime": target_dt})
  df_targets["Jam"] = df_targets["TargetTime"].dt.strftime("%H:00")

  df_master = pd.DataFrame({"Jam": df_targets["Jam"]})

  header_l0_study_case = ["Jam"]
  header_l1_table_name = ["Jam"]
  header_l2_tag_label = ["Jam"]

  for report in reports:
    study_title = report["title"]
    tables = report["tables"]
    tag_filters = report["tag_filters"]
    column_labels = report.get("column_labels", {})
    table_labels = report.get(
        "table_labels", {}
    )  # <--- BACA CUSTOM LABEL TABEL

    for table in tables:
      if not inspector.has_table(table):
        continue

      existing_columns = [col["name"] for col in inspector.get_columns(table)]
      matched_tags = [
          tag
          for tag in tag_filters
          if tag in existing_columns and tag != "LocalTimestamp"
      ]

      if not matched_tags:
        continue

      select_cols = ", ".join([f"`{tag}`" for tag in matched_tags])

      query = f"""
                SELECT `LocalTimestamp`, {select_cols}
                FROM `{table}`
                WHERE `LocalTimestamp` >= '2026-06-24 06:50:00' 
                  AND `LocalTimestamp` <= '{end_time}'
                ORDER BY `LocalTimestamp` ASC
            """

      try:
        df_db = pd.read_sql(query, engine)
        if df_db.empty:
          continue

        df_db["LocalTimestamp"] = pd.to_datetime(df_db["LocalTimestamp"])

        # Backward Lookup: Mengambil record terakhir mendekati jam cutoff
        df_snapshot = pd.merge_asof(
            df_targets,
            df_db,
            left_on="TargetTime",
            right_on="LocalTimestamp",
            direction="backward",
        )

        df_snapshot[matched_tags] = df_snapshot[matched_tags].round(4)
        df_snapshot.rename(columns=column_labels, inplace=True)

        # Dapatkan label kustom tabel (fallback ke nama tabel asli jika tidak diset)
        display_table_name = table_labels.get(table, table)

        rename_prefix = {}
        for col in matched_tags:
          clean_tag_label = column_labels.get(col, col)
          unique_col_name = f"{table}___{clean_tag_label}"
          rename_prefix[clean_tag_label] = unique_col_name

          header_l0_study_case.append(study_title)
          header_l1_table_name.append(
              display_table_name
          )  # <--- GUNAKAN LABEL KUSTOM TABEL
          header_l2_tag_label.append(clean_tag_label)

        df_snapshot.rename(columns=rename_prefix, inplace=True)

        cols_to_keep = ["Jam"] + list(rename_prefix.values())
        df_res = df_snapshot[cols_to_keep]

        df_master = pd.merge(df_master, df_res, on="Jam", how="left")

      except Exception as e:
        print(f"❌ Error query snapshot tabel {table}: {e}")

  numeric_cols = df_master.select_dtypes(include=[np.number]).columns
  df_master[numeric_cols] = df_master[numeric_cols].round(4)

  return (
      df_master,
      header_l0_study_case,
      header_l1_table_name,
      header_l2_tag_label,
  )


def build_push_header(raw_header):
  """Menyiapkan array header yang bersih untuk di-push ke Google Sheets:

  Elemen pertama dari grup merge berisi teks, selanjut berisi string kosong.
  """
  push_header = []
  last_val = None
  for idx, item in enumerate(raw_header):
    if idx == 0:
      push_header.append("")  # Dikosongkan agar A8:A10 dapat di-merge vertikal
      continue

    if item == last_val:
      push_header.append("")
    else:
      push_header.append(item)
      last_val = item
  return push_header


def merge_row_headers(worksheet, start_row, raw_header_list):
  """Melakukan Merge Cells horizontal secara presisi menggunakan MERGE_ROWS."""
  col_idx = 2  # Mulai dari Kolom B (Kolom A 'Jam' diabaikan)
  total_cols = len(raw_header_list)

  while col_idx <= total_cols:
    item_name = raw_header_list[col_idx - 1]

    if not item_name or item_name == "Jam":
      col_idx += 1
      continue

    start_col = col_idx

    while (
        col_idx <= total_cols and raw_header_list[col_idx - 1] == item_name
    ):
      col_idx += 1

    end_col = col_idx - 1

    if end_col > start_col:
      start_a1 = gspread.utils.rowcol_to_a1(start_row, start_col)
      end_a1 = gspread.utils.rowcol_to_a1(start_row, end_col)
      try:
        worksheet.merge_cells(f"{start_a1}:{end_a1}", merge_type="MERGE_ROWS")
      except Exception as e:
        print(
            f"⚠️ Skip merge horizontal {start_a1}:{end_a1} untuk '{item_name}':"
            f" {e}"
        )


def main():
  print(
      f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Memulai Unified Master"
      " Table Report..."
  )

  # 1. Load Config JSON
  if not os.path.exists("config.json"):
    print("❌ File `config.json` tidak ditemukan!")
    return

  with open("config.json", "r") as file:
    config = json.load(file)

  preset_group = config["preset_groups"][config["active_preset_group"]]
  metadata = preset_group.get("metadata", {})

  # 2. Setup Google Sheets Connection
  try:
    gc = gspread.service_account(filename=CREDENTIALS_FILE)
    sh = gc.open_by_key(SPREADSHEET_ID)
  except Exception as e:
    print(f"❌ Gagal terhubung ke Google Sheets: {e}")
    return

  sample_date_str = "2026-06-24"
  sheet_target_name = preset_group["single_sheet_name_pattern"].replace(
      "{date}", sample_date_str
  )

  # -------------------------------------------------------------
  # LOGIKA RE-CREATE WORKSHEET (Hapus jika exist, lalu buat baru)
  # -------------------------------------------------------------
  try:
    existing_worksheet = sh.worksheet(sheet_target_name)

    # Buat dummy worksheet jika target sheet adalah satu-satunya sheet di spreadsheet
    if len(sh.worksheets()) == 1:
      sh.add_worksheet(title="Temp_Sheet", rows="1", cols="1")

    sh.del_worksheet(existing_worksheet)
    print(f"🗑️ Worksheet lama '{sheet_target_name}' berhasil dihapus.")
  except gspread.exceptions.WorksheetNotFound:
    pass

  # Buat worksheet baru yang segar
  worksheet = sh.add_worksheet(
      title=sheet_target_name, rows="1000", cols="60"
  )
  print(f"✨ Worksheet baru '{sheet_target_name}' berhasil dibuat.")

  # Hapus Temp_Sheet jika sempat dibuat
  try:
    temp_ws = sh.worksheet("Temp_Sheet")
    sh.del_worksheet(temp_ws)
  except gspread.exceptions.WorksheetNotFound:
    pass

  # -------------------------------------------------------------
  # BUILD LAPORAN & MERGE
  # -------------------------------------------------------------
  # A. Gambar Kop Surat
  current_row = build_header_kop(worksheet, metadata)
  worksheet.update_cell(6, 3, f"Rabu, {sample_date_str}")

  engine = get_db_connection()

  # B. Proses Seluruh Studi Kasus Menjadi Satu Matriks
  print("\n🔄 Memproses Seluruh Studi Kasus ke dalam Satu Tabel...")
  df_master, raw_h0, raw_h1, raw_h2 = process_all_reports_unified(
      engine, preset_group["reports"]
  )

  if len(raw_h0) <= 1:
    print("⚠️  Tidak ada data ditemukan.")
    return

  # Buat array header bersih untuk di-push
  push_h0 = build_push_header(raw_h0)
  push_h1 = build_push_header(raw_h1)

  push_h2 = list(raw_h2)
  push_h2[0] = ""

  values = df_master.fillna("-").values.tolist()
  data_block = [push_h0, push_h1, push_h2] + values

  # Push Blok Data
  worksheet.update(values=data_block, range_name=f"A{current_row}")

  # C. Merge Headers
  merge_row_headers(worksheet, current_row, raw_h0)  # Level 0
  merge_row_headers(worksheet, current_row + 1, raw_h1)  # Level 1

  # Merge Vertikal 'Jam' di Kolom A (A8:A10)
  try:
    worksheet.merge_cells(f"A{current_row}:A{current_row+2}")
    worksheet.update_cell(current_row, 1, "Jam")
  except Exception as e:
    print(f"⚠️ Notice pada Jam vertikal merge: {e}")

  # D. Apply Formatting Visual
  last_col_idx = len(raw_h0)
  last_col_letter = gspread.utils.rowcol_to_a1(1, last_col_idx)[:-1]
  last_row_data = current_row + len(data_block) - 1

  # Header Level 0 (Judul Studi Kasus)
  fmt_h0 = CellFormat(
      textFormat=TextFormat(bold=True, fontSize=11),
      horizontalAlignment="CENTER",
      verticalAlignment="MIDDLE",
      backgroundColor={"red": 0.78, "green": 0.85, "blue": 0.95},
  )
  format_cell_range(
      worksheet, f"A{current_row}:{last_col_letter}{current_row}", fmt_h0
  )

  # Header Level 1 (Nama Tabel)
  fmt_h1 = CellFormat(
      textFormat=TextFormat(bold=True, fontSize=10),
      horizontalAlignment="CENTER",
      verticalAlignment="MIDDLE",
      backgroundColor={"red": 0.88, "green": 0.88, "blue": 0.88},
  )
  format_cell_range(
      worksheet, f"A{current_row+1}:{last_col_letter}{current_row+1}", fmt_h1
  )

  # Header Level 2 (Nama Tag/Kolom)
  fmt_h2 = CellFormat(
      textFormat=TextFormat(bold=True, fontSize=9),
      horizontalAlignment="CENTER",
      verticalAlignment="TOP",
      wrapStrategy="WRAP",
      backgroundColor={"red": 0.96, "green": 0.96, "blue": 0.96},
  )
  format_cell_range(
      worksheet, f"A{current_row+2}:{last_col_letter}{current_row+2}", fmt_h2
  )

  # Body Data
  fmt_body = CellFormat(
      verticalAlignment="TOP",
      wrapStrategy="WRAP",
  )
  format_cell_range(
      worksheet,
      f"A{current_row+3}:{last_col_letter}{last_row_data}",
      fmt_body,
  )

  # E. Build Footer Tanda Tangan Shift
  print("\n🎨 Membangun Layout Footer...")
  build_footer_signatures(worksheet, last_row_data + 3, metadata)

  print(
      f"\n🎉 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Selesai! Laporan"
      f" Unified Master Table berhasil di-push ke sheet: '{sheet_target_name}'"
  )


if __name__ == "__main__":
  main()