"""Comparison helpers for the 2026-11-18 revamp contract (decision D4 in docs/revamp/00_MASTER_REVAMP_PLAN.md).

Older tests asserted that the owner's booking response was identical to the Staff/Admin response. The revamp keeps
the same records but minimises the Customer view, and adds two read-only keys to detail responses ('timeline' for
every role and 'accommodation_name' for Staff/Admin Boarding). These helpers express that contract explicitly.
"""
from app.projections import customer_detail, customer_event

ADDITIVE = {'timeline', 'accommodation_name'}


def core(detail):
    """A detail response without the revamp's additive presentation keys."""
    return {k: v for k, v in detail.items() if k not in ADDITIVE}


def as_owner_sees(operational_detail):
    """What the owning Customer receives for the same booking."""
    return core(customer_detail(core(operational_detail)))


def owner_history(events):
    return [customer_event(e) for e in events]
