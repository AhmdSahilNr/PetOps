"""C00B SEM-01/02: atomic arrival and departure; no history rewrite.
Revision ID: 0007
Revises: 0006
"""
from pathlib import Path
from alembic import op
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None
def upgrade():
    if op.get_context().dialect.name == "postgresql":
        op.execute(Path(__file__).with_name("0007_rules.sql").read_text(encoding="utf-8"))
def downgrade():
    raise RuntimeError("Merged lifecycle facts require reviewed forward repair; do not reinterpret recorded history")
