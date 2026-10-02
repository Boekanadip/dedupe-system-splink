$ErrorActionPreference = "Stop"

Write-Host "Checking Python 3.12..."
py -3.12 --version

Write-Host "Creating virtual environment..."
py -3.12 -m venv .venv

Write-Host "Installing packages..."
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host "Verifying imports..."
.\.venv\Scripts\python.exe -c "import pandas, duckdb, splink; print('pandas', pandas.__version__); print('duckdb', duckdb.__version__); print('splink', splink.__version__)"

Write-Host "Setup complete. In VS Code select .venv\Scripts\python.exe as the interpreter."
