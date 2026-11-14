# Known limitations

- The recorded 82-test result is historical targeted PostgreSQL verification, not a final full regression. Test files also contain cases outside that selection.
- Human usability testing is underway; participant results and final acceptance are not included.
- Fresh-machine dependency installation and platforms other than the recorded local environment remain unverified. The existing environment used Python 3.12.14 and PostgreSQL 18.6.
- The developer owner/database recipe is not a production least-privilege deployment. Runtime grants, deployment configuration and production operations need separate verification.
- The application and Alembic configuration retain legacy placeholder database URLs. Always supply an explicit private environment URL; do not reuse the defaults for retained data.
- Application pytest fixtures clear their selected database. The loopback/`_test` check does not distinguish a human-testing database that also happens to have that suffix. Select a newly created, separate test database deliberately.
- Legacy availability structures and some bounded compatibility APIs remain. General availability records no longer control Staff eligibility.
- Migrated old responsibility records preserve only the last saved period; absent historical actor/name information stays unknown. No earlier handover is reconstructed.
- Responsibility periods are planned accountability, not attendance or continuous-care evidence. Boarding handover is bounded to now/future within the planned stay.
- Edit preflight checks are not a complete atomic conditional-edit protocol.
- Screenshot counts/dates reflect fictional data at capture time, not current operating totals or a usability result.
- A historical dependency warning concerns FastAPI/Starlette TestClient's use of `httpx`. Dependencies were not upgraded during active usability testing.

These are documented limits, not new requirements or an independent acceptance verdict.
