"""Local hygiene inventory and curated source export; never pushes or certifies privacy."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {'.py', '.js', '.mjs', '.css', '.html', '.md', '.txt', '.json', '.csv', '.sql', '.ini', '.example', '.yml', '.yaml'}
PRIVATE_PARTS = {'.git', '.local', '.venv', 'private', 'participants', 'participant_data', 'uat_private', 'case_organisation_private', 'consent_forms'}
PUBLIC_DOCS = {'README.md', 'docs/developer/SETUP.md', 'docs/developer/DEMO.md', 'docs/repository/PUBLIC_README_SKELETON.md', 'docs/repository/RELEASE_POLICY.md'}
PUBLIC_SCRIPTS = {'scripts/repro_demo.py', 'scripts/repository_release.py', 'scripts/test_repository_hardening.py', 'scripts/build_audit_package.py'}
ROOT_FILES = {'README.md', '.gitignore', '.gitattributes', '.env.example', 'alembic.ini', 'requirements.txt', 'requirements.lock.txt'}
PATTERNS = {
    'private_key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'service_token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[A-Z0-9]{16})\b'),
    'database_password_url': re.compile(r'postgres(?:ql)?(?:\+\w+)?://[^\s:/]+:([^\s@]+)@', re.I),
    'non_fixture_email': re.compile(r'[A-Za-z0-9_.+-]+@(?!(?:[\w.-]+\.)?(?:petops\.example|example\.(?:com|org|net))\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}'),
}

def forbidden_path(name):
    p = Path(name.replace('\\', '/'))
    lower = {part.lower() for part in p.parts}
    base = p.name.lower()
    return (p.is_absolute() or '..' in p.parts or bool(lower & PRIVATE_PARTS)
            or (base.startswith('.env') and base != '.env.example')
            or base in {'.pgpass', 'pgpass.conf'}
            or base.endswith(('.db', '.sqlite', '.sqlite3', '.dump', '.backup', '.pem', '.key', '.p12', '.pfx', '.log'))
            or base.startswith(('credentials.', 'secrets.')))

def public_path(name):
    if forbidden_path(name): return False
    return name in ROOT_FILES | PUBLIC_DOCS | PUBLIC_SCRIPTS or (name.startswith(('app/', 'alembic/', 'tests/')) and Path(name).suffix in TEXT_SUFFIXES)

def findings(data):
    try: text = data.decode('utf-8')
    except UnicodeDecodeError: return ['binary_requires_manual_review']
    result = []
    for kind, pattern in PATTERNS.items():
        hits = list(pattern.finditer(text))
        if kind == 'database_password_url':
            hits = [m for m in hits if m.group(1) not in {'CHANGE_ME', 'petops', 'password', 'REPLACE_ME', 'offline', 'placeholder', 'p'}]
        if hits: result.append(kind)
    return result

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)

def inventory(history=False):
    names = git('ls-files', '-z').decode().split('\0')[:-1]
    rows = []
    for name in names:
        kinds = findings((ROOT / name).read_bytes())
        if forbidden_path(name): kinds.append('forbidden_tracked_path')
        if kinds: rows.append({'path': name, 'review_categories': sorted(set(kinds))})
    result = {'head': git('rev-parse', 'HEAD').decode().strip(), 'tracked_files': len(names),
              'findings': rows, 'scope': 'Tracked working files; matching values never emitted',
              'limits': 'Heuristics are not a complete secret/privacy audit. Ignored/untracked files are not read. Fictional fixture passwords and legacy placeholder defaults are not real-secret evidence.'}
    if history:
        objects = {}
        for line in git('rev-list', '--objects', '--all').decode().splitlines():
            oid, _, name = line.partition(' ')
            if name: objects.setdefault(oid, name)
        history_rows = []
        for oid, name in objects.items():
            if git('cat-file', '-t', oid).strip() != b'blob': continue
            size = int(git('cat-file', '-s', oid))
            kinds = ['large_object_requires_manual_review'] if size > 2_000_000 else findings(git('cat-file', 'blob', oid))
            if forbidden_path(name): kinds.append('forbidden_historical_path')
            if kinds: history_rows.append({'object': oid, 'path_hint': name, 'review_categories': sorted(set(kinds))})
        result['history_findings'] = history_rows
        result['history_objects_considered'] = len(objects)
    return result

def export(destination):
    destination = destination.resolve()
    staging = (ROOT / '.local' / 'release_staging').resolve()
    if staging not in destination.parents or destination.exists():
        raise ValueError('Use a new output file inside .local/release_staging')
    names = sorted(n for n in git('ls-files', '--cached', '--others', '--exclude-standard', '-z').decode().split('\0') if n and public_path(n))
    def source(name):
        p = ROOT / ('docs/repository/PUBLIC_README_SKELETON.md' if name == 'README.md' else name)
        if p.is_symlink() or ROOT not in p.resolve().parents:
            raise ValueError('Export refuses symlinks or paths outside the repository')
        return p
    blocking = []
    for name in names:
        kinds = findings(source(name).read_bytes())
        if set(kinds) & {'private_key', 'service_token', 'database_password_url'}: blocking.append(name)
    if blocking: raise ValueError('Export refused: secret-pattern candidates require review (run inventory)')
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = {'source_head': git('rev-parse', 'HEAD').decode().strip(), 'worktree_clean': not bool(git('status', '--porcelain').strip()),
                'publication_approved': False, 'policy': 'Explicit source/docs allowlist; no .git, historical evidence, study/case documents, screenshots or runtime data',
                'readme_source': 'docs/repository/PUBLIC_README_SKELETON.md',
                'files': [{'path': n, 'sha256': hashlib.sha256(source(n).read_bytes()).hexdigest()} for n in names]}
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in names: z.write(source(name), name)
        z.writestr('EXPORT_MANIFEST.json', json.dumps(manifest, indent=2))
    with zipfile.ZipFile(destination) as z:
        assert z.testzip() is None
        for row in manifest['files']: assert hashlib.sha256(z.read(row['path'])).hexdigest() == row['sha256']
    return {'file_count': len(names), 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(), 'publication_approved': False}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inventory', 'export'])
    parser.add_argument('--history', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'inventory':
        result = inventory(args.history)
        # The inventory itself is private; do not write matching values anywhere.
        target = args.output.resolve()
        if (ROOT / '.local').resolve() not in target.parents: parser.error('Inventory output must be inside ignored .local')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps({'tracked_files': result['tracked_files'], 'review_files': len(result['findings']), 'history_review_objects': len(result.get('history_findings', []))}))
    else: print(json.dumps(export(args.output)))

if __name__ == '__main__': main()
