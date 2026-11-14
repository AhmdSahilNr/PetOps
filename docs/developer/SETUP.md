# Run a local developer copy

Use a new developer copy and new local databases. Never run setup, fixture reset or application tests against a database collecting human observations.

## Dependencies

The recorded environment used Python 3.12.14 and PostgreSQL 18.6. A fresh installation on another machine has not yet been verified. PostgreSQL needs the `btree_gist` extension. Node 20 or later is needed only for the built-in JavaScript test harnesses; no npm packages or frontend build step are required.

From the repository root in PowerShell:

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pip check
```

On a POSIX shell, use `python3.12` and `.venv/bin/python`. The requirements file includes an exact lock of the executed environment, including development/test dependencies.

## Create separate PostgreSQL databases

Start your own loopback PostgreSQL server. The example uses port 5432; use the port of your installation. In `psql`, as your local administrator:

```sql
CREATE ROLE petops_dev LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
\password petops_dev
CREATE DATABASE petops_repro_demo_test OWNER petops_dev;
CREATE DATABASE petops_regression_test OWNER petops_dev;
```

Enter a new local password interactively. These must be newly created databases. Do not rename or reuse a retained database to pass a name guard. The first database belongs exclusively to the managed fictional fixture; the second is for destructive application test fixtures.

This local owner setup permits migrations/extensions. It is not a production least-privilege deployment recipe. If extension installation is restricted by your PostgreSQL installation, have its local administrator install `btree_gist` in the new database.

## Private environment configuration

The application reads `PETOPS_DATABASE_URL`; environment variables override an optional root `.env` file. Copy `.env.example` only as a starting template and replace its placeholders privately. Never commit real database URLs, passwords or runtime configuration. URI-encode reserved characters in a URL password.

For the managed fixture, supply `PETOPS_REPRO_DATABASE_URL` explicitly. Its required shape is shown below with a placeholder password; this is not a working credential:

```text
postgresql+psycopg://petops_dev:REPLACE_ME@127.0.0.1:5432/petops_repro_demo_test
```

One way to enter your real local URL without putting it into shell history:

```powershell
$privateUrl = Read-Host 'Dedicated developer database URL' -AsSecureString
$env:PETOPS_REPRO_DATABASE_URL = [System.Net.NetworkCredential]::new('', $privateUrl).Password
Remove-Variable privateUrl
$env:PETOPS_DATABASE_URL = $env:PETOPS_REPRO_DATABASE_URL
$env:PETOPS_REMINDER_POLL_SECONDS = '0'
```

Keep the same terminal for the following commands. Do not print the environment variable or paste it into screenshots/logs. The fixture CLI requires the process environment variable; it does not load this setting from `.env` by itself.

## Migrations

Confirm that the resolved URL names your newly created developer database before proceeding:

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m alembic current
```

Current head is `0008`. Alembic reads the application setting, so editing `sqlalchemy.url` in `alembic.ini` alone does not select the target. Both the application and ini file retain old development placeholder URLs: always override them. Preserve migrations `0001`–`0008`, associated SQL and the revision template. Some migrations are intentionally forward-only; do not use downgrades as a fixture reset mechanism.

## Fictional data and startup

Follow the [fictional demo guide](../../demo/README.md) to inspect the plan and explicitly populate the empty developer database. Then:

```powershell
$env:PETOPS_DATABASE_URL = $env:PETOPS_REPRO_DATABASE_URL
$env:PETOPS_REMINDER_POLL_SECONDS = '0'
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 58120
```

Open `http://127.0.0.1:58120` and use the [fictional accounts](../../demo/README.md). Choose another free port if needed; do not stop an existing human-testing process to obtain it. Polling `0` disables the technical reminder sweep for this developer demonstration. Admin reminder lead settings and normal reminder behavior remain existing application features.

## Tests

Offline tooling checks avoid the application database fixtures:

```powershell
.venv/Scripts/python.exe -m unittest scripts.test_repository_hardening -v
node tests/ui_races.mjs
node tests/ui_product.mjs
```

Application pytest fixtures migrate and clear the selected database. Set `PETOPS_TEST_DATABASE_URL` privately to the separate `petops_regression_test` database before any later authorized application run, and verify the target. Never select a demo or human-testing database, even if its name ends in `_test`. Install Node on `PATH` or set `PETOPS_NODE` to its executable. The [testing guide](../testing/README.md) records the historical selection and remaining verification; this setup guide does not claim a final regression result.

## Common setup issues

An unset URL selects the legacy development fallback. A wrong port/role prevents connection; missing extension/DDL privileges prevents migration; missing Node prevents JavaScript harness integration. A past fixture anchor date prevents new bookings. Resolve configuration on the new developer target rather than altering business guards or editing booking history directly. Production deployment and secure-cookie configuration are outside this local guide.
