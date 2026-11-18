"""Provision fictional local databases in the dedicated project-owned cluster.

Requires initdb/pg_ctl first (README). Passwords stay in ignored .local/.env.
Never points at a remote host or changes an existing database/role.
"""
import json
from pathlib import Path
import secrets

import psycopg
from psycopg import sql
from sqlalchemy import URL

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local'


def main():
    config_path = LOCAL / 'postgres-config.json'
    if config_path.exists():
        raise SystemExit('Local configuration already exists; reuse it. No records changed.')
    passwords = {name: secrets.token_urlsafe(32) for name in ('petops_migrator','petops_runtime')}
    with psycopg.connect(host='127.0.0.1', port=55432, user='petops_local_admin',
                          password=(LOCAL/'pgpassword').read_text().strip(), dbname='postgres', autocommit=True) as conn:
        for name,password in passwords.items():
            conn.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE').format(sql.Identifier(name),sql.Literal(password)))
        for name in ('petops_demo','petops_hardening_test','petops_upgrade_test'):
            conn.execute(sql.SQL('CREATE DATABASE {} OWNER petops_migrator').format(sql.Identifier(name)))
    def url(user, database):
        return URL.create('postgresql+psycopg', username=user,password=passwords[user],host='127.0.0.1',port=55432,database=database).render_as_string(hide_password=False)
    config = {'migration_url':url('petops_migrator','petops_demo'),
              'runtime_url':url('petops_runtime','petops_demo'),
              'test_url':url('petops_migrator','petops_hardening_test'),
              'upgrade_url':url('petops_migrator','petops_upgrade_test')}
    config_path.write_text(json.dumps(config,indent=2),encoding='utf-8')
    env_path = ROOT / '.env'
    if not env_path.exists():
        env_path.write_text(f"PETOPS_DATABASE_URL={config['runtime_url']}\nPETOPS_ENV=development\n",encoding='utf-8')
    print('Created loopback-only demo/test/upgrade databases and separate non-superuser migration/runtime roles. Secrets saved only in ignored local files.')


if __name__ == '__main__':
    main()
