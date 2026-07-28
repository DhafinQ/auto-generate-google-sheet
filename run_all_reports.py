from datetime import datetime
import json
import os
import subprocess
import sys


def run_orchestrator():
  print("=" * 70)
  print(
      f" [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] MEMULAI OTOMATISASI"
      " GENERATOR LAPORAN HARIAN"
  )
  print("=" * 70)

  runner_config_file = "runner_config.json"
  if not os.path.exists(runner_config_file):
    print(f" Error: File `{runner_config_file}` tidak ditemukan!")
    return

  with open(runner_config_file, "r") as f:
    runner_config = json.load(f)

  reports_queue = runner_config.get("reports_queue", [])
  active_reports = [r for r in reports_queue if r.get("enabled", False)]

  print(
      f" Ditemukan {len(active_reports)} laporan aktif yang akan diproses.\n"
  )

  summary = []

  for idx, report in enumerate(active_reports, start=1):
    name = report.get("report_name")
    script = report.get("script_path")
    config = report.get("config_file")
    spreadsheet_id = report.get("spreadsheet_id")

    print(f"[{idx}/{len(active_reports)}] Memproses: '{name}'...")
    print(f"     Script: {script} | Config: {config}")

    if not os.path.exists(script):
      print(f"     Error: File script `{script}` tidak ditemukan!\n")
      summary.append((name, "FAILED (Script Missing)"))
      continue

    # Jalankan script sub-proses dengan mengirimkan argumen/env khusus
    env_vars = os.environ.copy()
    if config:
      env_vars["CONFIG_FILE"] = config
    if spreadsheet_id:
      env_vars["SPREADSHEET_ID"] = spreadsheet_id

    try:
      # Eksekusi script secara isolasi
      result = subprocess.run(
          [sys.executable, script],
          env=env_vars,
          capture_output=True,
          text=True,
          check=True,
      )
      print(f"     Berhasil!")
      summary.append((name, "SUCCESS"))
    except subprocess.CalledProcessError as e:
      print(f"    Gagal mengeksekusi script `{script}`!")
      print(f"    Detail Error:\n{e.stderr[:300]}...")
      summary.append((name, "FAILED"))

    print("-" * 50)

  # Ringkasan Akhir Eksekusi
  print("\n" + "=" * 70)
  print("RINGKASAN EKSEKUSI LAPORAN HARIAN")
  print("=" * 70)
  for name, status in summary:
    status_icon = "🟢" if "SUCCESS" in status else "🔴"
    print(f"{status_icon} {name:<45} : {status}")
  print("=" * 70 + "\n")


if __name__ == "__main__":
  run_orchestrator()