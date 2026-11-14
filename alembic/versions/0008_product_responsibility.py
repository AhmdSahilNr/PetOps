"""Controlled product addendum: booking responsibility, display identity/order, pet archive.
Revision ID: 0008
Revises: 0007
"""
from pathlib import Path
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ExcludeConstraint

revision="0008"
down_revision="0007"
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('users',sa.Column('display_name',sa.String(120),nullable=True))
    op.add_column('services',sa.Column('display_order',sa.Integer(),nullable=False,server_default='0'))
    op.add_column('pets',sa.Column('is_active',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('staff_responsibilities',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('booking_id',sa.Uuid(),sa.ForeignKey('bookings.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('staff_user_id',sa.Uuid(),sa.ForeignKey('users.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('starts_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('ends_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('ended_at',sa.DateTime(timezone=True),nullable=True),
        sa.Column('ended_by_user_id',sa.Uuid(),sa.ForeignKey('users.id',ondelete='RESTRICT'),nullable=True),
        sa.Column('released_at',sa.DateTime(timezone=True),nullable=True),
        sa.Column('created_by_user_id',sa.Uuid(),sa.ForeignKey('users.id',ondelete='RESTRICT'),nullable=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint('ends_at > starts_at AND (ended_at IS NULL OR (ended_at > starts_at AND ended_at <= ends_at AND ended_by_user_id IS NOT NULL))',name='ck_responsibility_period'))
    op.create_index('ix_staff_responsibilities_booking_id','staff_responsibilities',['booking_id'])
    op.create_index('ix_staff_responsibilities_staff_user_id','staff_responsibilities',['staff_user_id'])
    if op.get_context().dialect.name=='postgresql':
        op.create_check_constraint('ck_user_display_name','users',"display_name IS NULL OR (display_name=trim(display_name) AND length(display_name) BETWEEN 1 AND 120)")
        op.create_check_constraint('ck_service_display_order','services','display_order BETWEEN 0 AND 100000')
        # Import only the exact last recorded period. Do not invent old handovers or names.
        op.execute("""INSERT INTO staff_responsibilities(id,booking_id,staff_user_id,starts_at,ends_at,released_at,created_at)
          SELECT gen_random_uuid(),id,assigned_staff_user_id,staff_start,staff_end,
            CASE WHEN status IN ('SUBMITTED','CONFIRMED','IN_PROGRESS','CHECKED_IN','STAYING') THEN NULL ELSE updated_at END,
            clock_timestamp() FROM bookings WHERE assigned_staff_user_id IS NOT NULL AND staff_start IS NOT NULL AND staff_end IS NOT NULL""")
        for column,name in [('staff_user_id','ex_responsibility_staff_overlap'),('booking_id','ex_responsibility_booking_overlap')]:
            op.execute(f"ALTER TABLE staff_responsibilities ADD CONSTRAINT {name} EXCLUDE USING gist ({column} WITH =, tstzrange(starts_at,coalesce(ended_at,ends_at),'[)') WITH &&) WHERE (released_at IS NULL)")
        op.execute(Path(__file__).with_name('0008_rules.sql').read_text(encoding='utf-8'))

def downgrade():
    raise RuntimeError('Responsibility history must be retained; use reviewed forward repair')
