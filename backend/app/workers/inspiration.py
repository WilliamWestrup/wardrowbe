"""Analyze an inspiration look's photo garment by garment, then match the garments
against the wardrobe. Adapted from lindawal/wardrowbe (MIT)."""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from arq import Retry
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.inspiration import InspirationGarment, InspirationLook, InspirationStatus
from app.models.preference import UserPreference
from app.models.user import User
from app.services.ai_service import AIService, repeats_identically
from app.services.inspiration_matching_service import load_wardrobe, match_garments
from app.utils.locale import DEFAULT_LOCALE
from app.workers.db import get_db_session
from app.workers.tagging import _is_final_attempt, _tagging_call_budget, retry_delay_seconds

logger = logging.getLogger(__name__)

# The garment fields an analysis writes, straight from ClothingTags.
_GARMENT_FIELDS = (
    "type",
    "subtype",
    "primary_color",
    "colors",
    "pattern",
    "material",
    "style",
    "formality",
    "season",
    "fit",
    "description",
    "confidence",
)


class InspirationLookVanishedError(Exception):
    """The look is not visible to this worker's connection: either the producing request
    has not committed yet (retry), or the look was deleted (the retry then gives up)."""


async def _set_status(
    ctx: dict, look_id: str, status: InspirationStatus, error: str | None = None
) -> None:
    db = get_db_session(ctx)
    try:
        look = await db.get(InspirationLook, UUID(look_id))
        # Guarded so a late write never clobbers a look that already finished.
        if look is not None and look.status in (
            InspirationStatus.pending,
            InspirationStatus.analyzing,
        ):
            look.status = status
            look.error_message = error
            await db.commit()
    finally:
        await db.close()


async def _load_look(db, look_id: str) -> InspirationLook:
    result = await db.execute(
        select(InspirationLook)
        .options(selectinload(InspirationLook.garments))
        .where(InspirationLook.id == UUID(look_id))
        .execution_options(populate_existing=True)
    )
    look = result.scalar_one_or_none()
    if look is None:
        raise InspirationLookVanishedError(f"Look {look_id} not visible to worker")
    return look


async def analyze_inspiration_look(ctx: dict, look_id: str, image_path: str) -> dict[str, Any]:
    """Replace the look's garments with what the AI sees, then match them.

    A matching failure is logged and leaves the look unmatched (the UI offers a re-match)
    instead of failing the job, since a retry would redo the AI call for database work.
    When the AI gives up, the look is marked `error` and stays fully usable: the owner can
    add garments by hand.
    """
    logger.info(f"Starting AI analysis for inspiration look {look_id}")

    if not get_settings().effective_ai_vision_enabled:
        await _set_status(ctx, look_id, InspirationStatus.skipped)
        return {"status": "skipped", "reason": "vision disabled", "look_id": look_id}

    path = Path(image_path)
    if not path.exists():
        await _set_status(ctx, look_id, InspirationStatus.error, "Image not found")
        return {"status": "error", "error": "Image not found"}

    try:
        ai_endpoints = None
        locale = DEFAULT_LOCALE
        db = get_db_session(ctx)
        try:
            look = await _load_look(db, look_id)
            if look.status not in (InspirationStatus.pending, InspirationStatus.analyzing):
                # Photo replaced or analysis already finished: this job is stale.
                return {"status": "skipped", "reason": "stale", "look_id": look_id}
            locale = (
                await db.scalar(select(User.locale).where(User.id == look.user_id))
            ) or DEFAULT_LOCALE
            prefs = await db.scalar(
                select(UserPreference).where(UserPreference.user_id == look.user_id)
            )
            if prefs and prefs.ai_endpoints:
                ai_endpoints = prefs.ai_endpoints
            look.status = InspirationStatus.analyzing
            look.error_message = None
            await db.commit()
        finally:
            await db.close()

        ai_service = AIService(endpoints=ai_endpoints)
        found = await asyncio.wait_for(
            ai_service.analyze_look(path, locale=locale),
            timeout=_tagging_call_budget(ai_service),
        )
        logger.info(f"AI analysis for look {look_id}: {len(found)} garment(s)")

        db = get_db_session(ctx)
        try:
            look = await _load_look(db, look_id)
            if not image_path.endswith(look.photo_path):
                return {"status": "skipped", "reason": "photo replaced", "look_id": look_id}
            look.garments.clear()
            for position, tags in enumerate(found):
                look.garments.append(
                    InspirationGarment(
                        position=position,
                        **{field: getattr(tags, field) for field in _GARMENT_FIELDS},
                    )
                )
            look.matched_at = None
            await db.flush()

            matched = True
            try:
                # Read-only, in a savepoint so a failure leaves the transaction usable.
                async with db.begin_nested():
                    wardrobe = await load_wardrobe(db, look.user_id)
            except Exception:
                matched = False
                logger.exception(f"Wardrobe matching failed for inspiration look {look_id}")
            else:
                match_garments(look.garments, wardrobe)
                look.matched_at = datetime.now(UTC)

            look.status = InspirationStatus.analyzed
            look.error_message = None
            await db.commit()
        finally:
            await db.close()

        return {
            "status": "success",
            "look_id": look_id,
            "garment_count": len(found),
            "matched": matched,
        }

    except asyncio.CancelledError:
        raise
    except Exception as e:
        error_msg = str(e)[:500]
        logger.exception(f"Error analyzing inspiration look {look_id}: {error_msg}")
        # arq books a returned value as success, so a failure has to Retry to be retried.
        if _is_final_attempt(ctx) or repeats_identically(e):
            await _set_status(ctx, look_id, InspirationStatus.error, error_msg)
            raise
        raise Retry(defer=retry_delay_seconds(ctx)) from e
