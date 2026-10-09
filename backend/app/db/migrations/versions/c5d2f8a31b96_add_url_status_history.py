"""add url_status_history

Revision ID: c5d2f8a31b96
Revises: b3a9e6d1f204
Create Date: 2026-10-09 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c5d2f8a31b96'
down_revision: str | None = 'b3a9e6d1f204'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('url_status_history',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
    sa.Column('issue', sa.String(length=30), nullable=True),
    sa.Column('verdict', sa.String(length=50), nullable=True),
    sa.Column('coverage_state', sa.Text(), nullable=True),
    sa.Column('last_crawl_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('inspected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('word_count', sa.Integer(), nullable=True),
    sa.Column('http_status', sa.Integer(), nullable=True),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_url_status_history_project_id'), 'url_status_history', ['project_id'], unique=False)
    op.create_index('ix_url_status_history_project_url_from', 'url_status_history', ['project_id', 'url', 'valid_from'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_url_status_history_project_url_from', table_name='url_status_history')
    op.drop_index(op.f('ix_url_status_history_project_id'), table_name='url_status_history')
    op.drop_table('url_status_history')
