"""add_pr_columns_to_tasks

Revision ID: b71d9f824e12
Revises: 8be08d783f35
Create Date: 2026-10-26 19:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b71d9f824e12'
down_revision: Union[str, Sequence[str], None] = '8be08d783f35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to add PR tracking columns."""
    op.add_column('tasks', sa.Column('pr_number', sa.Integer(), nullable=True))
    op.add_column('tasks', sa.Column('pr_url', sa.String(length=512), nullable=True))
    op.add_column('tasks', sa.Column('source_branch', sa.String(length=255), nullable=True))
    op.add_column('tasks', sa.Column('target_branch', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('tasks', 'target_branch')
    op.drop_column('tasks', 'source_branch')
    op.drop_column('tasks', 'pr_url')
    op.drop_column('tasks', 'pr_number')
