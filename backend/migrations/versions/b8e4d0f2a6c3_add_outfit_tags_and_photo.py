"""add situation tags and a photo to outfits

Revision ID: b8e4d0f2a6c3
Revises: a7d3c9e1f5b2
Create Date: 2026-11-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8e4d0f2a6c3"
down_revision: str | None = "a7d3c9e1f5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outfits",
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String(30)),
            nullable=False,
            server_default="{}",
        ),
    )
    op.create_index("ix_outfits_tags", "outfits", ["tags"], postgresql_using="gin")
    op.add_column("outfits", sa.Column("photo_path", sa.String(500), nullable=True))
    op.add_column("outfits", sa.Column("photo_medium_path", sa.String(500), nullable=True))
    op.add_column("outfits", sa.Column("photo_thumbnail_path", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("outfits", "photo_thumbnail_path")
    op.drop_column("outfits", "photo_medium_path")
    op.drop_column("outfits", "photo_path")
    op.drop_index("ix_outfits_tags", table_name="outfits")
    op.drop_column("outfits", "tags")
