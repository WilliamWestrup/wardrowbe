"""add wardrobe gaps (shopping list) and declutter suggestions

Revision ID: d7a2c4e6f8b1
Revises: c9f1a3e5b7d2
Create Date: 2026-11-16

wardrobe_gaps is the shopping list: something missing from the wardrobe, with why, what to
look for and avoid, and product suggestions stored as JSONB (written by the client, never
fetched by the server). declutter_suggestions proposes that an item leave (or stay); a
partial unique index keeps at most one open suggestion per item. Neither table archives or
deletes wardrobe items.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d7a2c4e6f8b1"
down_revision: str | None = "c9f1a3e5b7d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIORITIES = ("high", "medium", "low")
GAP_STATUSES = ("open", "bought", "dropped")
ACTIONS = ("donate", "sell", "alter", "decide", "keep")
DECLUTTER_STATUSES = ("open", "done", "dismissed")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _user_id() -> sa.Column:
    return sa.Column(
        "user_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    op.execute(f"CREATE TYPE wardrobe_gap_priority AS ENUM {PRIORITIES!r}")
    op.execute(f"CREATE TYPE wardrobe_gap_status AS ENUM {GAP_STATUSES!r}")
    op.execute(f"CREATE TYPE declutter_action AS ENUM {ACTIONS!r}")
    op.execute(f"CREATE TYPE declutter_status AS ENUM {DECLUTTER_STATUSES!r}")

    op.create_table(
        "wardrobe_gaps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_id(),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("type", sa.String(50), nullable=True),
        sa.Column(
            "priority",
            postgresql.ENUM(*PRIORITIES, name="wardrobe_gap_priority", create_type=False),
            nullable=False,
            server_default="medium",
        ),
        sa.Column(
            "status",
            postgresql.ENUM(*GAP_STATUSES, name="wardrobe_gap_status", create_type=False),
            nullable=False,
            server_default="open",
        ),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("look_for", sa.Text, nullable=True),
        sa.Column("avoid", sa.Text, nullable=True),
        sa.Column("size", sa.String(50), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.String(30)), nullable=False, server_default="{}"),
        sa.Column(
            "pairs_with_item_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "inspiration_look_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "bought_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clothing_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "products",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        *_timestamps(),
    )
    op.create_index("ix_wardrobe_gaps_user_id", "wardrobe_gaps", ["user_id"])
    op.create_index("ix_wardrobe_gaps_tags", "wardrobe_gaps", ["tags"], postgresql_using="gin")

    op.create_table(
        "declutter_suggestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_id(),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clothing_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "action",
            postgresql.ENUM(*ACTIONS, name="declutter_action", create_type=False),
            nullable=False,
        ),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(*DECLUTTER_STATUSES, name="declutter_status", create_type=False),
            nullable=False,
            server_default="open",
        ),
        sa.Column("notes", sa.Text, nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_declutter_suggestions_user_id", "declutter_suggestions", ["user_id"])
    op.create_index("ix_declutter_suggestions_item_id", "declutter_suggestions", ["item_id"])
    op.create_index(
        "uq_declutter_suggestions_open_item",
        "declutter_suggestions",
        ["item_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_index("uq_declutter_suggestions_open_item", table_name="declutter_suggestions")
    op.drop_index("ix_declutter_suggestions_item_id", table_name="declutter_suggestions")
    op.drop_index("ix_declutter_suggestions_user_id", table_name="declutter_suggestions")
    op.drop_table("declutter_suggestions")
    op.drop_index("ix_wardrobe_gaps_tags", table_name="wardrobe_gaps")
    op.drop_index("ix_wardrobe_gaps_user_id", table_name="wardrobe_gaps")
    op.drop_table("wardrobe_gaps")
    op.execute("DROP TYPE IF EXISTS declutter_status")
    op.execute("DROP TYPE IF EXISTS declutter_action")
    op.execute("DROP TYPE IF EXISTS wardrobe_gap_status")
    op.execute("DROP TYPE IF EXISTS wardrobe_gap_priority")
