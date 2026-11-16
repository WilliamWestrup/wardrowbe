from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
)

from app.models.shopping import DeclutterAction, DeclutterStatus, GapPriority, GapStatus
from app.schemas.inspiration import _blank_to_none
from app.schemas.outfit import OutfitTags
from app.utils.garment_vocabulary import TYPES

MAX_TITLE_LENGTH = 120
MAX_TEXT_LENGTH = 2000
MAX_SHORT_LENGTH = 120
MAX_URL_LENGTH = 2000
MAX_PRODUCTS = 10
MAX_LINKED_IDS = 20
MAX_BULK = 50


def _required_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


def _http_url(value: str | None) -> str | None:
    """Keep only plain http(s) links. The URL is stored and shown, never fetched by the
    server; other schemes (javascript:, data:) are refused so the link is safe to render."""
    value = _blank_to_none(value)
    if value is None:
        return None
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ValueError("url must be an http or https link")
    return value


def _normalize_type(value: str | None) -> str | None:
    value = _blank_to_none(value)
    if value is None:
        return None
    normalized = value.lower()
    if normalized not in TYPES:
        raise ValueError(f"type {value!r} is not one of: {', '.join(TYPES)}")
    return normalized


def _normalize_currency(value: str | None) -> str | None:
    value = _blank_to_none(value)
    if value is None:
        return None
    value = value.upper()
    if len(value) != 3 or not value.isalpha() or not value.isascii():
        raise ValueError("currency must be a 3-letter code such as EUR")
    return value


def _unique_ids(values: list[UUID]) -> list[UUID]:
    return list(dict.fromkeys(values))


Title = Annotated[
    str, Field(min_length=1, max_length=MAX_TITLE_LENGTH), AfterValidator(_required_text)
]
RequiredText = Annotated[
    str, Field(min_length=1, max_length=MAX_TEXT_LENGTH), AfterValidator(_required_text)
]
LongText = Annotated[str | None, Field(max_length=MAX_TEXT_LENGTH), AfterValidator(_blank_to_none)]
ShortText = Annotated[
    str | None, Field(max_length=MAX_SHORT_LENGTH), AfterValidator(_blank_to_none)
]
Size = Annotated[str | None, Field(max_length=50), AfterValidator(_blank_to_none)]
GarmentType = Annotated[str | None, Field(max_length=50), AfterValidator(_normalize_type)]
Url = Annotated[str | None, Field(max_length=MAX_URL_LENGTH), AfterValidator(_http_url)]
Currency = Annotated[str | None, Field(max_length=3), AfterValidator(_normalize_currency)]
# Serialized as a JSON number so clients get 49.9, not "49.90".
Price = Annotated[
    Decimal,
    Field(ge=0, max_digits=12, decimal_places=2),
    PlainSerializer(float, return_type=float, when_used="json"),
]
LinkedIds = Annotated[list[UUID], Field(max_length=MAX_LINKED_IDS), AfterValidator(_unique_ids)]


class ProductSuggestion(BaseModel):
    """A product that could fill a gap. Written by the client; the server never opens url."""

    model_config = ConfigDict(extra="forbid")

    name: Title
    store: ShortText = None
    url: Url = None
    price: Price | None = None
    currency: Currency = None
    checked_at: date | None = None
    notes: LongText = None


Products = Annotated[list[ProductSuggestion], Field(max_length=MAX_PRODUCTS)]


class WardrobeGapUpdate(BaseModel):
    """Send only what changed. null clears an optional field; an empty list clears a list.
    title, priority and status cannot be cleared."""

    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    type: GarmentType = None
    priority: GapPriority | None = None
    status: GapStatus | None = None
    reason: LongText = None
    look_for: LongText = None
    avoid: LongText = None
    size: Size = None
    notes: LongText = None
    tags: OutfitTags | None = None
    pairs_with_item_ids: LinkedIds | None = None
    inspiration_look_ids: LinkedIds | None = None
    bought_item_id: UUID | None = None
    products: Products | None = None
    position: int | None = Field(None, ge=0, le=1_000_000)

    @field_validator("title", "priority", "status", "position")
    @classmethod
    def _not_clearable(cls, v: Any) -> Any:
        if v is None:
            raise ValueError("cannot be cleared")
        return v

    def changes(self) -> dict[str, Any]:
        """The fields sent, ready for the model: list columns are never None and products
        are stored as plain JSON."""
        updates = self.model_dump(exclude_unset=True)
        for key in ("tags", "pairs_with_item_ids", "inspiration_look_ids"):
            if key in updates and updates[key] is None:
                updates[key] = []
        if "products" in self.model_fields_set:
            updates["products"] = [p.model_dump(mode="json") for p in self.products or []]
        return updates


class WardrobeGapCreate(WardrobeGapUpdate):
    """A new gap. Only title is required; position defaults to the end of the list."""

    title: Title
    priority: GapPriority = GapPriority.medium
    status: GapStatus = GapStatus.open

    def changes(self) -> dict[str, Any]:
        fields = super().changes()
        fields.setdefault("priority", self.priority)
        fields.setdefault("status", self.status)
        return fields


class WardrobeGapBulkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gaps: list[WardrobeGapCreate] = Field(min_length=1, max_length=MAX_BULK)


class DeclutterUpdate(BaseModel):
    """Send only what changed. action, reason and status cannot be cleared. Marking a
    suggestion done only records the decision; it never archives the item."""

    model_config = ConfigDict(extra="forbid")

    action: DeclutterAction | None = None
    reason: RequiredText | None = None
    status: DeclutterStatus | None = None
    notes: LongText = None

    @field_validator("action", "reason", "status")
    @classmethod
    def _not_clearable(cls, v: Any) -> Any:
        if v is None:
            raise ValueError("cannot be cleared")
        return v


class DeclutterCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: UUID
    action: DeclutterAction = DeclutterAction.decide
    reason: RequiredText
    status: DeclutterStatus = DeclutterStatus.open
    notes: LongText = None


class DeclutterBulkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestions: list[DeclutterCreate] = Field(min_length=1, max_length=MAX_BULK)


class ItemSummary(BaseModel):
    """Just enough of a wardrobe item to show it on a card."""

    id: UUID
    name: str | None = None
    type: str
    primary_color: str | None = None
    thumbnail_url: str | None = None
    is_archived: bool = False


class LookSummary(BaseModel):
    id: UUID
    title: str | None = None
    thumbnail_url: str | None = None


class WardrobeGapResponse(BaseModel):
    id: UUID
    title: str
    type: str | None = None
    priority: GapPriority
    status: GapStatus
    reason: str | None = None
    look_for: str | None = None
    avoid: str | None = None
    size: str | None = None
    notes: str | None = None
    tags: list[str] = []
    pairs_with_item_ids: list[UUID] = []
    inspiration_look_ids: list[UUID] = []
    bought_item_id: UUID | None = None
    products: list[ProductSuggestion] = []
    position: int
    created_at: datetime
    updated_at: datetime
    # Resolved references; ids no longer usable (deleted, archived) are left out here.
    pairs_with: list[ItemSummary] = []
    inspiration_looks: list[LookSummary] = []
    bought_item: ItemSummary | None = None


class WardrobeGapListResponse(BaseModel):
    gaps: list[WardrobeGapResponse]
    total: int


class DeclutterResponse(BaseModel):
    id: UUID
    item_id: UUID
    action: DeclutterAction
    reason: str
    status: DeclutterStatus
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    item: ItemSummary


class DeclutterListResponse(BaseModel):
    suggestions: list[DeclutterResponse]
    total: int
