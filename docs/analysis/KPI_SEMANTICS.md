# Operational Insights: interpreting the numbers

| Measure | Meaning / time basis | Limitation |
|---|---|---|
| Requests | Bookings created in selected MYT period; type/current status breakdown refers to that cohort | Not demand forecasting or all service dates |
| Confirmation rate | Confirmation decision events divided by confirmation+rejection decision events in period | Reconfirmed booking can contribute another event; no decisions gives unavailable rate |
| Completions | Actual Grooming/Boarding completion timestamps in period | Not planned service dates or revenue |
| Cancellations/reschedules | Recorded change events in period | Not customer satisfaction or unique-customer churn |
| Physical capacity | Current open Boarding stays against current configured capacity | Not historical utilisation or future bookability |
| Assigned work | Open unreleased responsibility overlapping period, active Staff only; bookings counted | Not worked hours, attendance, external availability or performance |

Selected period, current physical snapshots and fixed next-seven-day arrivals/departures have distinct labels/bases. Volume buckets reconcile with creation cohorts; empty periods do not invent trend points. Fixture data has a current seed-time bucket, not fabricated history. Read [dashboard.py](../../app/dashboard.py), [overview.js](../../app/static/overview.js) and [final-candidate tests](../../tests/test_final_candidate.py). This is a sanitized explanation of approved captured-data reporting, not new requirements.
