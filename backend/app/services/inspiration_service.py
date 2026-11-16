"""Inspiration looks: a saved outfit photo with vote, tags and notes, broken down into
garments (by the AI when it is on, or by hand) and linked to the user's own wardrobe.

Garment handling and wardrobe matching are adapted from lindawal/wardrowbe (MIT).
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.inspiration import (
    InspirationGarment,
    InspirationLook,
    InspirationStatus,
    InspirationVote,
)
from app.models.item import ClothingItem, ItemStatus
from app.services.image_service import ImageService
from app.services.inspiration_matching_service import (
    MATCH_RELEVANT_FIELDS,
    match_look,
    rematch_garment,
)

logger = logging.getLogger(__name__)

# Garments can't be edited while an analysis is on its way: it replaces them all.
ANALYSIS_RUNNING = frozenset({InspirationStatus.pending, InspirationStatus.analyzing})


class InspirationGarmentNotFoundError(LookupError):
    pass


class WardrobeItemUnavailableError(LookupError):
    """The wardrobe item doesn't exist, isn't the user's, or isn't ready."""


class InspirationAnalysisRunningError(Exception):
    pass


@dataclass(frozen=True)
class InspirationListFilters:
    vote: InspirationVote | None = None
    # Looks carrying every one of these tags.
    tags: tuple[str, ...] = ()


def photo_paths(look: InspirationLook) -> dict[str, str | None]:
    """In the shape ImageService.delete_images takes."""
    return {
        "image_path": look.photo_path,
        "medium_path": look.photo_medium_path,
        "thumbnail_path": look.photo_thumbnail_path,
    }


def wardrobe_ids_for_garments(garments: Iterable[InspirationGarment]) -> set[UUID]:
    ids: set[UUID] = set()
    for garment in garments:
        if garment.matched_item_id is not None:
            ids.add(garment.matched_item_id)
        ids.update(garment.suggested_item_ids or [])
    return ids


class InspirationService:
    def __init__(self, db: AsyncSession, image_service: ImageService | None = None):
        self.db = db
        self.image_service = image_service or ImageService()

    async def create_look(
        self,
        user_id: UUID,
        stored: dict[str, str],
        fields: dict[str, Any],
        status: InspirationStatus,
    ) -> InspirationLook:
        """Save a look for photo files already stored. The files are removed again when the
        commit fails, so a failed save leaves nothing behind."""
        look = InspirationLook(
            user_id=user_id,
            photo_path=stored["image_path"],
            photo_medium_path=stored.get("medium_path"),
            photo_thumbnail_path=stored.get("thumbnail_path"),
            status=status,
            **fields,
        )
        self.db.add(look)
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            self.image_service.delete_images(dict(stored))
            raise
        loaded = await self.get_look(look.id, user_id, refresh=True)
        assert loaded is not None  # just committed in this session
        return loaded

    async def get_look(
        self, look_id: UUID, user_id: UUID, *, refresh: bool = False
    ) -> InspirationLook | None:
        query = (
            select(InspirationLook)
            .options(selectinload(InspirationLook.garments))
            .where(InspirationLook.id == look_id, InspirationLook.user_id == user_id)
        )
        if refresh:
            query = query.execution_options(populate_existing=True)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_looks(
        self,
        user_id: UUID,
        filters: InspirationListFilters,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[InspirationLook], int]:
        conditions = [InspirationLook.user_id == user_id]
        if filters.vote is not None:
            conditions.append(InspirationLook.vote == filters.vote)
        if filters.tags:
            conditions.append(InspirationLook.tags.contains(list(filters.tags)))

        total = await self.db.scalar(
            select(func.count()).select_from(InspirationLook).where(and_(*conditions))
        )
        result = await self.db.execute(
            select(InspirationLook)
            .options(selectinload(InspirationLook.garments))
            .where(and_(*conditions))
            .order_by(InspirationLook.created_at.desc(), InspirationLook.id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)

    async def update_look(self, look: InspirationLook, updates: dict[str, Any]) -> None:
        for field, value in updates.items():
            setattr(look, field, value)
        await self.db.commit()
        # updated_at is set by the database, so it is expired after the commit.
        await self.db.refresh(look, attribute_names=["updated_at"])

    async def replace_photo(
        self, look: InspirationLook, stored: dict[str, str], status: InspirationStatus
    ) -> None:
        """Swap in a new photo. The garments described the old one, so they go; the old
        files are deleted only once the new paths are committed."""
        old = photo_paths(look)
        look.photo_path = stored["image_path"]
        look.photo_medium_path = stored.get("medium_path")
        look.photo_thumbnail_path = stored.get("thumbnail_path")
        look.status = status
        look.error_message = None
        look.matched_at = None
        look.garments.clear()
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            self.image_service.delete_images(dict(stored))
            raise
        await self.db.refresh(look, attribute_names=["updated_at"])
        self.image_service.delete_images(old)

    async def delete_look(self, look: InspirationLook) -> None:
        paths = photo_paths(look)
        await self.db.delete(look)
        await self.db.commit()
        # Files go only once the row is gone for good.
        self.image_service.delete_images(paths)

    async def usable_wardrobe_items(
        self, user_id: UUID, item_ids: Iterable[UUID]
    ) -> dict[UUID, ClothingItem]:
        """The subset of item_ids the user can wear: their own, ready and not archived.
        Anything linked or suggested earlier but gone since drops out here."""
        ids = set(item_ids)
        if not ids:
            return {}
        result = await self.db.execute(
            select(ClothingItem).where(
                and_(
                    ClothingItem.id.in_(ids),
                    ClothingItem.user_id == user_id,
                    ClothingItem.status == ItemStatus.ready,
                    ClothingItem.is_archived.is_(False),
                )
            )
        )
        return {item.id: item for item in result.scalars().all()}

    def _find_garment(self, look: InspirationLook, garment_id: UUID) -> InspirationGarment:
        garment = next((g for g in look.garments if g.id == garment_id), None)
        if garment is None:
            raise InspirationGarmentNotFoundError(str(garment_id))
        return garment

    def _ensure_editable(self, look: InspirationLook) -> None:
        if look.status in ANALYSIS_RUNNING:
            raise InspirationAnalysisRunningError(str(look.id))

    async def add_garment(
        self, look: InspirationLook, fields: dict[str, Any]
    ) -> InspirationGarment:
        """Add a garment by hand: one the AI missed, or any when the AI is off or failed.
        If the look has been matched, the new garment is matched right away."""
        self._ensure_editable(look)
        position = max((g.position for g in look.garments), default=-1) + 1
        garment = InspirationGarment(position=position, **fields)
        look.garments.append(garment)
        await self.db.flush()
        if look.matched_at is not None:
            await rematch_garment(self.db, look, garment)
        await self.db.commit()
        await self.db.refresh(garment)
        return garment

    async def update_garment(
        self, look: InspirationLook, garment_id: UUID, updates: dict[str, Any]
    ) -> InspirationGarment:
        """Apply a correction. Actually changing a tag the match depends on re-matches the
        garment, since the old suggestions were chosen for the wrong tags."""
        self._ensure_editable(look)
        garment = self._find_garment(look, garment_id)
        changed = {f for f, v in updates.items() if getattr(garment, f) != v}
        for field, value in updates.items():
            setattr(garment, field, value)
        if look.matched_at is not None and MATCH_RELEVANT_FIELDS & changed:
            await rematch_garment(self.db, look, garment)
        await self.db.commit()
        await self.db.refresh(garment)
        return garment

    async def delete_garment(self, look: InspirationLook, garment_id: UUID) -> None:
        self._ensure_editable(look)
        garment = self._find_garment(look, garment_id)
        look.garments.remove(garment)  # delete-orphan removes the row
        await self.db.commit()

    async def set_match(
        self, look: InspirationLook, garment_id: UUID, wardrobe_item_id: UUID | None
    ) -> InspirationGarment:
        """Link (or with None, unlink) a wardrobe item. Any ready, unarchived item of the
        user's is allowed, not only the suggested ones; the same rule as
        studio_service.validate_item_ownership, plus not archived."""
        garment = self._find_garment(look, garment_id)
        if wardrobe_item_id is not None:
            usable = await self.usable_wardrobe_items(look.user_id, [wardrobe_item_id])
            if wardrobe_item_id not in usable:
                raise WardrobeItemUnavailableError(str(wardrobe_item_id))
        garment.matched_item_id = wardrobe_item_id
        await self.db.commit()
        await self.db.refresh(garment)
        return garment

    async def rematch_look(self, look: InspirationLook) -> InspirationLook:
        """Match every garment against the wardrobe as it is now; resets manual links."""
        self._ensure_editable(look)
        await match_look(self.db, look)
        await self.db.commit()
        refreshed = await self.get_look(look.id, look.user_id, refresh=True)
        return refreshed if refreshed is not None else look
