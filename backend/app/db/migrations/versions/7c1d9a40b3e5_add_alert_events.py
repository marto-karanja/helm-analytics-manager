"""add alert_events

Revision ID: 7c1d9a40b3e5
Revises: 2e5afd1c2899
Create Date: 2026-10-06 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '7c1d9a40b3e5'
down_revision: str | None = '2e5afd1c2899'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('alert_events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=60), nullable=False),
    sa.Column('severity', sa.String(length=20), nullable=False),
    sa.Column('state', sa.String(length=20), nullable=False),
    sa.Column('opened_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_notified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_alert_events_project_id'), 'alert_events', ['project_id'], unique=False)
    op.create_index('ix_alert_events_project_kind_state', 'alert_events', ['project_id', 'kind', 'state'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_alert_events_project_kind_state', table_name='alert_events')
    op.drop_index(op.f('ix_alert_events_project_id'), table_name='alert_events')
    op.drop_table('alert_events')
