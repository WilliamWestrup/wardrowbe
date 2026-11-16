import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.item import ClothingItem
    from app.models.user import User


class InspirationStatus(enum.StrEnum):
    # skipped: internal vision is off, so garments are added by hand.
    skipped = "skipped"
    pending = "pending"
    analyzing = "analyzing"
    analyzed = "analyzed"
    error = "error"


class InspirationVote(enum.StrEnum):
    love = "love"
    like = "like"


class InspirationLook(Base):
    """A saved inspiration photo (an outfit seen elsewhere), not an outfit the user owns.

    The photo is stored through ImageService like any upload; source_url is only kept and
    shown as a link, the server never fetches it.
    """

    __tablename__ = "inspiration_looks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    photo_path: Mapped[str] = mapped_column(String(500), nullable=False)
    photo_medium_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    photo_thumbnail_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    vote: Mapped[InspirationVote | None] = mapped_column(
        Enum(InspirationVote, name="inspiration_vote", create_type=False), nullable=True
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(30)), nullable=False, default=list, server_default=text("'{}'")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[InspirationStatus] = mapped_column(
        Enum(InspirationStatus, name="inspiration_status", create_type=False),
        nullable=False,
        default=InspirationStatus.pending,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # When wardrobe matching last ran. NULL means never, as opposed to "matched, but
    # nothing in the wardrobe fits", which leaves garments with empty suggestions.
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User")
    garments: Mapped[list["InspirationGarment"]] = relationship(
        "InspirationGarment",
        back_populates="look",
        cascade="all, delete-orphan",
        order_by="InspirationGarment.position",
    )


class InspirationGarment(Base):
    """One garment in an inspiration look, found by the AI or added by hand.

    Tag fields use the item vocabulary (app/data/garment_vocabulary.json) so matching can
    compare them with the wardrobe directly.
    """

    __tablename__ = "inspiration_garments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    look_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inspiration_looks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    type: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    subtype: Mapped[str | None] = mapped_column(String(50))
    primary_color: Mapped[str | None] = mapped_column(String(50))
    colors: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list, server_default=text("'{}'")
    )
    pattern: Mapped[str | None] = mapped_column(String(50))
    material: Mapped[str | None] = mapped_column(String(50))
    style: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list, server_default=text("'{}'")
    )
    formality: Mapped[str | None] = mapped_column(String(50))
    season: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list, server_default=text("'{}'")
    )
    fit: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # The wardrobe item picked for this garment. Matching presets it to the best
    # suggestion; the user can swap it for any item of theirs, or clear it.
    matched_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clothing_items.id", ondelete="SET NULL"), nullable=True
    )
    # Best wardrobe candidates, best first. No FK: ids of items deleted or archived since
    # matching ran are dropped when the look is read.
    suggested_item_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default=text("'{}'")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    look: Mapped["InspirationLook"] = relationship("InspirationLook", back_populates="garments")
    matched_item: Mapped[Optional["ClothingItem"]] = relationship(
        "ClothingItem", foreign_keys=[matched_item_id]
    )
