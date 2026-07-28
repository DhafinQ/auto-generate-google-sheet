import gspread
from gspread_formatting import (
    Border,
    Borders,
    CellFormat,
    Color,
    TextFormat,
    format_cell_range,
    format_cell_ranges,
)


def build_header_kop(worksheet, metadata, total_columns=16):
  """Membangun layout Kop Surat / Header Form Laporan di Google Sheets."""
  # -------------------------------------------------------------
  # 1. SETUP METADATA BINDING
  # -------------------------------------------------------------
  logo_url = metadata.get("company_logo_url", "")
  form_title = metadata.get(
      "form_title", "FORM HARIAN PRODUKSI DAN DISTRIBUSI IPA"
  )
  doc_info = metadata.get("doc_info", {})

  doc_num = doc_info.get("doc_number", "-")
  eff_date = doc_info.get("effective_date", "-")
  rev = doc_info.get("revision", "-")
  page = doc_info.get("page", "1 dari 1")

  # -------------------------------------------------------------
  # 2. ISI DATA KOP SURAT (Baris 1 s/d 4)
  # -------------------------------------------------------------
  if logo_url:
    worksheet.update_cell(1, 1, f'=IMAGE("{logo_url}")')
  else:
    worksheet.update_cell(1, 1, "LOGO")

  worksheet.update_cell(1, 3, form_title)

  # Tabel Metadata Kanan Atas
  worksheet.update_cell(1, 13, "No. Dok")
  worksheet.update_cell(1, 14, doc_num)

  worksheet.update_cell(2, 13, "Tgl Ber.")
  worksheet.update_cell(2, 14, eff_date)

  worksheet.update_cell(3, 13, "Rev")
  worksheet.update_cell(3, 14, rev)

  worksheet.update_cell(4, 13, "Hal")
  worksheet.update_cell(4, 14, page)

  # -------------------------------------------------------------
  # 3. MERGE CELLS UNTUK TAMPILAN KOP
  # -------------------------------------------------------------
  worksheet.merge_cells("A1:B4")  # Merge Area Logo
  worksheet.merge_cells("C1:L4")  # Merge Area Judul Utama

  # -------------------------------------------------------------
  # 4. FORMATTING & BORDER STYLE
  # -------------------------------------------------------------
  solid_line = Border("SOLID", Color(0, 0, 0))
  box_borders = Borders(
      top=solid_line, bottom=solid_line, left=solid_line, right=solid_line
  )

  # Format Teks Judul
  title_format = CellFormat(
      textFormat=TextFormat(bold=True, fontSize=13),
      horizontalAlignment="CENTER",
      verticalAlignment="MIDDLE",
      borders=box_borders,
  )

  # Format Label Metadata Kanan
  meta_label_format = CellFormat(
      textFormat=TextFormat(bold=True, fontSize=9),
      horizontalAlignment="LEFT",
      verticalAlignment="MIDDLE",
      borders=box_borders,
  )

  meta_val_format = CellFormat(
      textFormat=TextFormat(fontSize=9),
      horizontalAlignment="CENTER",
      verticalAlignment="MIDDLE",
      borders=box_borders,
  )

  # Eksekusi Formatting sekaligus
  format_cell_ranges(
      worksheet,
      [
          ("C1:L4", title_format),
          ("M1:M4", meta_label_format),
          ("N1:N4", meta_val_format),
          ("A1:B4", title_format),
      ],
  )

  # -------------------------------------------------------------
  # 5. BARIS INFORMASI TANGGAL (Baris 6)
  # -------------------------------------------------------------
  worksheet.update_cell(6, 1, "Hari/Tanggal :")
  worksheet.format("A6", {"textFormat": {"bold": True, "fontSize": 10}})

  return 8  # Kembalikan baris awal tempat tabel data ditaruh


def build_footer_signatures(worksheet, start_row, metadata):
  """Membangun layout Footer Tanda Tangan & Catatan Petugas Shift."""
  shifts = metadata.get("shifts", [])
  approvals = metadata.get("approvals", {})

  r = start_row

  # 1. Header Footer
  worksheet.update_cell(r, 1, "Petugas Shift")
  worksheet.update_cell(r, 4, "Diperiksa oleh")
  worksheet.update_cell(r, 6, "Catatan / Keterangan Operasional")

  worksheet.merge_cells(f"A{r}:C{r}")
  worksheet.merge_cells(f"D{r}:E{r}")
  worksheet.merge_cells(f"F{r}:L{r}")

  # 2. Body Nama Shift
  r_body = r + 1
  col_idx = 1
  for shift in shifts:
    shift_text = f"{shift['label']}: {shift['default_officer']}"
    worksheet.update_cell(r_body, col_idx, shift_text)
    col_idx += 1

  worksheet.update_cell(r_body, 4, f"Spw: {approvals.get('checked_by', '-')}")

  worksheet.merge_cells(f"F{r_body}:L{r_body+2}")
  worksheet.merge_cells(f"D{r_body}:E{r_body+2}")

  # 3. Border & Formatting
  solid_line = Border("SOLID", Color(0, 0, 0))
  box_borders = Borders(
      top=solid_line, bottom=solid_line, left=solid_line, right=solid_line
  )

  footer_header_format = CellFormat(
      textFormat=TextFormat(bold=True),
      horizontalAlignment="CENTER",
      borders=box_borders,
  )

  footer_body_format = CellFormat(
      textFormat=TextFormat(fontSize=9), borders=box_borders
  )

  format_cell_ranges(
      worksheet,
      [
          (f"A{r}:L{r}", footer_header_format),
          (f"A{r_body}:L{r_body+2}", footer_body_format),
      ],
  )