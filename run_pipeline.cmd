@echo off
cd /d "%~dp0"
python -m src.run_all --sample > run_sample.out 2> run_sample.err
