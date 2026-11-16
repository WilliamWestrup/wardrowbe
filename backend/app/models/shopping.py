import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.item import ClothingItem


class GapPriority(enum.StrEnum):
    # Declared from most to least urgent: ORDER BY priority sorts in this order.
    high = "high"
    medium = "medium"
    low = "low"


class GapStatus(enum.StrEnum):
    open = "open"
    bought = "bought"
    dropped = "dropped"


class DeclutterAction(enum.StrEnum):
    donate = "donate"
    sell = "sell"
    alter = "alter"
    decide = "decide"
    keep = "keep"


class DeclutterStatus(enum.StrEnum):
    open = "open"
    done = "done"
    dismissed = "dismissed"


class WardrobeGap(Base):
    """Something missing from the wardrobe, on the shopping list.

    Product suggestions (name, store, link, price) are written by the client; the server
    stores them and never fetches the links.
    """

    __tablename__ = "wardrobe_gaps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    priority: Mapped[GapPriority] = mapped_column(
        Enum(GapPriority, name="wardrobe_gap_priority", create_type=False),
        nullable=False,
        default=GapPriority.medium,
    )
    status: Mapped[GapStatus] = mapped_column(
        Enum(GapStatus, name="wardrobe_gap_status", create_type=False),
        nullable=False,
        default=GapStatus.open,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    look_for: Mapped[str | None] = mapped_column(Text, nullable=True)
    avoid: Mapped[str | None] = mapped_column(Text, nullable=True)
    size: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(30)), nullable=False, default=list, server_default=text("'{}'")
    )
    # No FK, like inspiration suggestions: ids of items or looks deleted or archived since
    # are dropped when the gap is read.
    pairs_with_item_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default=text("'{}'")
    )
    inspiration_look_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default=text("'{}'")
    )
    bought_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clothing_items.id", ondelete="SET NULL"), nullable=True
    )
    products: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    bought_item: Mapped[Optional["ClothingItem"]] = relationship(
        "ClothingItem", foreign_keys=[bought_item_id]
    )


class DeclutterSuggestion(Base):
    """A suggestion that a wardrobe item leave (or stay). Recording a decision never
    archives or deletes the item; that stays a separate action by the owner."""

    __tablename__ = "declutter_suggestions"
    __table_args__ = (
        # At most one open suggestion per item.
        Index(
            "uq_declutter_suggestions_open_item",
            "item_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clothing_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[DeclutterAction] = mapped_column(
        Enum(DeclutterAction, name="declutter_action", create_type=False), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[DeclutterStatus] = mapped_column(
        Enum(DeclutterStatus, name="declutter_status", create_type=False),
        nullable=False,
        default=DeclutterStatus.open,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    item: Mapped["ClothingItem"] = relationship("ClothingItem", foreign_keys=[item_id])
