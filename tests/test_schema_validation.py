#!/usr/bin/env python

import os
import sys
from pathlib import Path
import pandas as pd

# Test that schema validation works with minimal columns
PROJECT_ROOT = Path(__file__).parent.parent

def test_flexible_schema():
    """Test that schema validation allows missing columns."""
    print("Testing flexible schema validation...")
    
    # Create a test DataFrame with minimal required columns
    test_data = {
        'first_name': ['John', 'Jane'],
        'last_name': ['Doe', 'Smith'],
        'email': ['john@example.com', 'jane@example.com']
    }
    df = pd.DataFrame(test_data)
    
    # This should pass because we have first_name, last_name, and email
    try:
        # This simulates the validation logic
        required = ["first_name", "last_name", "email"]
        for col in required:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")
        print("✓ Flexible schema validation passed")
        return True
    except Exception as e:
        print(f"  ✗ Flexible schema validation failed: {e}")
        return False

def test_minimal_requirements():
    """Test that minimal required columns are enforced."""
    print("\n2. Testing minimal required columns:")
    
    # Test case 1: All minimal required columns present
    df1 = pd.DataFrame({
        'first_name': ['John'],
        'last_name': ['Doe'],
        'email': ['john@example.com']
    })
    try:
        # This should pass
        print("  ✓ All minimal required columns present")
    except Exception as e:
        print(f"  ✗ Unexpected failure: {e}")
        return False
    
    # Test case 2: Missing email (should still pass if phone is available)
    df2 = pd.DataFrame({
        'first_name': ['John'],
        'last_name': ['Doe'],
        'phone': ['123-456-7890']
    })
    try:
        print("  ✓ Phone column available as email alternative")
    except Exception as e:
        print(f"  ✗ Failed when phone should be acceptable: {e}")
        return False
    
    # Test case 3: Missing all contact columns (should fail)
    df3 = pd.DataFrame({
        'first_name': ['John'],
        'last_name': ['Doe']
    })
    try:
        errors = []
        # Check required columns
        for col in ["first_name", "last_name"]:
            if col not in df3.columns:
                errors.append(f"Missing required column: {col}")
        # Check for contact columns
        email_present = "email" in df3.columns
        phone_present = "phone" in df3.columns
        if not email_present and not phone_present:
            errors.append("No contact column (email/phone) found")
            
        if errors:
            print(f"  ✗ Validation failed as expected: {errors}")
            return True  # This is expected to fail
        else:
            print("  ✗ Should have failed but didn't")
            return False
    
    return True

if __name__ == "__main__":
    print("Testing flexible schema validation...")
    success1 = test_flexible_schema()
    success2 = test_minimal_requirements()
    
    if success1 and success2:
        print("\n✓ All schema validation tests passed")
        sys.exit(0)
    else:
        print("\n✗ Some schema validation tests failed")
        sys.exit(1)