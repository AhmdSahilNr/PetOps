# Run a local copy

Use your own new local PostgreSQL databases. These instructions are for an isolated developer demonstration, not production deployment or a fresh-machine certification. Do not point them at retained participant, organisation or maintainer databases. A filename ending `_test` is not evidence that a database is disposable.

## Install dependencies

The recorded environment was Python3.12.14 and PostgreSQL18.6. The lock pins the executed Python packages, including test dependencies. Node20+ is required for existing JS harnesses; no npm install or frontend build is needed. PostgreSQL must support `btree_gist`.

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pip check
```

For POSIX use `python3.12`, `.venv/bin/python` and the equivalent environment-variable syntax. This guide does not claim those platforms were freshly installed/tested. All following Python commands assume the virtual environment is activated, or replace `python` with its executable.

## Create your own empty targets

On your own loopback PostgreSQL installation, connect using `psql` as its administrator. The example uses port5432; use your actual local port.

```sql
CREATE ROLE petops_dev LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
\password petops_dev
CREATE DATABASE petops_final_candidate_demo_test OWNER petops_dev;
CREATE DATABASE petops_portfolio_regression_test OWNER petops_dev;
```

Enter a new password privately. If either database already exists, stop and establish its owner/purpose; do not drop or repurpose it. The frozen final-demo helper requires that exact demo database name. If it is already in use for retained records, use a separate new local PostgreSQL instance rather than changing the helper's guards. This task did not create, reset or seed any database.

The developer owner needs local migration/extension privileges. If `btree_gist` installation is denied, ask the local PostgreSQL administrator to install it in the NEW targets. This is not production least-privilege configuration; production grants, including `staff_responsibilities`, need separate review.

## Configure privately

From the repository root, activate the venv and enter the dedicated demo URL privately in the same PowerShell terminal:

```powershell
.venv/Scripts/Activate.ps1
$demoSecret = Read-Host 'Your NEW local final-demo database URL' -AsSecureString
$env:PETOPS_FINAL_DEMO_DATABASE_URL = [System.Net.NetworkCredential]::new('', $demoSecret).Password
Remove-Variable demoSecret
$env:PETOPS_DATABASE_URL = $env:PETOPS_FINAL_DEMO_DATABASE_URL
$env:PETOPS_REMINDER_POLL_SECONDS = '0'
```

URL shape, with a placeholder rather than working credentials:

```text
postgresql+psycopg://petops_dev:REPLACE_ME@127.0.0.1:5432/petops_final_candidate_demo_test
```

URI-encode reserved password characters. Never print/store the actual URL in Git, screenshots or transcripts. Optional `.env` is ignored; `.env.example` is only a placeholder. Environment values override `.env`. The frozen application and `alembic.ini` retain old development fallback URLs: explicit configuration is required. The demo helper reads its dedicated process environment variable, not that setting from `.env`.

Before setup, confirm the target using `psql`/your DB client: `SELECT current_database(), current_user, inet_server_addr(), inet_server_port();`. Confirm owner/purpose, loopback server and an empty public schema. Do not use the maintainer's existing demo/UAT server merely because its name matches this example.

## Migrations and fictional data

For the professional fixture, follow [demo instructions](../../demo/README.md). **First apply must start from an empty database:** the guarded helper applies unchanged Alembic migrations0001–0008 and creates its own fixture marker. Do not manually run migrations first on an unowned final-demo target; that makes the helper correctly refuse it.

For another NEW non-fixture developer/test database, privately select it with `PETOPS_DATABASE_URL`, then existing migration commands are:

```powershell
python -m alembic upgrade head
python -m alembic current
```

Head is0008. Alembic reads the application URL; editing only `sqlalchemy.url` does not select a target. Preserve all revisions/SQL; some upgrades are forward-only. Never use downgrade/deleting migration history as a reset method. Pytest applies migrations itself to its separately verified disposable database.

## Start the application

After fictional setup and checking `SELECT version_num FROM alembic_version` returns0008:

```powershell
$env:PETOPS_DATABASE_URL = $env:PETOPS_FINAL_DEMO_DATABASE_URL
$env:PETOPS_REMINDER_POLL_SECONDS = '0'
python -m uvicorn app.main:app --host 127.0.0.1 --port 58120
```

Open `http://127.0.0.1:58120`. Choose an unused port instead of stopping another process. Ctrl+C stops your foreground server. The client is served by this application; do not open index.html directly as a file. Polling0 keeps reminders manual for this demonstration; normal polling/Admin lead settings remain supported behaviour. Production cookie/proxy/TLS configuration is outside this guide.

## Tests and troubleshooting

[Testing](../testing/README.md) gives offline and full-suite commands. Application tests migrate/TRUNCATE their explicitly chosen disposable target; never use the demo URL for them. Set both test/app URLs privately to the new separate regression target before running pytest.

| Symptom | Check |
|---|---|
| Connection refused/login to DB fails | Local PostgreSQL running, correct port/role/password/URL encoding; no fallback URL selected |
| Missing extension or permission denied | `btree_gist` and migration privileges on your new database |
| Demo rejects existing schema/marker/accounts | Stop; inspect exact target and ownership. Reset only the known disposable fixture as documented |
| Plan dates rejected on apply | Use today's Malaysia date; no fake clock or historical apply |
| Browser will not load | Uvicorn startup output, correct active venv/root/URL and unused port |
| JS checks fail to launch | Node on PATH or `PETOPS_NODE` points to it |

Do not fix setup by editing business guards, raw booking states/history or disabling authorization. Keep runtime logs/local configuration private. A new reader's install remains unverified until actually performed.
