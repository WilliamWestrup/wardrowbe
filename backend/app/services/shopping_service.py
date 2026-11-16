"""Shopping list (wardrobe gaps) and declutter suggestions.

Both are mostly written by an external agent through the API and read by the owner. The
server stores product links and prices as given and never fetches them. Nothing here
archives or deletes wardrobe items.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inspiration import InspirationLook
from app.models.item import ClothingItem
from app.models.shopping import (
    DeclutterAction,
    DeclutterStatus,
    DeclutterSuggestion,
    GapPriority,
    GapStatus,
    WardrobeGap,
)


class ShoppingReferenceError(LookupError):
    """A referenced item or look doesn't exist, isn't the user's, or can't be used."""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class DeclutterAlreadyOpenError(Exception):
    def __init__(self, item_id: UUID):
        super().__init__(str(item_id))
        self.item_id = item_id


@dataclass(frozen=True)
class GapFilters:
    status: GapStatus | None = None
    priority: GapPriority | None = None
    # Gaps carrying every one of these tags.
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeclutterFilters:
    status: DeclutterStatus | None = None
    action: DeclutterAction | None = None


def _prefix(index: int | None) -> str:
    return "" if index is None else f"gaps[{index}]: "


class ShoppingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- references -------------------------------------------------------------------

    async def owned_items(
        self, user_id: UUID, item_ids: Iterable[UUID], *, include_archived: bool
    ) -> dict[UUID, ClothingItem]:
        ids = set(item_ids)
        if not ids:
            return {}
        conditions = [ClothingItem.id.in_(ids), ClothingItem.user_id == user_id]
        if not include_archived:
            conditions.append(ClothingItem.is_archived.is_(False))
        result = await self.db.execute(select(ClothingItem).where(and_(*conditions)))
        return {item.id: item for item in result.scalars().all()}

    async def owned_looks(
        self, user_id: UUID, look_ids: Iterable[UUID]
    ) -> dict[UUID, InspirationLook]:
        ids = set(look_ids)
        if not ids:
            return {}
        result = await self.db.execute(
            select(InspirationLook).where(
                InspirationLook.id.in_(ids), InspirationLook.user_id == user_id
            )
        )
        return {look.id: look for look in result.scalars().all()}

    async def _check_gap_references(
        self, user_id: UUID, fields: dict[str, Any], index: int | None = None
    ) -> None:
        """pairs_with must be the user's own unarchived items, looks the user's own, and the
        bought item the user's own (archived allowed). Same rule as inspiration matches:
        anything else reads as not found, so other users' ids leak nothing."""
        pairs = fields.get("pairs_with_item_ids") or []
        if pairs:
            usable = await self.owned_items(user_id, pairs, include_archived=False)
            missing = [i for i in pairs if i not in usable]
            if missing:
                raise ShoppingReferenceError(
                    "WARDROBE_ITEM_NOT_FOUND",
                    f"{_prefix(index)}wardrobe item {missing[0]} not found",
                )
        looks = fields.get("inspiration_look_ids") or []
        if looks:
            owned = await self.owned_looks(user_id, looks)
            missing = [i for i in looks if i not in owned]
            if missing:
                raise ShoppingReferenceError(
                    "INSPIRATION_LOOK_NOT_FOUND",
                    f"{_prefix(index)}inspiration look {missing[0]} not found",
                )
        bought = fields.get("bought_item_id")
        if bought is not None:
            owned_items = await self.owned_items(user_id, [bought], include_archived=True)
            if bought not in owned_items:
                raise ShoppingReferenceError(
                    "WARDROBE_ITEM_NOT_FOUND",
                    f"{_prefix(index)}wardrobe item {bought} not found",
                )

    # --- gaps -------------------------------------------------------------------------

    async def get_gap(self, gap_id: UUID, user_id: UUID) -> WardrobeGap | None:
        result = await self.db.execute(
            select(WardrobeGap).where(WardrobeGap.id == gap_id, WardrobeGap.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_gaps(
        self, user_id: UUID, filters: GapFilters, limit: int, offset: int
    ) -> tuple[list[WardrobeGap], int]:
        conditions = [WardrobeGap.user_id == user_id]
        if filters.status is not None:
            conditions.append(WardrobeGap.status == filters.status)
        if filters.priority is not None:
            conditions.append(WardrobeGap.priority == filters.priority)
        if filters.tags:
            conditions.append(WardrobeGap.tags.contains(list(filters.tags)))
        total = await self.db.scalar(
            select(func.count()).select_from(WardrobeGap).where(and_(*conditions))
        )
        result = await self.db.execute(
            select(WardrobeGap)
            .where(and_(*conditions))
            .order_by(
                WardrobeGap.priority,
                WardrobeGap.position,
                WardrobeGap.created_at,
                WardrobeGap.id,
            )
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)

    async def _next_position(self, user_id: UUID) -> int:
        current = await self.db.scalar(
            select(func.max(WardrobeGap.position)).where(WardrobeGap.user_id == user_id)
        )
        return 0 if current is None else current + 1

    async def create_gaps(
        self, user_id: UUID, items: Sequence[dict[str, Any]], *, bulk: bool = False
    ) -> list[WardrobeGap]:
        """Validate every gap first, then save them all in one commit: a bulk request either
        creates all its gaps or none."""
        for index, fields in enumerate(items):
            await self._check_gap_references(user_id, fields, index if bulk else None)
        position = await self._next_position(user_id)
        gaps = []
        for fields in items:
            fields = dict(fields)
            if fields.get("position") is None:
                fields["position"] = position
                position += 1
            gap = WardrobeGap(user_id=user_id, **fields)
            self.db.add(gap)
            gaps.append(gap)
        await self.db.commit()
        for gap in gaps:
            await self.db.refresh(gap)
        return gaps

    async def update_gap(self, gap: WardrobeGap, updates: dict[str, Any]) -> WardrobeGap:
        await self._check_gap_references(gap.user_id, updates)
        for field, value in updates.items():
            setattr(gap, field, value)
        await self.db.commit()
        await self.db.refresh(gap)
        return gap

    async def delete_gap(self, gap: WardrobeGap) -> None:
        await self.db.delete(gap)
        await self.db.commit()

    # --- declutter --------------------------------------------------------------------

    async def get_suggestion(
        self, suggestion_id: UUID, user_id: UUID
    ) -> DeclutterSuggestion | None:
        result = await self.db.execute(
            select(DeclutterSuggestion).where(
                DeclutterSuggestion.id == suggestion_id, DeclutterSuggestion.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def list_suggestions(
        self, user_id: UUID, filters: DeclutterFilters, limit: int, offset: int
    ) -> tuple[list[DeclutterSuggestion], int]:
        conditions = [DeclutterSuggestion.user_id == user_id]
        if filters.status is not None:
            conditions.append(DeclutterSuggestion.status == filters.status)
        if filters.action is not None:
            conditions.append(DeclutterSuggestion.action == filters.action)
        total = await self.db.scalar(
            select(func.count()).select_from(DeclutterSuggestion).where(and_(*conditions))
        )
        result = await self.db.execute(
            select(DeclutterSuggestion)
            .where(and_(*conditions))
            .order_by(DeclutterSuggestion.created_at.desc(), DeclutterSuggestion.id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)

    async def _open_item_ids(self, user_id: UUID, item_ids: Iterable[UUID]) -> set[UUID]:
        ids = set(item_ids)
        if not ids:
            return set()
        result = await self.db.execute(
            select(DeclutterSuggestion.item_id).where(
                DeclutterSuggestion.user_id == user_id,
                DeclutterSuggestion.item_id.in_(ids),
                DeclutterSuggestion.status == DeclutterStatus.open,
            )
        )
        return set(result.scalars().all())

    async def create_suggestions(
        self, user_id: UUID, items: Sequence[dict[str, Any]], *, bulk: bool = False
    ) -> list[DeclutterSuggestion]:
        """The item must be the user's own and not archived, and have no other open
        suggestion. All or nothing for bulk requests."""
        item_ids = [fields["item_id"] for fields in items]
        owned = await self.owned_items(user_id, item_ids, include_archived=False)
        for index, item_id in enumerate(item_ids):
            if item_id not in owned:
                prefix = f"suggestions[{index}]: " if bulk else ""
                raise ShoppingReferenceError(
                    "WARDROBE_ITEM_NOT_FOUND", f"{prefix}wardrobe item {item_id} not found"
                )
        open_ids = await self._open_item_ids(user_id, item_ids)
        seen: set[UUID] = set()
        for fields in items:
            if fields["status"] != DeclutterStatus.open:
                continue
            item_id = fields["item_id"]
            if item_id in open_ids or item_id in seen:
                raise DeclutterAlreadyOpenError(item_id)
            seen.add(item_id)

        suggestions = [DeclutterSuggestion(user_id=user_id, **fields) for fields in items]
        self.db.add_all(suggestions)
        await self._commit_or_conflict(item_ids[0])
        for suggestion in suggestions:
            await self.db.refresh(suggestion)
        return suggestions

    async def update_suggestion(
        self, suggestion: DeclutterSuggestion, updates: dict[str, Any]
    ) -> DeclutterSuggestion:
        reopening = (
            updates.get("status") == DeclutterStatus.open
            and suggestion.status != DeclutterStatus.open
        )
        if reopening and await self._open_item_ids(suggestion.user_id, [suggestion.item_id]):
            raise DeclutterAlreadyOpenError(suggestion.item_id)
        for field, value in updates.items():
            setattr(suggestion, field, value)
        await self._commit_or_conflict(suggestion.item_id)
        await self.db.refresh(suggestion)
        return suggestion

    async def delete_suggestion(self, suggestion: DeclutterSuggestion) -> None:
        await self.db.delete(suggestion)
        await self.db.commit()

    async def _commit_or_conflict(self, item_id: UUID) -> None:
        """The partial unique index is the last word when two writes race."""
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise DeclutterAlreadyOpenError(item_id) from None
