import os

root = r'C:\Users\User\Downloads\dedup-system-splink'

# Show all top-level non-essential files
print("Top-level files (non-dir):")
all_files = sorted([f for f in os.listdir(root) if os.path.isfile(os.path.join(root, f))])
for f in all_files:
    print(f"  - {f}")

print(f"\nTotal: {len(all_files)} files")