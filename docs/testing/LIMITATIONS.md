# Known limitations (final frozen build)

These are real limits of the FYP1 build. They are not hidden defects, and they are not work in progress.

## Evidence limits

- **Local academic prototype:** run on a local machine with fictional data. There is no production deployment, hosting, backup/recovery exercise or support process.
- **No certification:** no security certification, least-privilege production review, formal accessibility certification, broad cross-browser or zoom certification, or verified fresh-machine install.
- **Human evaluation:**
  - There was no human user-acceptance testing of the final 18 November redesigned interface.
  - Earlier qualitative feedback (on a previous version) is descriptive only, with no participant counts, scores or task timings.
- **Fictional figures:** Insights and Today figures in the screenshots come from fictional data. They are not business results.

## Functional limits

- Notifications are **in-system only**; there is no email, SMS or WhatsApp.
- There is **no active Grooming handover** once work has started; reassignment happens before work starts only.
- An **occupied Boarding unit cannot be transferred** to another unit during a stay.
- There is **no opening-hours model**, so the system does not suggest Grooming time slots; the Customer's preferred time is a request until Admin confirms it.
- There is **no leave, attendance or shift model**. Staff eligibility is an active account with no overlapping responsibility, and responsibility periods record accountability, not attendance.
- Insights shows **current occupancy only**; past occupancy is not reconstructed.
- **Overdue stay** is a display label only: there is no fee, extension or automatic check-out. Its positive case is tested at rule level, because a past-dated open stay can't be created through the API.
- **Exceptional overrides** after work has started (for example correcting a completed record) need business rules that were not approved, so they are not implemented.
- Stay updates and groomer notes are **visible to the Customer**; there is no separate internal-notes field.
- **Legacy compatibility:** old CHECKED_IN/CHECKED_OUT statuses remain readable. The old Staff availability records are kept read-only and do not affect eligibility.
- The interactive API documentation (`/docs`) is left enabled for local development.

## Out of scope for FYP1

Payment/POS, commission, inventory, payroll, external messaging (WhatsApp/SMS), native mobile application, multi-branch, multi-tenant SaaS, AI chatbot and commercialisation features.
