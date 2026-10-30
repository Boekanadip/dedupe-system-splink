#!/usr/bin/env python3
"""Simple test to verify system components"""

import sys
import os
sys.path.insert(0, 'src')

def test_basic_components():
    """Test basic system components"""
    print("Testing basic system components...")
    
    # Import key modules
    try:
        from config import PROCESSED_DATA_PATH, ENTITY_MAP_PATH
        from src.model_lifecycle import latest
        from src.splink_model import load_data
        
        print(f"PROCESSED_DATA_PATH exists: {PROCESSED_DATA_PATH.exists()}")
        print(f"ENTITY_MAP_PATH exists: {ENTITY_MAP_PATH.exists()}")
        
        # Check if we can load data
        if ENTITY_MAP_PATH.exists():
            df = load_data()
            print(f"Successfully loaded data with {len(df)} rows")
            print(f"Entity IDs: {df['entity_id'].nunique()}")
            return True
        else:
            print("Entity map not found - need to run pipeline")
            return False
            
    except Exception as e:
        print(f"Error importing modules: {e}")
        return False

def test_pipeline_steps():
    """Test core pipeline steps"""
    print("\nTesting pipeline steps...")
    
    try:
        # Test standardization
        from src.standardize import standardize
        from src.profiling import load_raw
        from pathlib import Path
        
        # Check if raw data exists
        raw_dir = Path('data/raw')
        raw_files = list(raw_dir.glob('*.csv'))
        print(f"Raw CSV files found: {len(raw_files)}")
        
        if raw_files:
            # Test basic standardization function
            print("Standardization module imported successfully")
            
        # Test config
        from config import BENCHMARK_RULES
        print(f"Loaded {len(BENCHMARK_RULES)} blocking rules")
        
        return True
        
    except Exception as e:
        print(f"Error in pipeline test: {e}")
        return False

if __name__ == "__main__":
    success1 = test_basic_components()
    success2 = test_pipeline_steps()
    
    if success1 and success2:
        print("\n✅ System components test PASSED")
        sys.exit(0)
    else:
        print("\n❌ System components test FAILED")
        sys.exit(1)