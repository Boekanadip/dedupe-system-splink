import os
from pathlib import Path

ROOT = Path(r"C:\Users\User\Downloads\dedup-system-splink")
SRC = ROOT / "src"

# Files to keep (essential project files)
KEEP_FILES = {
    # Essential config and code
    "config", "data", "src", "outputs", "models", "docs", "pages", "tests",
    
    # Documentation
    "AGENTS.md", "DESIGN.md", "MASTER_CONTEXT.md.txt", "PRD.md", "README.md",
    
    # Data files
    "review_sample.csv", "review_sample_band.csv", "CATATAN_20261014.md",
    "BACKEND_HANDOFF.md", "PANDUAN.md",
    
    # Scripts yang sudah rapi
    "scripts",
}

# Files to move to scripts (non-essential utilities)
SCRIPT_FILES = [
    "analyze_errors.py", "analyze_fn.py", "analyze_fn2.py",
    "check_clutter.py", "check_dist.py", "check_imports.py",
    "check_jaro.py", "check_model.py", "check_phone.py",
    "check_usage.py", "cleanup_check.py", "compare_thresholds.py",
    "debug_fn.py", "debug_fn2.py", "evaluate_test.py",
    "eval_new.py", "eval_proper.py", "eval_thresholds.py",
    "final_eval.py", "fix_colmap.py", "gen_report.py",
    "identify_fn.py", "review_sample.py", "test_split.py",
    "verify_results.py",
]

# Files to delete (temporary/debug files)
DELETE_FILES = [
    "app.py", "app.py.bak", "body.json",
    "blocking_output.txt", "eval_output.txt",
    "FINAL_EVAL_REPORT.md", "threshold_output.txt",
    "threshold_output_v2.txt", "pytest_out.txt",
    "docker-entrypoint.sh", "Dockerfile", "docker-compose.yml",
    ".dockerignore", ".env", ".env.example",
    "requirements.txt", "setup.ps1",
]

# Move SCRIPT_FILES to scripts folder
for fname in SCRIPT_FILES:
    src = ROOT / fname
    dst = SRC / fname
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        print(f"Moved: {fname} -> src/")

# Delete DELETE_FILES
for fname in DELETE_FILES:
    path = ROOT / fname
    if path.exists():
        if path.is_file():
            path.unlink()
            print(f"Deleted: {fname}")
        elif path.is_dir():
            import shutil
            shutil.rmtree(path)
            print(f"Deleted dir: {fname}")

# Clean __pycache__
pycache = ROOT / "__pycache__"
if pycache.exists():
    import shutil
    shutil.rmtree(pycache)
    print("Deleted: __pycache__/")

print("\n=== Cleaned ===")