"""add outfit item alternates

Revision ID: 4fc8501d464a
Revises: d7a2c4e6f8b1
Create Date: 2026-11-18

An alternate is an item that can stand in for one of an outfit's items (another pair of
shoes, say), so one outfit covers several variations instead of near-duplicate outfits.
Rows cascade with the outfit and with either item.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4fc8501d464a"
down_revision: str | None = "d7a2c4e6f8b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outfit_item_alternates",
        sa.Column(
            "outfit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outfits.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clothing_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "alternate_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clothing_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_outfit_item_alternates_alternate_item_id",
        "outfit_item_alternates",
        ["alternate_item_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outfit_item_alternates_alternate_item_id", table_name="outfit_item_alternates"
    )
    op.drop_table("outfit_item_alternates")
