# Testing and verification

## Recorded results (final frozen build, 18 November 2026)

These runs were executed in the private development repository on the frozen source. That source is byte-identical to this repository's `app/`, `tests/`, `alembic/` and `scripts/`; see the [release identity](../RELEASE.md).

| Execution | Result |
|---|---|
| Full regression: `pytest tests scripts/test_repository_hardening.py` on PostgreSQL 18.6, Python 3.12.14, disposable database | **433 passed, 0 failed**, 0 errors, 0 skipped; 4 nested subtests passed; 1 pre-existing Starlette/httpx deprecation warning; exit 0 |
| Browser end-to-end (13 scripted journeys through the real interface, all three roles) | **13 / 13 passed** |
| Frontend harness `node tests/ui_revamp.mjs all` | 19 check groups passed |
| Repository checks `python -m unittest scripts.test_repository_hardening` | 7 passed |

The 433 tests break down by area:

| Area | Tests |
|---|---:|
| Accounts and core booking | 10 |
| Security and integrity hardening (anonymous rejection, role matrix, Customer isolation, sessions, registration) | 84 |
| Grooming availability and Staff assignment (incl. concurrent requests on PostgreSQL) | 58 |
| Grooming fulfilment | 46 |
| Boarding operations | 55 |
| Notifications, reminders and Admin management | 70 |
| Responsibility and handover rules | 26 |
| Final integration and reporting | 44 |
| Final interface views and Customer data minimisation | 31 |
| Legacy Staff read scope after independent review | 2 |
| Repository safeguards | 7 |

The 13 end-to-end journeys:

1. Customer books Grooming.
2. Admin assigns and confirms in one action.
3. Staff starts and completes Grooming.
4. Customer sees the result, notes, notifications and history.
5. Admin reassigns, and the timeline records it.
6. The former Staff member's link is refused and their notifications are redacted.
7. The new Staff member sees the work.
8. Customer reschedules (back to Requested), then cancels.
9. Boarding is confirmed with accommodation and a Staff member.
10. Staff checks in, adds a stay update and checks out.
11. Customer sees the stay update.
12. Today and Insights tiles equal their drill-down lists.
13. Direct API access is refused: another Customer's booking returns 404, and Customer and Staff are refused on Admin endpoints.

**What these results do and don't show:** they show the tested behaviour works on the frozen source with a real PostgreSQL database. They do **not** show usability, human acceptance, production readiness, security certification or business benefit.

An independent technical review passed the build after one medium finding was corrected. The legacy `/staff/bookings/{id}` route now uses the same responsibility read rule as the main routes.

## Run the checks yourself

**Offline, no database needed:**

```powershell
python -m unittest scripts.test_repository_hardening -v
node tests/ui_revamp.mjs all
```

**Full suite:**

1. Create your own **new, empty** local PostgreSQL database, for example `petops_portfolio_regression_test`. Check its owner and purpose; the name ending `_test` proves nothing.
2. In your own terminal, set both `PETOPS_TEST_DATABASE_URL` and `PETOPS_DATABASE_URL` to that database, and set `PETOPS_REMINDER_POLL_SECONDS=0`. Do this privately: never commit or paste the URL.
3. The test fixtures migrate the database and **TRUNCATE** its business tables, so never point them at a database whose data you need.
4. Make sure Node.js is on `PATH`, or set `PETOPS_NODE` to it.

```powershell
python -m pytest tests scripts/test_repository_hardening.py --collect-only -q
python -m pytest tests scripts/test_repository_hardening.py -q
```

The `scripts/check_*.cjs` and `scripts/audit_ui_content.cjs` files are **legacy** browser checks written for the interface before the 18 November redesign. They are kept unchanged because they are part of the frozen source identity, but they are not part of the current verification. They also contain the original developer machine's local tool paths. The current frontend checks are `tests/ui_revamp.mjs`.

SQLite is not a substitute: PostgreSQL constraints, triggers and concurrency behaviour are part of what is tested. A fresh install on a new machine has not been verified. See [setup](../developer/SETUP.md) and [limitations](LIMITATIONS.md).
