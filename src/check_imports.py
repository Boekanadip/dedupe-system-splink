import os

root = r'C:\Users\User\Downloads\dedup-system-splink'

# Check what final_eval.py references
with open(os.path.join(root, 'final_eval.py'), 'r') as f:
    content = f.read()
print("final_eval.py imports/refs:")
for line in content.split('\n'):
    if line.strip().startswith(('from ', 'import ')):
        print(f"  {line.strip()}")

print()

# Check what src/splink_model.py imports
src_path = os.path.join(root, 'src', 'splink_model.py')
with open(src_path, 'r') as f:
    content = f.read()
print("splink_model.py imports:")
for line in content.split('\n'):
    if line.strip().startswith(('from ', 'import ')):
        print(f"  {line.strip()}")