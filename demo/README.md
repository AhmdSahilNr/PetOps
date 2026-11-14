# Reproducible fictional developer fixture

Use only petops_repro_demo_test, a separately created loopback PostgreSQL database. It must never be used for human sessions. No current runtime is selected automatically. The CLI does not start/stop servers, create databases or touch main/demo/UAT targets.

```powershell
# Plan: no database connection or write.
.venv/Scripts/python.exe -m scripts.repro_demo --anchor-date YYYY-MM-DD
# Set PETOPS_REPRO_DATABASE_URL privately, then explicitly apply to the new empty DB.
.venv/Scripts/python.exe -m scripts.repro_demo --anchor-date YYYY-MM-DD --apply
# Later, reset ONLY this fixture-owned developer database:
.venv/Scripts/python.exe -m scripts.repro_demo --anchor-date YYYY-MM-DD --reset --apply
```

Choose the actual MYT date or a future anchor; past dates are refused. Same anchor yields the same named configuration, service order, relative schedules and semantic states. UUIDs, salted password hashes and recorded event/session timestamps are deliberately not identical. This is deterministic fixture content, not byte-identical history.

Accounts admin.repro@petops.example, staff.repro@petops.example and customer.repro@petops.example use public fictional password DemoPass!123. No personal/organisation data is used. Three pets and services support a Requested Grooming, Confirmed Grooming and Confirmed Boarding booking. Staff timing is derived by existing handlers, with no generic availability rows. Completed-care facts are not invented; perform a later developer walkthrough through the normal UI if needed and label it honestly.

The tool bootstraps one fixed-ID fictional Admin, then uses the application's normal API handlers for business setup. It records a developer database comment as an ownership marker (not an application table/schema change). Reset requires the exact database name, loopback address, marker, bootstrap identity and only known fixture account emails. A partial fixture can be retried with reset if those ownership checks hold. Unexpected accounts/markers stop the reset. Back up anything needed before explicitly resetting this disposable fixture; it is not a preservation mechanism.


For environment configuration and startup, follow the [setup guide](../docs/developer/SETUP.md). Replace YYYY-MM-DD with the current or a future Malaysia date.
