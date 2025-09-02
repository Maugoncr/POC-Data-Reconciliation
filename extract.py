import re
from pathlib import Path
from typing import Dict, List, Optional, Any

import pdfplumber
import pandas as pd
from datetime import datetime

# ================================
# CARPETAS
# ================================
BASE = Path(__file__).resolve().parent / "project"
INPUT_DIR = BASE / "data" / "input_pdfs"
OUTPUT_DIR = BASE / "data" / "output"
OUTPUT_XLSX = OUTPUT_DIR / "pdf_extract.xlsx"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ================================
# ESQUEMA (alias + TIPO ESPERADO)
# Tipos soportados: "digits", "year", "date", "alnum", "age", "text"
# ================================
FIELD_SCHEMA: Dict[str, Dict[str, Any]] = {
    "Site Number": {
        "variants": ["Site Number", "Site No", "Site ID", "Derived Site ID"],
        "type": "digits",
    },
    "Subject": {
        # Ojo: Subject puede venir como "SCR-0001" => alfanumérico con guion
        "variants": ["Subject", "Subject ID"],
        "type": "alnum",
    },
    "Birth Year": {
        "variants": ["Birth Year", "Year of Birth", "YOB"],
        "type": "year",
    },
    "Age": {
        # Puede venir "2 Years", "11 Months", etc. (validamos que tenga dígitos)
        "variants": ["Age"],
        "type": "age",
    },
    "Sex Reported at Birth": {
        "variants": ["Sex Reported at Birth", "Sex at Birth", "Sex", "Derived Sex"],
        "type": "text",
    },
    "First Informed Consent Date": {
        "variants": ["First Informed Consent Date", "Informed Consent Date", "First Consent Date"],
        "type": "date",
    },
    "Randomization/Allocation Date": {
        "variants": [
            "Randomization/Allocation Date",
            "Randomization Date",
            "Allocation Date",
            "Randomization / Allocation Date",
        ],
        "type": "date",
    },
    "Randomization/Allocation Number": {
        "variants": [
            "Randomization/Allocation Number",
            "Randomization Number",
            "Allocation Number",
            "Randomization / Allocation Number",
        ],
        "type": "digits",
    },
    "Cohort": {
        "variants": ["Cohort", "Cohort Assignment"],
        "type": "text",
    },
    "Date of Component ID Assignment": {
        "variants": [
            "Date of Component ID Assignment",
            "Component ID Assignment Date",
            "Date of Component Assignment",
        ],
        "type": "date",
    },
    "Component ID": {
        "variants": ["Component ID", "Component Identifier", "ComponentID"],
        "type": "digits",  # <- clave para evitar "Assignment"
    },
}

# Normalización y utilidades -----------------------------------------------

def norm(s: str) -> str:
    if s is None:
        return ""
    s = s.replace("\u00A0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()

def norm_label(s: str) -> str:
    s = norm(s).lower()
    s = re.sub(r"[:]+$", "", s)   # quitar ":" al final si viene
    s = re.sub(r"\s+", " ", s)
    return s

def is_nullish(value: str) -> bool:
    return (not value) or value.lower().startswith("no value to display")

# Validadores por tipo ------------------------------------------------------

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12
}

DATE_PATTERNS = [
    # 12-Jun-2025, 1-Jan-2025, 01/02/2025, 2025-06-12, etc.
    r"\b\d{1,2}[-/](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*[-/]\d{4}\b",
    r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b",
    r"\b\d{4}[-/]\d{2}[-/]\d{2}\b",
]

def is_date(s: str) -> bool:
    if is_nullish(s):
        return False
    s = norm(s)
    return any(re.search(pat, s, flags=re.IGNORECASE) for pat in DATE_PATTERNS)

def is_digits(s: str) -> bool:
    if is_nullish(s):
        return False
    return bool(re.fullmatch(r"\d+", s))

def is_year(s: str) -> bool:
    if is_nullish(s):
        return False
    return bool(re.fullmatch(r"(19|20)\d{2}", s))

def is_alnum(s: str) -> bool:
    if is_nullish(s):
        return False
    # Permitimos letras, dígitos, guion, guion bajo
    return bool(re.fullmatch(r"[A-Za-z0-9\-_]+", s))

def is_age(s: str) -> bool:
    if is_nullish(s):
        return False
    # Debe tener al menos un dígito
    return bool(re.search(r"\d", s))

def is_text(s: str) -> bool:
    if is_nullish(s):
        return False
    return True

VALIDATORS = {
    "date": is_date,
    "digits": is_digits,
    "year": is_year,
    "alnum": is_alnum,
    "age": is_age,
    "text": is_text,
}

# Matching label ------------------------------------------------------------

def label_matches(cell_text: str, variants: List[str]) -> bool:
    t = norm_label(cell_text)
    for v in variants:
        if t == norm_label(v):       # coincidencia exacta normalizada
            return True
    return False

# Extracción desde TABLAS ---------------------------------------------------

def extract_from_tables(page, schema=FIELD_SCHEMA) -> Dict[str, Optional[str]]:
    found: Dict[str, Optional[str]] = {k: None for k in schema.keys()}

    # Preferir detección por líneas (bordes dibujados)
    table_settings = {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "intersection_tolerance": 5,
        "snap_tolerance": 3,
        "join_tolerance": 3,
    }

    try:
        tables = page.extract_tables(table_settings=table_settings) or []
    except Exception:
        tables = []

    for tbl in tables:
        # tbl es List[List[str|None]]
        for row in tbl:
            if not row:
                continue
            cells = [norm(c) for c in row if c is not None]
            if len(cells) < 1:
                continue
            # Saltar encabezados típicos
            first = norm(cells[0])
            if first.lower() in {"item", "field", "parameter"}:
                continue

            # label en primera celda no vacía, valor en última celda no vacía
            label_cell = None
            value_cell = None
            for c in cells:
                if c:
                    label_cell = c
                    break
            for c in reversed(cells):
                if c:
                    value_cell = c
                    break
            if not label_cell:
                continue

            for col_name, spec in schema.items():
                if found[col_name] is not None:
                    continue
                if label_matches(label_cell, spec["variants"]):
                    val = norm(value_cell or "")
                    if not is_nullish(val) and VALIDATORS[spec["type"]](val):
                        found[col_name] = val
    return found

# Extracción por LÍNEAS (fallback) -----------------------------------------

def value_after_label_by_lines(lines: List[str], label: str) -> Optional[str]:
    """
    Busca 'Label ... valor' en una sola línea, con cualquier separación,
    pero devolvemos valor solo si valida tipo más adelante.
    """
    pat = r"^\s*" + re.escape(label) + r"\b[:\s]*(.+)$"
    for ln in lines:
        m = re.match(pat, ln, flags=re.IGNORECASE)
        if m:
            return norm(m.group(1))
    return None

def extract_from_lines(page, schema=FIELD_SCHEMA) -> Dict[str, Optional[str]]:
    found: Dict[str, Optional[str]] = {k: None for k in schema.keys()}
    text = page.extract_text() or ""
    lines = [norm(ln) for ln in text.splitlines() if ln.strip()]

    for col_name, spec in schema.items():
        if found[col_name] is not None:
            continue
        # probar cada alias
        for v in spec["variants"]:
            val = value_after_label_by_lines(lines, v)
            if not val:
                continue
            # Evitar capturas tipo "Component ID Assignment"
            # (si el residuo es una sola palabra y no pasa validador, la descartamos)
            if not VALIDATORS[spec["type"]](val):
                continue
            found[col_name] = val
            break
    return found

# Master extractor por PDF --------------------------------------------------

def extract_fields_from_pdf(pdf_path: Path, schema=FIELD_SCHEMA) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {k: None for k in schema.keys()}
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                # 1) Tablas primero
                tbl_vals = extract_from_tables(page, schema)
                for k, v in tbl_vals.items():
                    if v and result[k] is None:
                        result[k] = v
                # 2) Fallback líneas
                line_vals = extract_from_lines(page, schema)
                for k, v in line_vals.items():
                    if v and result[k] is None:
                        result[k] = v

                # Cortar si ya tenemos todos
                if all(result[k] is not None for k in schema.keys()):
                    break
    except Exception as e:
        # Dejar rastro si no se pudo abrir/parsing
        result["Component ID"] = f"ERROR: {e}"
    return result

# MAIN ---------------------------------------------------------------------

def main():
    pdf_files = sorted(INPUT_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"No se encontraron PDFs en {INPUT_DIR}")
        return

    records = []
    for pdf_file in pdf_files:
        fields = extract_fields_from_pdf(pdf_file, FIELD_SCHEMA)
        fields["_source_pdf"] = pdf_file.name
        records.append(fields)

    ordered_cols = list(FIELD_SCHEMA.keys()) + ["_source_pdf"]
    df = pd.DataFrame(records, columns=ordered_cols)

    with pd.ExcelWriter(OUTPUT_XLSX, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="extract")
        ws = writer.sheets["extract"]
        ws.freeze_panes(1, 0)
        for i, col in enumerate(df.columns):
            width = max(15, min(50, df[col].astype(str).map(len).max() + 2))
            ws.set_column(i, i, width)

    print(f"✅ Archivo generado: {OUTPUT_XLSX}")

if __name__ == "__main__":
    main()
