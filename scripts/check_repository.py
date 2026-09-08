"""Check staged source files before publishing (no third-party dependencies)."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
MAX_SIZE = 5 * 1024 * 1024
BLOCKED = {'.exe', '.msi', '.dll', '.tar', '.tgz', '.gz', '.zip', '.7z',
           '.rar', '.sql', '.pem', '.key', '.p12', '.pfx', '.pyc'}
SECRET = re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|'
                    rb'gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|'
                    rb'AKIA[0-9A-Z]{16}')

def main():
    paths = subprocess.check_output(
        ['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0')
    errors = []
    count = total = 0
    for name in filter(None, paths):
        path = Path(name)
        data = subprocess.check_output(['git', 'show', ':' + name], cwd=ROOT)
        count += 1
        total += len(data)
        if (path.suffix.lower() in BLOCKED or
                (path.name.startswith('.env') and not path.name.endswith('.example')) or
                any(p in {'.venv', 'build', 'dist', 'transfer-package', '__pycache__',
                          'generated', 'certs'}
                    for p in path.parts)):
            errors.append(f'{name}: excluded artifact or local configuration')
        if len(data) > MAX_SIZE:
            errors.append(f'{name}: larger than 5 MiB')
        if b'\0' in data:
            errors.append(f'{name}: binary content')
        if SECRET.search(data):
            errors.append(f'{name}: possible credential (value suppressed)')
    for error in errors:
        print(error)
    print(f'Checked {count} staged files, {total:,} bytes; {len(errors)} errors.')
    return bool(errors)

if __name__ == '__main__':
    sys.exit(main())
