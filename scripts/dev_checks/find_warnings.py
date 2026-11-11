import os

for root, dirs, files in os.walk('pages'):
    dirs[:] = [d for d in dirs if not d.startswith('.')]
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                    content = fh.read()
                    if 'bukti kuat' in content.lower():
                        print(f'FOUND in {path}')
                        for i, line in enumerate(content.split('\n'), 1):
                            if 'bukti kuat' in line.lower():
                                print(f'  Line {i}: {line[:200]}')
            except:
                pass

# Also check 5_queue.py and 7_gaps.py for record sources
for path in ['pages/5_queue.py', 'pages/7_gaps.py', 'pages/1_review.py']:
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            content = fh.read()
            print(f'\n=== {path} ===')
            # Find enqueue function and queue sources
            for i, line in enumerate(content.split('\n'), 1):
                if 'enqueue' in line.lower():
                    print(f'  Line {i}: {line[:200]}')
            # Find QUEUE_PATH references
            if 'QUEUE_PATH' in content:
                for i, line in enumerate(content.split('\n'), 1):
                    if 'QUEUE_PATH' in line:
                        print(f'  Line {i} (QUEUE): {line[:200]}')
    except:
        pass