"""Frontend checks run against the shipped ES modules (tests/ui_revamp.mjs).

Re-pointed in the 2026-11-18 product revamp: the layered legacy scripts (demo.js, operations.js, staff.js ...)
were replaced by one module tree, so the race and Staff-queue intents are now asserted on core/router.js,
core/session.js and staff/queue.js directly. Function names are kept for traceability.
"""
import os
from pathlib import Path
import shutil
import subprocess

HARNESS = str(Path(__file__).with_name('ui_revamp.mjs'))


def _node():
    node = os.getenv('PETOPS_NODE') or shutil.which('node')
    assert node, 'Install Node.js >=20 or set PETOPS_NODE for the built-in-only UI harness'
    return node


def test_delayed_ui_responses_do_not_cross_logout_or_newer_views():
    result = subprocess.run([_node(), HARNESS, 'races'], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_staff_queue_respects_actual_work_and_future_responsibility():
    result = subprocess.run([_node(), HARNESS, 'queue'], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
