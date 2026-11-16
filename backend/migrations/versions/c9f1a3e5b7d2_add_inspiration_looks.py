"""add inspiration looks and their garments

Revision ID: c9f1a3e5b7d2
Revises: b8e4d0f2a6c3
Create Date: 2026-11-16

An inspiration look is a photo of an outfit seen elsewhere, saved with a vote, situation
tags, notes, an optional title and source link. inspiration_garments holds one row per
garment in the photo (found by the AI or added by hand), tagged with the item vocabulary and
optionally linked to a wardrobe item. matched_item_id is SET NULL on delete, so removing a
wardrobe item never deletes a look.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9f1a3e5b7d2"
down_revision: str | None = "b8e4d0f2a6c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("skipped", "pending", "analyzing", "analyzed", "error")
VOTES = ("love", "like")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.execute(f"CREATE TYPE inspiration_status AS ENUM {STATUSES!r}")
    op.execute(f"CREATE TYPE inspiration_vote AS ENUM {VOTES!r}")

    op.create_table(
        "inspiration_looks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("photo_path", sa.String(500), nullable=False),
        sa.Column("photo_medium_path", sa.String(500), nullable=True),
        sa.Column("photo_thumbnail_path", sa.String(500), nullable=True),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("source_url", sa.String(2000), nullable=True),
        sa.Column(
            "vote",
            postgresql.ENUM(*VOTES, name="inspiration_vote", create_type=False),
            nullable=True,
        ),
        sa.Column("tags", postgresql.ARRAY(sa.String(30)), nullable=False, server_default="{}"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(*STATUSES, name="inspiration_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_inspiration_looks_user_id", "inspiration_looks", ["user_id"])
    op.create_index(
        "ix_inspiration_looks_tags", "inspiration_looks", ["tags"], postgresql_using="gin"
    )

    op.create_table(
        "inspiration_garments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "look_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inspiration_looks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("type", sa.String(50), nullable=False, server_default="unknown"),
        sa.Column("subtype", sa.String(50), nullable=True),
        sa.Column("primary_color", sa.String(50), nullable=True),
        sa.Column("colors", postgresql.ARRAY(sa.String), nullable=False, server_default="{}"),
        sa.Column("pattern", sa.String(50), nullable=True),
        sa.Column("material", sa.String(50), nullable=True),
        sa.Column("style", postgresql.ARRAY(sa.String), nullable=False, server_default="{}"),
        sa.Column("formality", sa.String(50), nullable=True),
        sa.Column("season", postgresql.ARRAY(sa.String), nullable=False, server_default="{}"),
        sa.Column("fit", sa.String(50), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column(
            "matched_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clothing_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "suggested_item_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
        *_timestamps(),
    )
    op.create_index("ix_inspiration_garments_look_id", "inspiration_garments", ["look_id"])
    op.create_index(
        "ix_inspiration_garments_matched_item_id", "inspiration_garments", ["matched_item_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_inspiration_garments_matched_item_id", table_name="inspiration_garments")
    op.drop_index("ix_inspiration_garments_look_id", table_name="inspiration_garments")
    op.drop_table("inspiration_garments")
    op.drop_index("ix_inspiration_looks_tags", table_name="inspiration_looks")
    op.drop_index("ix_inspiration_looks_user_id", table_name="inspiration_looks")
    op.drop_table("inspiration_looks")
    op.execute("DROP TYPE IF EXISTS inspiration_vote")
    op.execute("DROP TYPE IF EXISTS inspiration_status")
