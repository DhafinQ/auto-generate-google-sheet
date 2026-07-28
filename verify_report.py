from datetime import datetime, timedelta
import json
import os
from dotenv import load_dotenv
import pandas as pd
from sqlalchemy import create_engine, inspect

# Load Environment Variables
load_dotenv()
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "")
DB_NAME = os.getenv("DB_NAME", "db_sensor")
DB_PORT = os.getenv("DB_PORT", 3306)


def get_db_connection():
  db_url = (
      f"mysql+mysqlconnector://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
  )
  return create_engine(db_url)


def test_query_from_config(config_path="config_produksi_distribusi.json"):
  print("🔍 Memulai Diagnostik Penarikan Data dari Database...\n")

  if not os.path.exists(config_path):
    print(f"❌ File `{config_path}` tidak ditemukan!")
    return

  with open(config_path, "r") as f:
    config = json.load(f)

  mappings = config.get("fixed_column_mapping", [])
  engine = get_db_connection()
  inspector = inspect(engine)

  # Rentang waktu pengujian (Kemarin 07:00 s.d. Hari ini 07:00)
  now = datetime.now()
  today_str = now.strftime("%Y-%m-%d")
  yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

  start_cutoff = f"{yesterday_str} 06:50:00"
  end_cutoff = f"{today_str} 07:00:00"

  # Target jam presisi
  target_dt = pd.date_range(
      start=f"{yesterday_str} 07:00:00", end=f"{today_str} 07:00:00", freq="1h"
  )
  df_targets = pd.DataFrame({"TargetTime": target_dt})
  df_targets["Jam"] = df_targets["TargetTime"].dt.strftime("%H:00")

  # Kelompokkan berdasarkan nama tabel
  tables_group = {}
  for item in mappings:
    tbl = item["table"]
    col = item["column"]
    idx = item["target_column_index"]
    if tbl not in tables_group:
      tables_group[tbl] = []
    tables_group[tbl].append((col, idx))

  # Pengujian Per Tabel
  for table_name, col_list in tables_group.items():
    print("=" * 60)
    print(f"📊 MEMERIKSA TABEL: `{table_name}`")
    print("=" * 60)

    # 1. Cek Apakah Tabel Ada
    all_db_tables = inspector.get_table_names()
    matched_table = next(
        (t for t in all_db_tables if t.lower() == table_name.lower()), None
    )

    if not matched_table:
      print(
          f"❌ ERROR: Tabel `{table_name}` TIDAK DITEMUKAN di database"
          f" '{DB_NAME}'!"
      )
      print(f"   Tabel yang tersedia: {all_db_tables}")
      continue

    # 2. Cek Kolom yang Diminta
    existing_cols = [c["name"] for c in inspector.get_columns(matched_table)]
    print(f"✅ Tabel `{matched_table}` ditemukan. Memeriksa kolom...")

    valid_cols = []
    for col_name, idx in col_list:
      if col_name in existing_cols:
        print(f"   [Index {idx:2d}] Kolom `{col_name}` -> MATCH ✅")
        valid_cols.append((col_name, idx))
      else:
        print(f"   [Index {idx:2d}] Kolom `{col_name}` -> NOT FOUND ❌")

    if not valid_cols:
      print(
          f"⚠️ Tidak ada kolom yang cocok untuk ditanyakan ke tabel"
          f" `{matched_table}`.\n"
      )
      continue

    # 3. Jalankan Query SQL dengan Backticks Presisi
    cols_sql = ", ".join([f"`{c[0]}`" for c in valid_cols])
    query = f"""
            SELECT `LocalTimestamp`, {cols_sql}
            FROM `{matched_table}`
            WHERE `LocalTimestamp` >= '{start_cutoff}' 
              AND `LocalTimestamp` <= '{end_cutoff}'
            ORDER BY `LocalTimestamp` ASC
        """

    print(f"\n📝 Executing SQL:\n{query.strip()}\n")

    try:
      df_db = pd.read_sql(query, engine)
      print(
          f"📈 Total record mentah ditemukan di DB: {len(df_db)} baris"
          " timestamp."
      )

      if df_db.empty:
        print(
            "⚠️ WARNING: Query mengembalikan 0 baris data! Periksa apakah"
            f" sensor mengisi log pada rentang {start_cutoff} s.d."
            f" {end_cutoff}."
        )
        continue

      df_db["LocalTimestamp"] = pd.to_datetime(df_db["LocalTimestamp"])

      # 4. Uji Pemetaan Merge Snapshot
      df_snapshot = pd.merge_asof(
          df_targets,
          df_db,
          left_on="TargetTime",
          right_on="LocalTimestamp",
          direction="backward",
      )

      print("\n📋 Hasil Uji Snapshot Per Kolom:")
      for col_name, idx in valid_cols:
        series_num = pd.to_numeric(df_snapshot[col_name], errors="coerce")
        null_count = series_num.isna().sum()
        valid_count = len(series_num) - null_count

        if null_count == 0:
          status = "✅ 100% Terisi (Tidak ada -)"
        elif valid_count > 0:
          status = f"⚠️ Sebagian Terisi ({valid_count} terisi, {null_count} '-')"
        else:
          status = "❌ KOSONG TOTAL (Semua -)"

        print(f"   * Indeks {idx:2d} (`{col_name}`): {status}")

    except Exception as e:
      print(f"❌ Error saat mengeksekusi query: {e}")

    print("\n")


if __name__ == "__main__":
  test_query_from_config()