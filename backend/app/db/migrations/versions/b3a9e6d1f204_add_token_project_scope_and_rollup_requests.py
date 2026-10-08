"""add token project scope and rollup_requests

Revision ID: b3a9e6d1f204
Revises: 7c1d9a40b3e5
Create Date: 2026-10-08 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'b3a9e6d1f204'
down_revision: str | None = '7c1d9a40b3e5'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('mcp_tokens', sa.Column('project_slugs', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_table('rollup_requests',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('requested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('requested_by', sa.String(length=255), nullable=True),
    sa.Column('done_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_rollup_requests_project_id'), 'rollup_requests', ['project_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_rollup_requests_project_id'), table_name='rollup_requests')
    op.drop_table('rollup_requests')
    op.drop_column('mcp_tokens', 'project_slugs')
