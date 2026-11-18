from datetime import UTC, date, datetime, timedelta
from itertools import combinations
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.item import ClothingItem, ItemStatus
from app.models.outfit import (
    FamilyOutfitRating,
    Outfit,
    OutfitItem,
    OutfitItemAlternate,
    OutfitSource,
    OutfitStatus,
)
from app.models.user import User
from app.services.item_service import ItemService
from app.services.learning_service import LearningService
from app.utils.clothing import canonical_item_order
from app.utils.timezone import get_user_today


class ItemOwnershipError(Exception):
    pass


class OutfitWornImmutableError(Exception):
    pass


class OutfitNotTemplateError(Exception):
    pass


class InvalidAlternateError(ValueError):
    pass


async def load_full_outfit(db: AsyncSession, outfit_id: UUID) -> Outfit:
    result = await db.execute(
        select(Outfit)
        .where(Outfit.id == outfit_id)
        .options(
            selectinload(Outfit.items).selectinload(OutfitItem.item),
            selectinload(Outfit.feedback),
            selectinload(Outfit.source_item),
            selectinload(Outfit.family_ratings).selectinload(FamilyOutfitRating.user),
        )
    )
    return result.scalar_one()


async def validate_item_ownership(
    db: AsyncSession, user_id: UUID, item_ids: list[UUID]
) -> list[ClothingItem]:
    if not item_ids:
        raise ValueError("items required")

    result = await db.execute(
        select(ClothingItem).where(
            and_(
                ClothingItem.id.in_(item_ids),
                ClothingItem.user_id == user_id,
                ClothingItem.status == ItemStatus.ready,
            )
        )
    )
    items = list(result.scalars().all())
    unique_requested = set(item_ids)
    if len(items) != len(unique_requested):
        raise ItemOwnershipError("one or more items do not belong to the caller")
    return items


class StudioService:
    CLONE_SOFT_IDEMPOTENCY_SECONDS = 5

    def __init__(self, db: AsyncSession):
        self.db = db
        self.learning = LearningService(db)

    def _order_items_canonically(self, items: list[ClothingItem]) -> list[ClothingItem]:
        type_map = {item.id: (item.type or "") for item in items}
        ordered_ids = canonical_item_order([i.id for i in items], type_map)
        by_id = {item.id: item for item in items}
        return [by_id[iid] for iid in ordered_ids]

    async def _reload_outfit(self, outfit_id: UUID) -> Outfit:
        result = await self.db.execute(
            select(Outfit)
            .where(Outfit.id == outfit_id)
            .options(
                selectinload(Outfit.items).selectinload(OutfitItem.item),
                selectinload(Outfit.feedback),
            )
        )
        return result.scalar_one()

    async def get_full_outfit(self, outfit_id: UUID) -> Outfit:
        return await load_full_outfit(self.db, outfit_id)

    async def create_from_scratch(
        self,
        user: User,
        item_ids: list[UUID],
        occasion: str,
        name: str | None,
        scheduled_for: date | None,
        mark_worn: bool,
        source_item_id: UUID | None,
        season: str | None = None,
        formality: str | None = None,
        palette: list[str] | None = None,
        notes: str | None = None,
    ) -> Outfit:
        items = await validate_item_ownership(self.db, user.id, item_ids)
        ordered = self._order_items_canonically(items)

        # Marking an undated outfit worn means it was worn today, as wear_today assumes.
        if mark_worn and scheduled_for is None:
            scheduled_for = get_user_today(user)
        effective_worn = scheduled_for if mark_worn else None

        outfit = Outfit(
            user_id=user.id,
            occasion=occasion,
            scheduled_for=scheduled_for,
            source=OutfitSource.manual,
            status=OutfitStatus.pending,
            name=name,
            source_item_id=source_item_id,
            season=season,
            formality=formality,
            palette=palette,
            notes=notes,
        )
        self.db.add(outfit)
        await self.db.flush()

        for pos, item in enumerate(ordered):
            self.db.add(OutfitItem(outfit_id=outfit.id, item_id=item.id, position=pos))

        feedback = self.learning.create_synthetic_feedback(
            outfit_id=outfit.id, accepted=True, worn_at=effective_worn
        )
        self.db.add(feedback)

        if mark_worn and effective_worn is not None:
            await ItemService(self.db).record_wears(
                user.id,
                [i.id for i in ordered],
                effective_worn,
                occasion=occasion,
                outfit_id=outfit.id,
            )

        await self.db.flush()
        return await self._reload_outfit(outfit.id)

    async def create_wore_instead(
        self,
        user: User,
        original_outfit_id: UUID,
        item_ids: list[UUID],
        rating: int | None,
        comment: str | None,
        scheduled_for: date | None,
    ) -> Outfit:
        result = await self.db.execute(
            select(Outfit)
            .where(and_(Outfit.id == original_outfit_id, Outfit.user_id == user.id))
            .options(selectinload(Outfit.feedback))
            .with_for_update()
        )
        original = result.scalar_one_or_none()
        if original is None:
            raise LookupError("original outfit not found")

        existing_result = await self.db.execute(
            select(Outfit)
            .where(Outfit.replaces_outfit_id == original.id)
            .options(
                selectinload(Outfit.items).selectinload(OutfitItem.item),
                selectinload(Outfit.feedback),
            )
        )
        existing_replacement = existing_result.scalar_one_or_none()
        if existing_replacement is not None:
            return existing_replacement

        items = await validate_item_ownership(self.db, user.id, item_ids)
        ordered = self._order_items_canonically(items)

        effective_date = scheduled_for or original.scheduled_for

        replacement = Outfit(
            user_id=user.id,
            occasion=original.occasion,
            scheduled_for=effective_date,
            source=OutfitSource.manual,
            status=OutfitStatus.pending,
            replaces_outfit_id=original.id,
        )
        self.db.add(replacement)
        await self.db.flush()

        for pos, item in enumerate(ordered):
            self.db.add(OutfitItem(outfit_id=replacement.id, item_id=item.id, position=pos))

        feedback = self.learning.create_synthetic_feedback(
            outfit_id=replacement.id,
            accepted=True,
            worn_at=effective_date,
            rating=rating,
            comment=comment,
        )
        self.db.add(feedback)

        original.status = OutfitStatus.rejected
        original.responded_at = datetime.utcnow()

        if effective_date is not None:
            await ItemService(self.db).record_wears(
                user.id,
                [i.id for i in ordered],
                effective_date,
                occasion=replacement.occasion,
                outfit_id=replacement.id,
            )

        await self.db.flush()
        return await self._reload_outfit(replacement.id)

    async def clone_to_lookbook(
        self,
        user: User,
        source_outfit_id: UUID,
        name: str,
    ) -> Outfit:
        result = await self.db.execute(
            select(Outfit)
            .where(and_(Outfit.id == source_outfit_id, Outfit.user_id == user.id))
            .options(selectinload(Outfit.items).selectinload(OutfitItem.item))
        )
        source = result.scalar_one_or_none()
        if source is None:
            raise LookupError("source outfit not found")

        recent_cutoff = datetime.now(UTC) - timedelta(seconds=self.CLONE_SOFT_IDEMPOTENCY_SECONDS)
        recent_result = await self.db.execute(
            select(Outfit)
            .where(
                and_(
                    Outfit.user_id == user.id,
                    Outfit.cloned_from_outfit_id == source.id,
                    Outfit.scheduled_for.is_(None),
                    Outfit.created_at >= recent_cutoff,
                )
            )
            .options(
                selectinload(Outfit.items).selectinload(OutfitItem.item),
                selectinload(Outfit.feedback),
            )
        )
        existing = recent_result.scalar_one_or_none()
        if existing is not None:
            return existing

        clone = Outfit(
            user_id=user.id,
            occasion=source.occasion,
            scheduled_for=None,
            source=OutfitSource.manual,
            status=OutfitStatus.pending,
            cloned_from_outfit_id=source.id,
            source_item_id=source.source_item_id,
            name=name,
        )
        self.db.add(clone)
        await self.db.flush()

        for oi in sorted(source.items, key=lambda x: x.position):
            self.db.add(
                OutfitItem(
                    outfit_id=clone.id,
                    item_id=oi.item_id,
                    position=oi.position,
                    layer_type=oi.layer_type,
                )
            )

        feedback = self.learning.create_synthetic_feedback(
            outfit_id=clone.id, accepted=True, worn_at=None
        )
        self.db.add(feedback)

        await self.db.flush()
        return await self._reload_outfit(clone.id)

    async def wear_today(
        self,
        user: User,
        template_id: UUID,
        scheduled_for: date | None,
        swaps: dict[UUID, UUID] | None = None,
    ) -> Outfit:
        result = await self.db.execute(
            select(Outfit)
            .where(and_(Outfit.id == template_id, Outfit.user_id == user.id))
            .options(selectinload(Outfit.items).selectinload(OutfitItem.item))
        )
        template = result.scalar_one_or_none()
        if template is None:
            raise LookupError("template not found")

        if template.scheduled_for is not None:
            raise OutfitNotTemplateError("wear_today requires a lookbook template")

        # Each swap must name one of the template's alternates for that item
        swaps = swaps or {}
        allowed = {(a.item_id, a.alternate_item_id) for a in template.alternates}
        for item_id, alternate_id in swaps.items():
            if (item_id, alternate_id) not in allowed:
                raise InvalidAlternateError(
                    f"{alternate_id} is not an alternate for {item_id} in this outfit"
                )

        target_date = scheduled_for if scheduled_for is not None else get_user_today(user)

        wear = Outfit(
            user_id=user.id,
            occasion=template.occasion,
            scheduled_for=target_date,
            source=OutfitSource.manual,
            status=OutfitStatus.pending,
            cloned_from_outfit_id=template.id,
            source_item_id=template.source_item_id,
            name=template.name,
        )
        self.db.add(wear)
        await self.db.flush()

        worn_item_ids = []
        for oi in sorted(template.items, key=lambda x: x.position):
            worn_id = swaps.get(oi.item_id, oi.item_id)
            worn_item_ids.append(worn_id)
            self.db.add(
                OutfitItem(
                    outfit_id=wear.id,
                    item_id=worn_id,
                    position=oi.position,
                    layer_type=oi.layer_type,
                )
            )

        feedback = self.learning.create_synthetic_feedback(
            outfit_id=wear.id, accepted=True, worn_at=target_date
        )
        self.db.add(feedback)

        await ItemService(self.db).record_wears(
            user.id,
            worn_item_ids,
            target_date,
            occasion=wear.occasion,
            outfit_id=wear.id,
        )

        await self.db.flush()
        return await self._reload_outfit(wear.id)

    async def patch_outfit(
        self,
        user: User,
        outfit_id: UUID,
        name: str | None,
        items: list[UUID] | None,
        tags: list[str] | None = None,
        alternates: dict[UUID, list[UUID]] | None = None,
    ) -> Outfit:
        result = await self.db.execute(
            select(Outfit)
            .where(and_(Outfit.id == outfit_id, Outfit.user_id == user.id))
            .options(
                selectinload(Outfit.items).selectinload(OutfitItem.item),
                selectinload(Outfit.feedback),
            )
        )
        outfit = result.scalar_one_or_none()
        if outfit is None:
            raise LookupError("outfit not found")

        if name is not None:
            outfit.name = name

        if tags is not None:
            outfit.tags = tags

        if items is not None:
            if outfit.feedback is not None and outfit.feedback.worn_at is not None:
                raise OutfitWornImmutableError("cannot modify items on a worn outfit")

            new_items = await validate_item_ownership(self.db, user.id, items)
            ordered = self._order_items_canonically(new_items)

            old_item_ids = [oi.item_id for oi in outfit.items]
            new_item_ids = [i.id for i in ordered]

            old_pairs = {tuple(sorted([a, b])) for a, b in combinations(old_item_ids, 2)}
            new_pairs = {tuple(sorted([a, b])) for a, b in combinations(new_item_ids, 2)}
            added = new_pairs - old_pairs
            removed = old_pairs - new_pairs

            self.db.expire(outfit, attribute_names=["items"])
            await self.db.execute(sa_delete(OutfitItem).where(OutfitItem.outfit_id == outfit.id))
            await self.db.flush()

            for pos, item in enumerate(ordered):
                self.db.add(OutfitItem(outfit_id=outfit.id, item_id=item.id, position=pos))
            await self.db.flush()

            refreshed = await self._reload_outfit(outfit.id)
            if added or removed:
                await self.learning.process_item_diff(refreshed, removed_pairs=removed)
            outfit = refreshed

            if alternates is None:
                # Keep the alternates whose item is still in the outfit and that are not in it
                alternates = {}
                for alt in outfit.alternates:
                    if alt.item_id in new_item_ids and alt.alternate_item_id not in new_item_ids:
                        alternates.setdefault(alt.item_id, []).append(alt.alternate_item_id)

        if alternates is not None:
            await self._replace_alternates(user, outfit, alternates)

        await self.db.flush()
        return await self._reload_outfit(outfit.id)

    async def _replace_alternates(
        self, user: User, outfit: Outfit, alternates: dict[UUID, list[UUID]]
    ) -> None:
        if outfit.feedback is not None and outfit.feedback.worn_at is not None:
            raise OutfitWornImmutableError("cannot modify alternates on a worn outfit")

        outfit_item_ids = {oi.item_id for oi in outfit.items}
        rows: list[tuple[UUID, UUID, int]] = []
        for item_id, alternate_ids in alternates.items():
            if item_id not in outfit_item_ids:
                raise InvalidAlternateError(f"{item_id} is not an item of this outfit")
            unique = list(dict.fromkeys(alternate_ids))
            for alternate_id in unique:
                if alternate_id in outfit_item_ids:
                    raise InvalidAlternateError(f"{alternate_id} is already in this outfit")
            rows.extend((item_id, alt, pos) for pos, alt in enumerate(unique))

        alternate_ids = list({alt for _, alt, _ in rows})
        if alternate_ids:
            await validate_item_ownership(self.db, user.id, alternate_ids)

        await self.db.execute(
            sa_delete(OutfitItemAlternate).where(OutfitItemAlternate.outfit_id == outfit.id)
        )
        self.db.expire(outfit, attribute_names=["alternates"])
        await self.db.flush()
        for item_id, alternate_id, pos in rows:
            self.db.add(
                OutfitItemAlternate(
                    outfit_id=outfit.id,
                    item_id=item_id,
                    alternate_item_id=alternate_id,
                    position=pos,
                )
            )
        await self.db.flush()
