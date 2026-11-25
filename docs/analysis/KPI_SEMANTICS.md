# Today and Insights: what the numbers mean

All dates use Malaysia time. Each count and its drill-down list come from **one server definition**, so a tile can't disagree with the list behind it.

## Today (Admin operations centre)

| Tile / section | Definition |
|---|---|
| Needs decision | Requested bookings, each with readiness flags: needs groomer, needs accommodation, ready to confirm, date passed, changed request |
| Grooming today | Grooming appointments today |
| Arrivals today | Confirmed Boarding stays starting today |
| Departures due | Staying pets planned to check out today or earlier |
| In care now | Pets currently staying, out of configured places |
| Coming up | Tomorrow to 7 days ahead, excluding requested and cancelled bookings |
| Staff work | Open responsibility per Staff member, now and in the next 7 days |

## Insights (selected period)

Since the 25 November 2026 corrections, Insights is a simplified period review: four main tiles, a booking-requests trend, completed services by service type, and a **More detail** section. Current occupancy and team workload are no longer repeated here. They are shown on Today (In care now, Staff work), on the lodging board and on the Staff work page. The reporting definitions and drill-down records are unchanged.

| Measure | Where | Definition | Limitation |
|---|---|---|---|
| Booking requests | Tile and trend chart | Bookings **created** in the period | Not service dates or demand forecasts |
| Completed services | Tile, and completed services by service type | Grooming/Boarding **completion times** in the period | Not revenue |
| Decision rate | Tile | Confirmations ÷ (confirmations + rejections) in the period; "—" when there were none | A reconfirmed booking can add another decision |
| Cancellations | Tile | Recorded cancellation **events** in the period | Not satisfaction or churn |
| Confirmations, rejections, date changes | More detail | Recorded decision and change **events** in the period | As above |

- **Periods:** presets or custom, up to 731 days.
- **Trends:** zero-filled by day, week or month.
- **Comparison:** with the previous period of the same length. A percentage is shown only when the earlier value is 10 or more.

Source: [operations.py](../../app/operations.py), [dashboard.py](../../app/dashboard.py) (`/admin/insights/records` returns exactly the counted records), [admin/insights.js](../../app/static/js/admin/insights.js), tests in [test_revamp_2026_11_18.py](../../tests/test_revamp_2026_11_18.py) and [test_final_candidate.py](../../tests/test_final_candidate.py).

Screenshots use fictional data. These definitions describe the system's reporting; they are not business results.
