#!/usr/bin/env python3
"""Verify system components"""

import sys
import os
sys.path.insert(0, 'src')

def main():
    print("Verifying system components...")
    
    # Check key files and directories
    checks = []
    
    # Check data directories
    data_dirs = ['data/raw', 'data/processed', 'data/labels', 'data/synthetic']
    for dir_path in data_dirs:
        full_path = os.path.join(os.path.dirname(__file__), dir_path)
        exists = os.path.exists(full_path)
        checks.append((dir_path, exists))
        print(f"  {dir_path}: {'✓' if exists else '✗'}")
    
    # Check output directories
    output_dirs = ['outputs', 'outputs/models', 'outputs/staging']
    for dir_path in output_dirs:
        full_path = os.path.join(os.path.dirname(__file__), dir_path)
        exists = os.path.exists(full_path)
        checks.append((dir_path, exists))
        print(f"  {dir_path}: {'✓' if exists else '✗'}")
    
    # Check key files
    key_files = [
        'outputs/master_customers.parquet',
        'outputs/entity_map.parquet',
        'outputs/incremental_history.jsonl',
        'outputs/gold_scored.parquet'
    ]
    
    for file_path in key_files:
        full_path = os.path.join(os.path.dirname(__file__), file_path)
        exists = os.path.exists(full_path)
        checks.append((file_path, exists))
        print(f"  {file_path}: {'✓' if exists else '✗'}")
    
    # Check if we can import key modules
    try:
        import src.config
        import src.standardize
        import src.splink_model
        checks.append(('module_import', True))
        print("  modules: ✓")
    except Exception as e:
        checks.append(('module_import', False))
        print(f"  modules: ✗ ({e})")
    
    # Summary
    passed = sum(1 for _, exists in checks if exists)
    total = len(checks)
    print(f"\n{passed}/{total} checks passed")
    
    if passed == total:
        print("✅ System verification PASSED")
        return 0
    else:
        print("❌ System verification FAILED")
        return 1

if __name__ == "__main__":
    sys.exit(main())