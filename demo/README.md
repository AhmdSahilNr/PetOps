# Recruiter demonstration — 3–5 minutes

Prepare your own local environment using [setup](../docs/developer/SETUP.md) before the walkthrough. All identities/records below are fictional. No public live deployment is claimed.

## Prepare the story

From the repository root with dependencies installed and your new empty `petops_final_candidate_demo_test` explicitly configured:

```powershell
# Plan only: no database connection or writes.
python -m scripts.final_demo --anchor-date YYYY-MM-DD
# Explicitly apply only to your own new empty target.
python -m scripts.final_demo --anchor-date YYYY-MM-DD --apply
```

Replace YYYY-MM-DD with **today's Malaysia date** for apply. The helper requires `PETOPS_FINAL_DEMO_DATABASE_URL`, validates the exact loopback database/ownership, applies existing0001–0008 migrations, marks its fixture and uses supported handlers to create17 bookings/8 fictional users/8 pets. First apply requires empty schema; do not manually pre-migrate it. It does not create the database or start a server. Unexpected existing schema/marker/accounts are refused. Applying takes longer than the plan because operations are genuine handler calls and Grooming reaches its scheduled time before starting.

The story includes requested/confirmed/staying/completed/cancelled/rejected records, responsibilities, events, care notes and operational summaries. UUIDs, salted hashes, sessions and actual timestamps vary; semantic content repeats for a valid anchor. Care is an accelerated fictional walkthrough, not proof of real elapsed service. All events are created now, so do not present the seeded chart as historical demand.

Start Uvicorn and confirm0008 using [setup](../docs/developer/SETUP.md). These public fictional credentials exist **only after explicit fixture apply**; never reuse them for real users or expose an internet service with them.

| Role | Email | Password |
|---|---|---|
| Customer | `nadia.zainal@petops.example` | `DemoPass!123` |
| Staff | `daniel.tan@petops.example` | `DemoPass!123` |
| Admin | `farah.ismail@petops.example` | `DemoPass!123` |

The helper also creates Staff Aisyah Rahman/Amir Hakim and Customers Mei Ling/Arif Hakim/Maya Krishnan; their exact reserved emails are in [final_demo.py](../scripts/final_demo.py), with the same fictional password. Keep login fields out of screenshots.

## Walkthrough

| Time | Show / explain |
|---|---|
|0:00–0:30|Business problem: connected booking, capacity, responsibility and service history rather than scattered reservations/remarks.|
|0:30–1:10|Customer Home → Book a service (Type, Pet, Service, Date and time, Review). Explain that the time is a request until Admin confirms. Don't create an extra request unless you are deliberately demonstrating on your own disposable fixture.|
|1:10–1:50|Admin Today → Needs decision → open a request → review checklist → choose a groomer, or accommodation plus optional Staff → one Confirm action (or reject). Eligibility is PetOps workload and capacity, not attendance.|
|1:50–2:30|Staff My work → one next action per job → open a Boarding job (stay progress, stay updates, responsibility). A scheduled future assignee can view the job but can't act early.|
|2:30–3:10|Boarding lodging board and booking history. Explain Check in → Staying → Check out → Completed, the handover record, and the Overdue stay label (display only). Don't fake elapsed care.|
|3:10–4:00|Admin Insights: selected period compared with the previous one; requests by creation date, decision rate, completions, current occupancy, team workload. Each tile opens its records.|
|4:00–4:30|Verification: 433/0 PostgreSQL regression, 13/13 end-to-end, and the independent review that passed after one corrected finding. State the limits: no human evaluation of this interface, no production or security certification.|

Use separate browser sessions if showing roles side by side, or log out before changing roles. Counts change if you perform real actions; never claim a stale screenshot is a live query. Older fixture dates need deliberate regeneration of your own disposable fixture for a later day.

## Reset and recovery

Only on your own explicitly disposable exact fixture:

```powershell
python -m scripts.final_demo --anchor-date YYYY-MM-DD --reset --apply
```

Reset additionally requires the fixture marker, bootstrap Admin identity and known fictional account set. It truncates only that target's business rows and rebuilds through normal handlers, retaining migrations. It is not backup/recovery certification. Never reset a maintainer/participant/organisation database or one containing records you need. A partial owned fixture can be inspected and retried only if these guards hold; unexpected accounts or ownership require investigation, not forced cleanup.

If startup fails, check the setup troubleshooting table and environment before changing anything. The small older `repro_demo` fixture remains as legacy tooling/test source but is not this gallery's17-booking story; do not mix its credentials/URLs into this guide. This preparation task ran plan/offline checks only; it did not reseed a retained runtime.
