# Release identity: PetOps FYP1 final frozen build (18 November 2026)

## Two repositories, one product

The product was developed and audited in a **private development repository**. There the final technical freeze is:

- commit `ca485b0455dc8bf97aaab0c3b6ef44c05ff27619`;
- tree `1bb32610a2553d93922682b227b100bc8f4a7e0f`;
- tag `petops-fyp1-final-frozen-2026-11-18`;
- migration head `0008`.

This **public repository** keeps its own curated history. Its source files are byte-identical copies of that frozen commit's `app/`, `tests/`, `alembic/` and `scripts/` folders. Documentation, screenshots and licence files here are curated for public reading.

The private development history holds internal evidence and project-control records, and is deliberately not published.

## How to check the source identity

[`testing/source-manifest.json`](testing/source-manifest.json) lists every file with its SHA-256. The combined fingerprint is `1fd06edf1788176a09d9c3d93c3a28413a55a006f53f6210652fd14087048e70` over **146 files**. It is defined as follows:

- take the files under `app/`, `tests/`, `alembic/` and `scripts/` (excluding `__pycache__`), in that folder order, each folder sorted by path;
- hash each file, and write one line `path:sha256` per file, ending with a newline;
- take the SHA-256 of all those lines joined together.

Recompute it on a Windows checkout (this repository uses `.gitattributes`). The files in this public repository's tag must reproduce the same value.

## Verification of the frozen build

All results below were produced in the private repository against disposable local PostgreSQL databases. None of these runs was repeated in this public repository.

| Check | Result |
|---|---|
| Full automated regression, PostgreSQL 18.6 | 433 passed, 0 failed, 4 subtests passed, 1 pre-existing dependency warning, exit 0 |
| Browser end-to-end workflows | 13 / 13 passed |
| Independent technical review | Passed with conditions: 1 medium and 1 low finding, no blocker or high finding. The medium finding (a legacy Staff read route used an older access rule) was corrected and re-reviewed: **condition closed, pass** |

The freeze rule: implementation reopens only for genuine defects, security or integrity issues, incorrect business rules or serious workflow defects. Each reopening is re-verified before a new freeze.

## History

Earlier public commits describe earlier frozen candidates (15 November 2026, 394 tests). They are kept unchanged as history and are **not current**.
