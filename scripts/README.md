# Developer tools

- `python -m scripts.final_demo --anchor-date YYYY-MM-DD`: plan only; [demo](../demo/README.md) explains guarded apply/reset for its exact owned database.
- `python -m unittest scripts.test_repository_hardening -v`: seven offline checks; no application DB fixture.
- `python -m scripts.repository_release inventory --history --output .local/review.json`: redacted heuristic inventory, not privacy certification.

Legacy repository_release export and build_audit_package utilities are retained byte-identical as dependencies of the existing tooling tests. The former uses an academic-era allowlist/README path and is not the exporter for this curated portfolio: it may omit gallery/docs or refuse the absent old README source. Do not use either as a public-release command. Packaging for this review is prepared outside hosted source with explicit file/hash validation. No frozen helper behaviour was changed to hide that inconsistency.

Secrets, runtime files, generated archives and inventories belong outside hosted source or in ignored.local. Application pytest is destructive to its explicitly selected database; see [testing](../docs/testing/README.md).
