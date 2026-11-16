from datetime import datetime
from typing import Annotated, Any
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.inspiration import InspirationStatus, InspirationVote
from app.schemas.color import ColorList, ColorName
from app.schemas.outfit import OutfitTags
from app.utils.garment_vocabulary import TYPES
from app.utils.tag_validation import normalize_tag_edits

MAX_TITLE_LENGTH = 200
MAX_SOURCE_URL_LENGTH = 2000
MAX_NOTES_LENGTH = 5000
MAX_DESCRIPTION_LENGTH = 200


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _http_url(value: str | None) -> str | None:
    """Keep only plain http(s) links. The URL is stored and shown, never fetched by the
    server; other schemes (javascript:, data:) are refused so the link is safe to render."""
    value = _blank_to_none(value)
    if value is None:
        return None
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ValueError("source_url must be an http or https link")
    return value


Title = Annotated[str | None, Field(max_length=MAX_TITLE_LENGTH), AfterValidator(_blank_to_none)]
SourceUrl = Annotated[
    str | None, Field(max_length=MAX_SOURCE_URL_LENGTH), AfterValidator(_http_url)
]
Notes = Annotated[str | None, Field(max_length=MAX_NOTES_LENGTH), AfterValidator(_blank_to_none)]


class InspirationLookUpdate(BaseModel):
    """Fields the owner sets on a look. Send only what changed; null clears a field
    (an empty list clears the tags)."""

    model_config = ConfigDict(extra="forbid")

    title: Title = None
    source_url: SourceUrl = None
    vote: InspirationVote | None = None
    tags: OutfitTags | None = None
    notes: Notes = None

    @field_validator("tags", mode="after")
    @classmethod
    def _null_tags_mean_empty(cls, v: list[str] | None) -> list[str]:
        return v or []


class InspirationGarmentUpdate(BaseModel):
    """A correction to one garment. Send only edited fields; null clears a single value
    and an empty list clears a list. `type` cannot be cleared."""

    model_config = ConfigDict(extra="forbid")

    type: str | None = Field(None, max_length=50)
    subtype: str | None = Field(None, max_length=50)
    primary_color: ColorName | None = None
    colors: ColorList | None = None
    pattern: str | None = Field(None, max_length=50)
    material: str | None = Field(None, max_length=50)
    style: list[Annotated[str, Field(max_length=50)]] | None = Field(None, max_length=10)
    formality: str | None = Field(None, max_length=50)
    season: list[Annotated[str, Field(max_length=50)]] | None = Field(None, max_length=10)
    fit: str | None = Field(None, max_length=50)
    description: str | None = Field(None, max_length=MAX_DESCRIPTION_LENGTH)

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str | None) -> str:
        if v is None:
            raise ValueError("type cannot be cleared")
        normalized = v.strip().lower()
        if normalized not in TYPES:
            raise ValueError(f"type {v!r} is not one of: {', '.join(TYPES)}")
        return normalized

    @model_validator(mode="after")
    def _validate_vocabulary(self) -> "InspirationGarmentUpdate":
        edits = {k: getattr(self, k) for k in ("pattern", "material", "formality", "fit")}
        edits |= {k: getattr(self, k) for k in ("style", "season")}
        cleaned = normalize_tag_edits(edits)
        for key, value in cleaned.items():
            object.__setattr__(self, key, value)
        if self.subtype is not None:
            object.__setattr__(self, "subtype", _blank_to_none(self.subtype))
        if self.description is not None:
            object.__setattr__(self, "description", _blank_to_none(self.description))
        return self

    def changes(self) -> dict[str, Any]:
        """The fields the client sent, with list fields never None (their columns are not
        nullable)."""
        updates = self.model_dump(exclude_unset=True)
        for key in ("colors", "style", "season"):
            if key in updates and updates[key] is None:
                updates[key] = []
        return updates


class InspirationGarmentCreate(InspirationGarmentUpdate):
    """A garment added by hand. Only `type` is required."""

    type: str = Field(max_length=50)


class InspirationMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # None clears the link ("nothing in my wardrobe for this one").
    wardrobe_item_id: UUID | None


class WardrobeItemSummary(BaseModel):
    """Just enough of a wardrobe item to show it as a match."""

    id: UUID
    type: str
    subtype: str | None = None
    name: str | None = None
    primary_color: str | None = None
    image_url: str | None = None
    thumbnail_url: str | None = None


class InspirationGarmentResponse(BaseModel):
    id: UUID
    position: int
    type: str
    subtype: str | None = None
    primary_color: str | None = None
    colors: list[str] = []
    pattern: str | None = None
    material: str | None = None
    style: list[str] = []
    formality: str | None = None
    season: list[str] = []
    fit: str | None = None
    description: str | None = None
    confidence: float | None = None
    matched_item_id: UUID | None = None
    # Resolved wardrobe items. matched_item is None when nothing is linked or the link is
    # no longer usable; suggested_items keeps rank order and drops unusable ids.
    matched_item: WardrobeItemSummary | None = None
    suggested_items: list[WardrobeItemSummary] = []


class InspirationLookResponse(BaseModel):
    id: UUID
    title: str | None = None
    source_url: str | None = None
    vote: InspirationVote | None = None
    tags: list[str] = []
    notes: str | None = None
    status: InspirationStatus
    error_message: str | None = None
    photo_url: str | None = None
    photo_medium_url: str | None = None
    photo_thumbnail_url: str | None = None
    matched_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    garment_count: int = 0
    garments: list[InspirationGarmentResponse] = []


class InspirationLookListResponse(BaseModel):
    looks: list[InspirationLookResponse]
    total: int
