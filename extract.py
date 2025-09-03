# extract.py
# Versión: 1.2.0  (tablas primero, validadores por tipo y limpieza final de DF)

import re
from pathlib import Path
from typing import Dict, List, Optional, Any

import pdfplumber
import pandas as pd

# ================================
# CARPETAS
# ================================
BASE = Path(__file__).resolve().parent / "project"
INPUT_DIR = BASE / "data" / "input_pdfs"
OUTPUT_DIR = BASE / "data" / "output"
OUTPUT_XLSX = OUTPUT_DIR / "pdf_extract.xlsx"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
INPUT_DIR.mkdir(parents=True, exist_ok=True)

# ================================
# ESQUEMA (alias + TIPO ESPERADO)
# Tipos: "digits", "year", "date", "alnum", "age", "text"
# ================================
FIELD_SCHEMA: Dict[str, Dict[str, Any]] = {
    "Site Number": {
        "variants": ["Site Number", "Site No", "Site ID", "Derived Site ID"],
        "type": "digits",
    },
    "Subject": {
        "variants": ["Subject", "Subject ID"],
        "type": "alnum",  # ej. SCR-0001
    },
    "Birth Year": {
        "variants": ["Birth Year", "Year of Birth", "YOB"],
        "type": "year",
    },
    "Age": {
        "variants": ["Age"],
        "type": "age",  # requiere al menos un dígito (e.g., "2 Years")
    },
    "Sex Reported at Birth": {
        "variants": ["Sex Reported at Birth"],
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
        "type": "digits",  # evita capturar "Assignment"
    },
}

# ================================
# Normalización y utilidades
# ================================
def norm(s: str) -> str:
    if s is None:
        return ""
    s = s.replace("\u00A0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()

def norm_label(s: str) -> str:
    s = norm(s).lower()
    s = re.sub(r"[:]+$", "", s)    # quitar ":" al final si viene
    s = re.sub(r"\s+", " ", s)
    return s

def is_nullish(value: str) -> bool:
    return (not value) or value.strip() == "" or value.strip().lower().startswith("no value to display")

# ================================
# Validadores por tipo
# ================================
DATE_PATTERNS = [
    r"\b\d{1,2}[-/](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*[-/]\d{4}\b",  # 12-Jun-2025
    r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b",                                                      # 01/02/2025
    r"\b\d{4}[-/]\d{2}[-/]\d{2}\b",                                                            # 2025-06-12
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
    return bool(re.fullmatch(r"[A-Za-z0-9\-_]+", s))

def is_age(s: str) -> bool:
    if is_nullish(s):
        return False
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

# ================================
# Matching de etiqueta
# ================================
def label_matches(cell_text: str, variants: List[str]) -> bool:
    t = norm_label(cell_text)
    for v in variants:
        if t == norm_label(v):
            return True
    return False

# ================================
# Extracción desde TABLAS
# (con guardas para evitar label como valor)
# ================================
def extract_from_tables(page, schema=FIELD_SCHEMA) -> Dict[str, Optional[str]]:
    def same_as_any_variant(value: str, variants: List[str]) -> bool:
        vv = norm_label(value)
        return any(vv == norm_label(v) for v in variants)

    found: Dict[str, Optional[str]] = {k: None for k in schema.keys()}

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
        for row in tbl:
            if not row:
                continue
            cells = [norm(c) for c in row if c is not None]
            if len(cells) < 1:
                continue

            first = norm(cells[0])
            if first.lower() in {"item", "field", "parameter"}:
                continue

            # label = primera no vacía; value = última no vacía
            label_cell = next((c for c in cells if c), None)
            value_cell = next((c for c in reversed(cells) if c), None)

            # Si solo hay label o el "valor" es idéntico al label, descartar
            if not label_cell or not value_cell:
                continue

            for col_name, spec in schema.items():
                if found[col_name] is not None:
                    continue

                if label_matches(label_cell, spec["variants"]):
                    # Evitar que el valor sea el propio label o cualquiera de sus alias
                    if norm_label(value_cell) == norm_label(label_cell):
                        continue
                    if same_as_any_variant(value_cell, spec["variants"]):
                        continue

                    val = norm(value_cell)
                    if not is_nullish(val) and VALIDATORS[spec["type"]](val):
                        found[col_name] = val
    return found

# ================================
# Extracción por LÍNEAS (fallback)
# ================================
def value_after_label_by_lines(lines: List[str], label: str) -> Optional[str]:
    """
    Busca 'Label ... valor' en una sola línea (con cualquier separación).
    El valor se validará por tipo antes de aceptarse.
    """
    pat = r"^\s*" + re.escape(label) + r"\b[:\s]*(.+)$"
    for ln in lines:
        m = re.match(pat, ln, flags=re.IGNORECASE)
        if m:
            return norm(m.group(1))
    return None

def extract_from_lines(page, schema=FIELD_SCHEMA) -> Dict[str, Optional[str]]:
    def same_as_any_variant(value: str, variants: List[str]) -> bool:
        vv = norm_label(value)
        return any(vv == norm_label(v) for v in variants)

    found: Dict[str, Optional[str]] = {k: None for k in schema.keys()}
    text = page.extract_text() or ""
    lines = [norm(ln) for ln in text.splitlines() if ln.strip()]

    for col_name, spec in schema.items():
        if found[col_name] is not None:
            continue
        for v in spec["variants"]:
            val = value_after_label_by_lines(lines, v)
            if not val:
                continue
            # Evitar que el valor sea el propio label o alguno de sus alias
            if norm_label(val) == norm_label(v):
                continue
            if same_as_any_variant(val, spec["variants"]):
                continue
            if not VALIDATORS[spec["type"]](val):
                continue
            found[col_name] = val
            break
    return found

# ================================
# Master extractor por PDF
# ================================
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
                # 2) Luego líneas
                line_vals = extract_from_lines(page, schema)
                for k, v in line_vals.items():
                    if v and result[k] is None:
                        result[k] = v

                # Cortar si ya tenemos todos
                if all(result[k] is not None for k in schema.keys()):
                    break
    except Exception as e:
        # Dejar rastro si no se pudo abrir/parsing (visible en el Excel)
        result["Component ID"] = f"ERROR: {e}"
    return result

# ================================
# MAIN
# ================================
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

    # --- Limpieza final: si el valor quedó igual a la etiqueta o alias, -> null ---
    def _key(s: str) -> str:
        if s is None:
            return ""
        # normaliza: quita ":"/espacios finales, minúsculas
        return re.sub(r"[:\s]+$", "", str(s)).strip().lower()

    NULL_TOKENS = {"no value to display", "n/a", "na", "-", "--", "null"}

    for col, spec in FIELD_SCHEMA.items():
        if col not in df.columns:
            continue

        # Etiquetas prohibidas (columna + sus alias)
        bad_keys = {_key(col)} | {_key(v) for v in spec["variants"]}

        # 1) valor == etiqueta/alias (normalizado) -> null
        mask_same_as_label = df[col].notna() & df[col].astype(str).map(_key).isin(bad_keys)
        df.loc[mask_same_as_label, col] = pd.NA

        # 2) tokens comunes de "sin valor" -> null
        mask_null_tokens = df[col].notna() & df[col].astype(str).str.strip().str.lower().isin(NULL_TOKENS)
        df.loc[mask_null_tokens, col] = pd.NA

    # Exportar Excel con formato
    with pd.ExcelWriter(OUTPUT_XLSX, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="extract")
        ws = writer.sheets["extract"]
        ws.freeze_panes(1, 0)
        for i, col in enumerate(df.columns):
            try:
                width = max(15, min(50, df[col].astype(str).map(len).max() + 2))
            except Exception:
                width = 20
            ws.set_column(i, i, width)

    print(f"✅ Archivo generado: {OUTPUT_XLSX}")

if __name__ == "__main__":
    main()
