# Repository tooling entry points

Current developer setup: [SETUP](../docs/developer/SETUP.md). The0008 fictional fixture is `python -m scripts.repro_demo` (plan first); release/privacy preparation is `python -m scripts.repository_release`. Run offline tooling checks with `python -m unittest scripts.test_repository_hardening -v`.

Older seed/configure/verify_slice scripts are preserved historical tooling. They can use obsolete APIs, private machine paths or destructive proof databases; do not use them against the active human-testing environment. No C03 audit or final regression is authorized by this index.

The technical audit pack below is private evidence packaging, not a public-source/privacy clearance tool. Use the explicit source export for later portfolio preparation.

---

# Audit Packaging Script

Run from the repository root:

```bash
python scripts/build_audit_package.py
```

Optional:

```bash
python scripts/build_audit_package.py --label Slice2
python scripts/build_audit_package.py --output-dir audit_packages
```

The script:
- reads Git commit/status;
- packages tracked repository files plus current control/evidence documents;
- excludes common secret/cache/local-environment paths;
- creates SHA-256 manifest entries;
- writes provenance metadata;
- creates a ZIP.

The script does NOT:
- run tests;
- claim tests passed;
- invent PostgreSQL evidence;
- decide the audit verdict.

Run tests separately and store/log actual evidence before packaging.
