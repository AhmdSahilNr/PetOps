# Testing and verification

Frozen application e174d81ed2b170928d070c12dd59adba57bba6a3; test-only checkpoint50b1935216f4d569bf56aeec938c84be47ad9fb0; source documentation f86bc9cae069db5e2932da5188afaf6b210f1a77;0008. Curated portfolio history is distinct. [Source manifest](source-manifest.json) records exact77-file combined fingerprint including tests. Runtime source, all migrations and current tests are byte-identical to that frozen baseline; portfolio documentation is a sanitized derivative.

| Recorded execution | Collected/run | Passed | Failed | Exit | Pytest seconds |
|---|---:|---:|---:|---:|---:|
| Initial full suite |394|392|2|1|855.36|
| Corrected setup retest |8|8|0|0|24.23|
| Final complete rerun |394|394|0|0|898.40|

Each had1 retained Starlette/httpx dependency warning and0 errors/skips/xfails/xpasses. Four nested tooling subtests in full runs are not extra collected cases.394 includes387 tests/ cases (some frontend/guard checks) and7 offline repository checks. Separate21 JavaScript checks overlap two Python harness integrations and are not added to394. The recorded run used a verified separate disposable PostgreSQL18.6 database and Python3.12.14.

The first failed setup wrote an assignment without the0008 responsibility/history required by constraints. The second supplied manual initial Boarding periods although approved rules derive them from the stay. Setup-only corrections retained invalid-role denial/rollback and allocation-history/403 expectations. Product guards were not relaxed. Original failed logs, exact patch, retest and final raw evidence are retained privately rather than republished with local paths or academic material.

Independent C03: PASS WITH CONDITIONS; no blocking implementation defect/current MUST gap or code rework/additional broad regression. C03 inspected source/evidence, independently collected394 cases and executed7 offline tests and21 JS checks; it did not provision another PostgreSQL rerun. Conditions concerned actual Git identity, package preservation, addendum authority and claim bounds; subsequent control verification satisfied them. Controller freeze is recorded in the supplied closure authorization. Neither result certifies production/security or broad usability.

## Reproducing checks

Offline, without application database fixtures:

```powershell
python -m unittest scripts.test_repository_hardening -v
node tests/ui_races.mjs
node tests/ui_product.mjs
node tests/ui_refinement.mjs
node tests/ui_insights.mjs
```

For application pytest, first create and verify your own NEW disposable loopback PostgreSQL database ending `_test`, such as petops_portfolio_regression_test. Check exact database/server/owner/purpose and ensure it holds no retained records. `_test` alone proves nothing. Privately set BOTH PETOPS_TEST_DATABASE_URL and PETOPS_DATABASE_URL to that target; set PETOPS_REMINDER_POLL_SECONDS=0. The fixtures migrate and TRUNCATE business rows. Never point them at demo/UAT data. Node must be on PATH or set PETOPS_NODE.

```powershell
python -m pytest tests scripts/test_repository_hardening.py --collect-only -q
python -m pytest tests scripts/test_repository_hardening.py -vv --tb=short
```

SQLite fallback is not PostgreSQL constraint/concurrency proof. No fresh-machine install or new broad regression is claimed for portfolio preparation. [Setup](../developer/SETUP.md) · [Limits](LIMITATIONS.md).
