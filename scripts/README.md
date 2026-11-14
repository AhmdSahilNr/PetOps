# Developer tools

| Tool | Purpose |
|---|---|
| `python -m scripts.repro_demo --anchor-date YYYY-MM-DD` | Print the fictional fixture plan without connecting to a database; see the [demo guide](../demo/README.md) for explicitly applying/resetting its dedicated developer database |
| `python -m unittest scripts.test_repository_hardening -v` | Seven offline checks for target guards, exclusions and fixture planning |
| `python -m scripts.repository_release inventory --history --output .local/review.json` | Redacted heuristic review of tracked files and reachable history; not a privacy certification |
| `python -m scripts.repository_release export --output .local/release_staging/review.zip` | Explicitly allowlisted review ZIP with source HEAD and hashes; never pushes or approves publication |
| `python scripts/build_audit_package.py --output-dir .local/audit_packages` | Package tracked technical evidence with provenance; does not run tests or award acceptance |

Source/export tooling requires Git on `PATH`. Inventories, archives, runtime logs and private configuration belong in ignored `.local`, not in hosted source. The application pytest fixtures are separate and destructive to their selected database.
