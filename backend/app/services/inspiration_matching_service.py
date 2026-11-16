"""Wardrobe matching for inspiration looks, adapted from lindawal/wardrowbe (MIT).

For every garment identified in an inspiration photo, find the most similar
pieces in the user's own wardrobe. Pure scoring over the stored tags -- no AI call --
so it is cheap enough to run inside the analysis job and again whenever the user
corrects an item's tags.

Scoring is "how much does this wardrobe item look like that garment", not "does it
suit today's weather/occasion" (that's item_scorer.py's job):

- Type is a hard filter: an exact type match counts fully, a closely related type
  (jeans <-> pants, sneakers <-> shoes, ...) counts at RELATED_TYPE_FACTOR, anything
  else is not a candidate at all.
- Within that, a weighted similarity over color, pattern, material, style,
  formality and fit. A tag that is missing on either side scores UNKNOWN (neutral)
  rather than 0, so an untagged item isn't punished for what AI didn't record.

The weights and the related-type/close-color tables are a first guess meant to be
tuned against the real wardrobe, not a finished calibration.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inspiration import InspirationGarment, InspirationLook
from app.models.item import ClothingItem, ItemStatus
from app.services.item_scorer import FORMALITY_ORDER

# Best match + 2 alternatives; any other item stays reachable through the picker in the UI.
MATCH_SUGGESTION_COUNT = 3

# Tag fields whose correction changes the match, so editing one re-runs matching
# for that item. subtype/season/description are informational only here.
MATCH_RELEVANT_FIELDS = frozenset(
    {"type", "primary_color", "colors", "pattern", "material", "style", "formality", "fit"}
)

UNKNOWN = 0.5
RELATED_TYPE_FACTOR = 0.6

WEIGHTS: dict[str, float] = {
    "color": 0.40,
    "pattern": 0.15,
    "material": 0.10,
    "style": 0.15,
    "formality": 0.10,
    "fit": 0.10,
}

# Directed on purpose: the key is the type seen in the photo, the values are the
# wardrobe types that can stand in for it. Uses our vocabulary (garment_vocabulary.json).
RELATED_TYPES: dict[str, frozenset[str]] = {
    "jeans": frozenset({"pants"}),
    "pants": frozenset({"jeans"}),
    "leggings": frozenset({"tights"}),
    "sneakers": frozenset({"shoes"}),
    "shoes": frozenset({"sneakers", "boots", "flats"}),
    "boots": frozenset({"shoes"}),
    "flats": frozenset({"shoes"}),
    "heels": frozenset({"flats", "shoes"}),
    "t-shirt": frozenset({"tank-top", "top", "polo"}),
    "tank-top": frozenset({"t-shirt", "camisole"}),
    "camisole": frozenset({"tank-top"}),
    "top": frozenset({"t-shirt", "blouse"}),
    "shirt": frozenset({"blouse", "polo"}),
    "blouse": frozenset({"shirt", "top"}),
    "polo": frozenset({"t-shirt", "shirt"}),
    "sweater": frozenset({"sweatshirt", "cardigan"}),
    "sweatshirt": frozenset({"sweater", "hoodie"}),
    "hoodie": frozenset({"sweatshirt"}),
    "cardigan": frozenset({"sweater"}),
    "jacket": frozenset({"blazer", "coat"}),
    "blazer": frozenset({"jacket"}),
    "coat": frozenset({"jacket"}),
}

_CLOSE_COLOR_PAIRS = (
    ("navy", "blue"),
    ("blue", "light-blue"),
    ("navy", "black"),
    ("gray", "black"),
    ("gray", "silver"),
    ("white", "cream"),
    ("cream", "beige"),
    ("beige", "tan"),
    ("tan", "brown"),
    ("red", "burgundy"),
    ("red", "pink"),
    ("burgundy", "purple"),
    ("green", "olive"),
    ("yellow", "gold"),
    ("yellow", "orange"),
)
CLOSE_COLORS: frozenset[frozenset[str]] = frozenset(frozenset(p) for p in _CLOSE_COLOR_PAIRS)

_CLOSE_FIT_PAIRS = (
    ("slim", "regular"),
    ("slim", "tailored"),
    ("regular", "relaxed"),
    ("relaxed", "oversized"),
)
CLOSE_FITS: frozenset[frozenset[str]] = frozenset(frozenset(p) for p in _CLOSE_FIT_PAIRS)


@dataclass(frozen=True)
class MatchCandidate:
    item: ClothingItem
    score: float


def _norm(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value or None


def _norm_list(values: Iterable[object] | None) -> set[str]:
    return {v for v in (_norm(x) for x in (values or [])) if v}


def item_fit(item: ClothingItem) -> str | None:
    # Fit is a JSON-only tag on clothing items (kept in item.tags).
    tags = item.tags if isinstance(item.tags, dict) else {}
    return _norm(tags.get("fit"))


def type_factor(look_type: str | None, item_type: str | None) -> float:
    look_type, item_type = _norm(look_type), _norm(item_type)
    if not look_type or not item_type or look_type == "unknown":
        return 0.0
    if look_type == item_type:
        return 1.0
    if item_type in RELATED_TYPES.get(look_type, frozenset()):
        return RELATED_TYPE_FACTOR
    return 0.0


def color_score(
    look_primary: str | None,
    look_colors: Iterable[str] | None,
    item_primary: str | None,
    item_colors: Iterable[str] | None,
) -> float:
    look_primary, item_primary = _norm(look_primary), _norm(item_primary)
    look_all = _norm_list(look_colors)
    item_all = _norm_list(item_colors)
    if not look_primary or not (item_primary or item_all):
        return UNKNOWN
    if look_primary == item_primary:
        return 1.0
    if item_primary and frozenset((look_primary, item_primary)) in CLOSE_COLORS:
        return 0.6
    # The photo's main color shows up somewhere on the item, or vice versa.
    if look_primary in item_all or (item_primary and item_primary in look_all):
        return 0.4
    return 0.0


def equal_score(a: str | None, b: str | None) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return UNKNOWN
    return 1.0 if a == b else 0.0


def style_score(a: Iterable[str] | None, b: Iterable[str] | None) -> float:
    set_a, set_b = _norm_list(a), _norm_list(b)
    if not set_a or not set_b:
        return UNKNOWN
    return len(set_a & set_b) / len(set_a | set_b)


def formality_score(a: str | None, b: str | None) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return UNKNOWN
    if a == b:
        return 1.0
    if a in FORMALITY_ORDER and b in FORMALITY_ORDER:
        if abs(FORMALITY_ORDER.index(a) - FORMALITY_ORDER.index(b)) == 1:
            return 0.5
    return 0.0


def fit_score(a: str | None, b: str | None) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return UNKNOWN
    if a == b:
        return 1.0
    if frozenset((a, b)) in CLOSE_FITS:
        return 0.5
    return 0.0


def score_candidate(garment: InspirationGarment, item: ClothingItem) -> float:
    """Similarity in [0, 1]; 0.0 also for items of an unrelated type."""
    factor = type_factor(garment.type, item.type)
    if factor == 0.0:
        return 0.0
    similarity = (
        WEIGHTS["color"]
        * color_score(garment.primary_color, garment.colors, item.primary_color, item.colors)
        + WEIGHTS["pattern"] * equal_score(garment.pattern, item.pattern)
        + WEIGHTS["material"] * equal_score(garment.material, item.material)
        + WEIGHTS["style"] * style_score(garment.style, item.style)
        + WEIGHTS["formality"] * formality_score(garment.formality, item.formality)
        + WEIGHTS["fit"] * fit_score(garment.fit, item_fit(item))
    )
    return round(factor * similarity, 4)


def rank_candidates(
    garment: InspirationGarment, wardrobe: Sequence[ClothingItem]
) -> list[MatchCandidate]:
    """Every type-compatible wardrobe item, best first.

    An item of the right type is a candidate even if nothing else about it fits --
    it's still the closest thing the wardrobe has. Ties go to favorites, then to a
    stable id order so repeated runs agree.
    """
    ranked = [
        MatchCandidate(item=item, score=score_candidate(garment, item))
        for item in wardrobe
        if type_factor(garment.type, item.type) > 0.0
    ]
    ranked.sort(key=lambda c: (-c.score, not c.item.favorite, str(c.item.id)))
    return ranked


def assign_match(
    garment: InspirationGarment,
    wardrobe: Sequence[ClothingItem],
    taken: set[UUID] | None = None,
) -> None:
    """Store the top suggestions on garment and preselect the best one.

    `taken` holds wardrobe items already picked for other slots of the same look, so
    two slots (say a t-shirt and a blouse layered over it) don't both get preselected
    with the same piece. The user can still pick such an item by hand.
    """
    taken = taken or set()
    available = [c for c in rank_candidates(garment, wardrobe) if c.item.id not in taken]
    top = available[:MATCH_SUGGESTION_COUNT]
    garment.suggested_item_ids = [c.item.id for c in top]
    garment.matched_item_id = top[0].item.id if top else None


def match_garments(
    garments: Sequence[InspirationGarment], wardrobe: Sequence[ClothingItem]
) -> None:
    taken: set[UUID] = set()
    for garment in sorted(garments, key=lambda i: i.position):
        assign_match(garment, wardrobe, taken)
        if garment.matched_item_id is not None:
            taken.add(garment.matched_item_id)


async def load_wardrobe(db: AsyncSession, user_id: UUID) -> list[ClothingItem]:
    """The items matching may suggest: the same "usable" filter recommendations use."""
    result = await db.execute(
        select(ClothingItem).where(
            and_(
                ClothingItem.user_id == user_id,
                ClothingItem.status == ItemStatus.ready,
                ClothingItem.is_archived.is_(False),
            )
        )
    )
    return list(result.scalars().all())


async def match_look(db: AsyncSession, look: InspirationLook) -> None:
    """(Re-)match every garment of `look` (garments must be loaded). Does not commit.

    Resets any manual pick: the caller asked for a fresh match.
    """
    wardrobe = await load_wardrobe(db, look.user_id)
    match_garments(look.garments, wardrobe)
    look.matched_at = datetime.now(UTC)


async def rematch_garment(
    db: AsyncSession, look: InspirationLook, garment: InspirationGarment
) -> None:
    """Re-match one garment after its tags were corrected. Does not commit."""
    wardrobe = await load_wardrobe(db, look.user_id)
    taken = {
        other.matched_item_id
        for other in look.garments
        if other.id != garment.id and other.matched_item_id is not None
    }
    assign_match(garment, wardrobe, taken)
