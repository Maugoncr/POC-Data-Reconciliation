# PDF Data Reconciliation

Script en **Python** para extraer 11 campos desde múltiples PDFs (normalmente en tablas) y consolidarlos en un **Excel** con una fila por PDF.

---

## 🚀 Características

- Escanea todos los PDFs en `project/data/input_pdfs/`.
- Intenta primero extraer desde **tablas**; si no las encuentra, usa un **fallback por líneas**.
- Valida cada campo por **tipo de dato** (fecha, dígitos, texto, etc.) para evitar falsos positivos  
  (por ejemplo, que *Component ID* no capture *Assignment*).
- Exporta a `project/data/output/pdf_extract.xlsx`.
- Alias y tipos por campo se controlan en un solo diccionario (`FIELD_SCHEMA`).

---

## 📦 Requisitos

- **Python 3.11** (recomendado)
- Librerías (instalable con `requirements.txt`):
  - `pdfplumber`
  - `pandas`
  - `openpyxl`
  - `XlsxWriter`

### `requirements.txt` sugerido

pdfplumber>=0.11
pandas>=2.0
openpyxl>=3.1
XlsxWriter>=3.1

---

## 🗂️ Estructura de carpetas

data-reconciliation/
├─ README.md
├─ .gitignore
├─ extract.py
├─ requirements.txt
└─ project/
└─ data/
├─ input_pdfs/ # aquí pegas los PDFs
└─ output/ # aquí se genera el Excel


> Este repositorio puede incluir archivos vacíos (por ejemplo `.gitkeep`) para que Git rastree `input_pdfs/` y `output/` aunque estén vacías.

---

## ⚙️ Instalación y uso

### 1) Crear entorno virtual e instalar dependencias (Windows PowerShell/CMD)

```bash
cd path\to\data-reconciliation
py -m venv .venv
.\.venv\Scripts\activate
py -m pip install --upgrade pip
pip install -r requirements.txt

Copia tus archivos .pdf dentro de: project/data/input_pdfs/

Ejecuta el script: python extract.py