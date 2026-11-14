"""Real shipped JS with controlled delayed responses; separate browser proof too."""
import os
from pathlib import Path
import shutil
import subprocess


def test_delayed_ui_responses_do_not_cross_logout_or_newer_views():
    node=os.getenv('PETOPS_NODE') or shutil.which('node')
    assert node,'Install Node.js >=20 or set PETOPS_NODE for the built-in-only UI race harness'
    result=subprocess.run([node,str(Path(__file__).with_name('ui_races.mjs'))],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr


def test_staff_queue_respects_actual_work_and_future_responsibility():
    node=os.getenv('PETOPS_NODE') or shutil.which('node')
    assert node,'Node.js is required for the shipped Staff queue checks'
    result=subprocess.run([node,str(Path(__file__).with_name('ui_product.mjs'))],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
