# Release identity: PetOps FYP1 corrected frozen build (25 November 2026)

## Two repositories, one product

The product was developed and audited in a **private development repository**. After the FYP1 poster and prototype presentation, the supervisor directed five corrections. These were implemented, independently reviewed and accepted. The current technical freeze there is:

- tag `petops-fyp1-corrected-frozen-2026-11-25` (commit `00724defc4776332f62b800abd9472ba2da74edd`);
- product source last changed in commit `ca3089fcfaa9f4307fc2a047a6421556066972bc` (tree `de8ec669103ec5769bc036140b32e3df284dd100`);
- migration head `0008` (no schema change in the corrections).

This **public repository** keeps its own curated history. Its source files are byte-identical copies of that product commit's `app/`, `tests/`, `alembic/` and `scripts/` folders. Documentation, screenshots and licence files here are curated for public reading.

The private development history holds internal evidence and project-control records, and is deliberately not published.

## What the corrections changed

- **Passwords:**
  - Admin sets a Staff member's password only when creating the account and can no longer change an existing Staff password.
  - Staff change their own password from their Profile (`PUT /account/password`): the current password is verified, the new password is validated and hashed, and the Staff member's other sessions are signed out.
- **Admin Insights:** simplified to four period measures, a requests trend, completed services by type, and a "More detail" section. Current occupancy and team workload stay on Today and Staff work.
- **Readability:** small interface text was enlarged, and the lodging board's night columns were widened.

**Unchanged:** booking workflows, business rules, the database schema and all other routes.

## How to check the source identity

[`testing/source-manifest.json`](testing/source-manifest.json) lists every file with its SHA-256. The combined fingerprint is `9f48bce69bfc7fbbd6b3e49e152f9cfb45d01f6e4dd539b57f632ace6770b33a` over **147 files**. It is defined as follows:

- take the files under `app/`, `tests/`, `alembic/` and `scripts/` (excluding `__pycache__`), in that folder order, each folder sorted by path;
- hash each file, and write one line `path:sha256` per file, ending with a newline;
- take the SHA-256 of all those lines joined together.

Recompute it on a Windows checkout (this repository uses `.gitattributes`). The files in this public repository must reproduce the same value.

## Verification of the corrected build

All results below were produced in the private repository against disposable local PostgreSQL databases. None of these runs was repeated in this public repository.

| Check | Result |
|---|---|
| Full automated regression, PostgreSQL 18.6 | 446 passed, 0 failed, 4 subtests passed, 1 pre-existing dependency warning, exit 0 |
| Browser end-to-end workflows | 13 / 13 passed |
| Staff password browser checks | 7 / 7 passed |
| Responsive captures (1440, 1280, 820 and 375 px) | 133 screens, no horizontal overflow or error messages |
| Independent technical review | Passed with conditions. Both conditions concerned evidence handling, not product behaviour: redaction of disposable test-session tokens in private logs, and execution-record provenance. After they were closed, the result was **pass**, accepted on 25 November 2026 |

**Execution provenance:**
- The regression and browser runs were made by the developer on the source immediately before it was committed as `ca3089f`.
- The link between the runs and that commit rests on file timestamps and server records, not on an identifier captured during each run.
- The reviewer examined the evidence; this record does not claim the reviewer re-ran the tests.

## History

- **18 November 2026:** the build presented at the FYP1 poster session.
  - Private commit `ca485b0`, tag `petops-fyp1-final-frozen-2026-11-18`; 146 files, fingerprint `1fd06edf1788176a09d9c3d93c3a28413a55a006f53f6210652fd14087048e70`; 433 tests passed.
  - It remains in this repository's history and is **not current**.
- **15 November 2026:** the earlier candidate (394 tests). It is also kept as history.
