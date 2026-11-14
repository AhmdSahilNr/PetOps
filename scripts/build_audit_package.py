#!/usr/bin/env python3
"""
PetOps deterministic audit package builder.

This script packages existing evidence. It intentionally DOES NOT run tests or
invent results.

Recommended use:
    1. Run the intended tests manually/through the builder.
    2. Save actual logs/evidence in the repository's approved evidence location.
    3. Freeze/commit the review candidate.
    4. Run this script.
    5. Give the ZIP to an independent reviewer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


EXCLUDED_PARTS = {
    ".local", "private", "participants", "participant_data", "uat_private",
    "case_organisation_private", "consent_forms", "release_staging",
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    "node_modules",
    ".idea",
    ".vscode",
    "pgdata",
    "postgres-data",
    "postgres_data",
    "dist",
    "build",
}

EXCLUDED_FILENAMES = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    ".DS_Store",
}

EXCLUDED_SUFFIXES = {
    ".dump", ".backup", ".sql.gz",
    ".pem", ".key", ".p12", ".pfx",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".log.tmp",
}

SENSITIVE_NAME_FRAGMENTS = {
    "secret",
    "password",
    "private_key",
    "credentials",
    "token_dump",
}

DEFAULT_INCLUDE_UNTRACKED_PREFIXES = (

)


def run_git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout.strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_rel(rel: str) -> bool:
    p = PurePosixPath(rel.replace("\\", "/"))
    parts_lower = {part.lower() for part in p.parts}
    name_lower = p.name.lower()

    if '..' in p.parts or p.is_absolute():
        return False
    if name_lower.startswith('.env') and name_lower != '.env.example':
        return False
    if name_lower in {'.pgpass', 'pgpass.conf'}:
        return False

    if any(part.lower() in EXCLUDED_PARTS for part in p.parts):
        return False
    if name_lower in {x.lower() for x in EXCLUDED_FILENAMES}:
        return False
    if any(name_lower.endswith(sfx.lower()) for sfx in EXCLUDED_SUFFIXES):
        return False
    if any(fragment in name_lower for fragment in SENSITIVE_NAME_FRAGMENTS):
        return False

    # Keep safe templates.
    if name_lower == ".env.example":
        return True

    return True


def collect_files(repo: Path) -> list[str]:
    tracked = run_git(repo, "ls-files").splitlines()
    selected = {p for p in tracked if p and safe_rel(p)}

    # Permit current workflow/control documents to be packaged even if the user
    # has not committed them yet. This does not make them commit-bound; provenance
    # records the repository status so the reviewer can see that.
    for prefix in DEFAULT_INCLUDE_UNTRACKED_PREFIXES:
        base = repo / prefix
        if base.exists():
            for path in base.rglob("*"):
                if path.is_file():
                    rel = path.relative_to(repo).as_posix()
                    if safe_rel(rel):
                        selected.add(rel)

    for filename in ():
        p = repo / filename
        if p.is_file() and safe_rel(filename):
            selected.add(filename)

    return sorted(selected)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".", help="Repository root (default: .)")
    parser.add_argument("--label", default="Review", help="Review package label")
    parser.add_argument(
        "--output-dir",
        default=".local/audit_packages",
        help="Output directory relative to repo unless absolute",
    )
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        print("ERROR: repository root must contain .git", file=sys.stderr)
        return 2

    try:
        commit = run_git(repo, "rev-parse", "HEAD")
        short = run_git(repo, "rev-parse", "--short=12", "HEAD")
        tree = run_git(repo, "rev-parse", "HEAD^{tree}")
        branch = run_git(repo, "branch", "--show-current", check=False) or "(detached)"
        status = run_git(repo, "status", "--porcelain=v1", check=False)
        commit_subject = run_git(repo, "log", "-1", "--pretty=%s", check=False)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = repo / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_label = "".join(c for c in args.label if c.isalnum() or c in "-_") or "Gate"
    zip_name = f"PetOps_{safe_label}_Audit_{short}_{timestamp}.zip"
    zip_path = output_dir / zip_name

    files = collect_files(repo)
    manifest = []
    missing = []

    for rel in files:
        path = repo / rel
        if not path.is_file():
            missing.append(rel)
            continue
        manifest.append(
            {
                "path": rel,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    provenance = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "label": args.label,
        "git": {
            "commit": commit,
            "short_commit": short,
            "tree": tree,
            "branch": branch,
            "commit_subject": commit_subject,
            "worktree_clean": not bool(status.strip()),
            "status_porcelain": status.splitlines() if status else [],
        },
        "important_note": (
            "This package records repository/evidence state. It does not prove that "
            "tests, migrations, PostgreSQL operations, or application runs succeeded "
            "unless actual evidence files inside the package demonstrate that."
        ),
        "missing_files": missing,
    }

    manifest_json = json.dumps(
        {
            "provenance": provenance,
            "files": manifest,
        },
        indent=2,
        sort_keys=True,
    ).encode("utf-8")

    readme = f"""PetOps Audit Package

Label: {args.label}
Commit: {commit}
Tree: {tree}
Branch: {branch}
Worktree clean at packaging: {not bool(status.strip())}

IMPORTANT:
- Verify MANIFEST.json hashes.
- Review actual test/runtime evidence; do not infer PASS from packaging.
- If worktree_clean is false, distinguish commit-bound files from uncommitted state.
- Independent reviewer should not modify the implementation being approved.
"""

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for item in manifest:
            rel = item["path"]
            z.write(repo / rel, arcname=f"repository/{rel}")
        z.writestr("MANIFEST.json", manifest_json)
        z.writestr("AUDIT_PACKAGE_README.txt", readme.encode("utf-8"))

    package_hash = sha256_file(zip_path)

    summary = {
        "package": str(zip_path),
        "sha256": package_hash,
        "commit": commit,
        "tree": tree,
        "worktree_clean": not bool(status.strip()),
        "file_count": len(manifest),
    }

    summary_path = zip_path.with_suffix(".json")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
