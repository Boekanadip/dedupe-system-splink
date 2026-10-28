import os

root = r'C:\Users\User\Downloads\dedup-system-splink'
_py_files = sorted([f for f in os.listdir(root) if f.startswith('_') and f.endswith('.py')])

# Find all Python files recursively
all_py = []
for dirpath, dirnames, filenames in os.walk(root):
    # Skip .venv and .git
    dirnames[:] = [d for d in dirnames if d not in ('.venv', '.git')]
    for f in filenames:
        if f.endswith('.py'):
            all_py.append(os.path.join(dirpath, f))

# For each _*.py file, check if any other .py file imports it
print(f"Checking usage of {len(_py_files)} _*.py files across all .py files...\n")

for _f in _py_files:
    mod_name = _f.replace('.py', '')
    used_by = []
    for pth in all_py:
        if pth.endswith(_f):
            continue  # skip self
        try:
            with open(pth, 'r', errors='ignore') as fh:
                content = fh.read()
            patterns = [f'from {mod_name}', f'import {mod_name}', f'from .{mod_name}', f'import .{mod_name}']
            for pat in patterns:
                if pat in content:
                    used_by.append(os.path.relpath(pth, root))
                    break
        except:
            pass
    if used_by:
        print(f"  USED: {_f}")
        for u in used_by:
            print(f"      -> {u}")
    else:
        print(f"  UNUSED: {_f}")