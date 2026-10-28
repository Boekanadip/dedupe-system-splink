import os

root = r'C:\Users\User\Downloads\dedup-system-splink'
_py_files = sorted([f for f in os.listdir(root) if f.startswith('_') and f.endswith('.py')])
print(f"_*.py files in root: {len(_py_files)}")
for f in _py_files:
    print(f"  - {f}")

# Check which are imported by src/*.py
src_dir = os.path.join(root, 'src')
used_in_src = set()
for sf in os.listdir(src_dir):
    if not sf.endswith('.py'):
        continue
    full = os.path.join(src_dir, sf)
    try:
        with open(full, 'r', errors='ignore') as fh:
            content = fh.read()
        for _f in _py_files:
            mod_name = _f.replace('.py', '')
            import_patterns = [
                f'from {mod_name}',
                f'import {mod_name}',
                f'from .{mod_name}',
                f'import .{mod_name}',
            ]
            for pat in import_patterns:
                if pat in content:
                    used_in_src.add(_f)
                    break
    except:
        pass

print(f"\nFiles used in src/: {len(used_in_src)}")
for f in sorted(used_in_src):
    print(f"  - {f} <- used in src")

all_set = set(_py_files)
unused = all_set - used_in_src
print(f"\nFiles NOT used in src/ (potential clutter): {len(unused)}")
for f in sorted(unused):
    print(f"  - {f}")