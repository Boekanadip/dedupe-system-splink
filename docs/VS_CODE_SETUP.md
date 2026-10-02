# VS Code Setup — Windows

## Recommended environment
Use Python 3.12 for this PoC even though current Splink 4.0.17 supports Python >=3.10,<4.0. The point is reproducibility, not using the newest interpreter.

## 1. Check installed Python versions
PowerShell:

```powershell
py -0p
python --version
```

If Python 3.12 is not installed, install it from python.org or your preferred package manager, then verify:

```powershell
py -3.12 --version
```

Do not uninstall your other Python versions just for this project.

## 2. Open the project

```powershell
cd "C:\Users\ASUS\Documents\Maganghub 2026\Bulan 1\Sistem Duplikasi"
code .
```

Replace the path with the actual folder.

## 3. Create the project virtual environment

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation, run the current terminal's command-policy fix only for the user scope or activate through the VS Code Python interpreter picker instead of changing system-wide policies.

## 4. VS Code extensions
Install:
- Python (Microsoft)
- Jupyter (Microsoft)
- Pylance (Microsoft)

VS Code supports Python environments and native `.ipynb` notebooks through these extensions. See the official Python/Jupyter documentation.

## 5. Select interpreter
Command Palette:

`Python: Select Interpreter`

Choose:

`.venv\Scripts\python.exe`

Then create/open a notebook and select the same `.venv` kernel.

## 6. Verify

```powershell
python -c "import pandas, duckdb, splink; print('pandas', pandas.__version__); print('duckdb', duckdb.__version__); print('splink', splink.__version__)"
```

Then:

```powershell
python -m src.profiling
```

## 7. Put the dataset here

```text
data/
└── raw/
    └── crm_50000_customers_dirty_v3.csv
```

If your filename/path differs, change only `RAW_DATA_PATH` in `src/config.py`.

## 8. Important first adaptation
Before running standardization, open `src/config.py` and check `COLUMN_MAP` against the real CSV header.

If, for example, your file has:

```text
phone
```

instead of:

```text
phone_number
```

change only:

```python
"phone": "phone"
```

Do not rename the raw file just to make the code work.

## 9. OpenCode project instructions
From the project root run OpenCode and use `/init` only if you want OpenCode to inspect the project. The starter already contains a hand-written `AGENTS.md`; keep it as the authoritative project rule file.

Project skills are under:

```text
.opencode/skills/
```

Current skills:
- `dedup-workflow`
- `data-profiling`
- `blocking-benchmark`
- `splink-model`
