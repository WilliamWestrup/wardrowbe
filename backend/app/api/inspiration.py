"""Inspiration looks: save an outfit photo seen elsewhere, vote and tag it, note why it
works, break it down into garments and link them to pieces in the wardrobe.

The garment analysis and wardrobe matching are adapted from lindawal/wardrowbe (MIT).
source_url is stored and shown as a link only; nothing here fetches it.
"""

import logging
from typing import Annotated
from uuid import UUID

from arq import create_pool
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import ValidationError

from app.config import get_settings
from app.database import DbSession
from app.models.inspiration import (
    InspirationGarment,
    InspirationLook,
    InspirationStatus,
    InspirationVote,
)
from app.models.item import ClothingItem
from app.models.user import User
from app.schemas.inspiration import (
    InspirationGarmentCreate,
    InspirationGarmentResponse,
    InspirationGarmentUpdate,
    InspirationLookListResponse,
    InspirationLookResponse,
    InspirationLookUpdate,
    InspirationMatchRequest,
    WardrobeItemSummary,
)
from app.schemas.outfit import MAX_OUTFIT_TAGS
from app.services.image_service import ImageService
from app.services.inspiration_service import (
    ANALYSIS_RUNNING,
    InspirationAnalysisRunningError,
    InspirationGarmentNotFoundError,
    InspirationListFilters,
    InspirationService,
    WardrobeItemUnavailableError,
    wardrobe_ids_for_garments,
)
from app.utils.auth import get_current_user
from app.utils.rate_limit import rate_limit_by_user
from app.utils.signed_urls import sign_optional
from app.utils.uploads import UploadTooLargeError, read_upload_within_limit
from app.workers.queues import TAGGING_QUEUE
from app.workers.settings import get_redis_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inspiration", tags=["Inspiration"])

CurrentUser = Annotated[User, Depends(get_current_user)]
WardrobeMap = dict[UUID, ClothingItem]


def _wardrobe_summary(item: ClothingItem) -> WardrobeItemSummary:
    return WardrobeItemSummary(
        id=item.id,
        type=item.type,
        subtype=item.subtype,
        name=item.name,
        primary_color=item.primary_color,
        image_url=sign_optional(item.medium_path or item.image_path),
        thumbnail_url=sign_optional(item.thumbnail_path),
    )


def garment_to_response(
    garment: InspirationGarment, wardrobe: WardrobeMap | None = None
) -> InspirationGarmentResponse:
    matched = None
    suggested: list[WardrobeItemSummary] = []
    if wardrobe is not None:
        if garment.matched_item_id in wardrobe:
            matched = _wardrobe_summary(wardrobe[garment.matched_item_id])
        suggested = [
            _wardrobe_summary(wardrobe[iid])
            for iid in garment.suggested_item_ids or []
            if iid in wardrobe
        ]
    return InspirationGarmentResponse(
        id=garment.id,
        position=garment.position,
        type=garment.type,
        subtype=garment.subtype,
        primary_color=garment.primary_color,
        colors=garment.colors or [],
        pattern=garment.pattern,
        material=garment.material,
        style=garment.style or [],
        formality=garment.formality,
        season=garment.season or [],
        fit=garment.fit,
        description=garment.description,
        confidence=garment.confidence,
        matched_item_id=garment.matched_item_id,
        matched_item=matched,
        suggested_items=suggested,
    )


def look_to_response(
    look: InspirationLook, wardrobe: WardrobeMap | None = None, *, with_garments: bool = True
) -> InspirationLookResponse:
    garments = sorted(look.garments, key=lambda g: g.position)
    return InspirationLookResponse(
        id=look.id,
        title=look.title,
        source_url=look.source_url,
        vote=look.vote,
        tags=look.tags or [],
        notes=look.notes,
        status=look.status,
        error_message=look.error_message,
        photo_url=sign_optional(look.photo_path),
        photo_medium_url=sign_optional(look.photo_medium_path or look.photo_path),
        photo_thumbnail_url=sign_optional(look.photo_thumbnail_path),
        matched_at=look.matched_at,
        created_at=look.created_at,
        updated_at=look.updated_at,
        garment_count=len(garments),
        garments=[garment_to_response(g, wardrobe) for g in garments] if with_garments else [],
    )


async def _full_response(
    service: InspirationService, look: InspirationLook
) -> InspirationLookResponse:
    wardrobe = await service.usable_wardrobe_items(
        look.user_id, wardrobe_ids_for_garments(look.garments)
    )
    return look_to_response(look, wardrobe)


async def _garment_response(
    service: InspirationService, look: InspirationLook, garment: InspirationGarment
) -> InspirationGarmentResponse:
    wardrobe = await service.usable_wardrobe_items(
        look.user_id, wardrobe_ids_for_garments([garment])
    )
    return garment_to_response(garment, wardrobe)


def _not_found(error_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error_code": error_code, "message": message},
    )


def _analysis_running() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error_code": "INSPIRATION_ANALYSIS_RUNNING",
            "message": "Wait for the analysis to finish before editing garments",
        },
    )


async def _get_look_or_404(
    service: InspirationService, look_id: UUID, user_id: UUID
) -> InspirationLook:
    look = await service.get_look(look_id, user_id)
    if look is None:
        raise _not_found("INSPIRATION_LOOK_NOT_FOUND", "Inspiration look not found")
    return look


async def _store_photo(image: UploadFile, user: User, image_service: ImageService) -> dict:
    """Validate and store an upload. ImageService re-encodes it as JPEG, which drops EXIF
    metadata such as GPS location."""
    try:
        content = await read_upload_within_limit(image, get_settings().max_upload_size_mb)
    except UploadTooLargeError as e:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(e)) from None
    if not image_service.validate_image(content, image.content_type or "application/octet-stream"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image file. Supported formats: JPEG, PNG, WebP, HEIC",
        )
    try:
        return await image_service.process_and_store(
            user_id=user.id,
            image_data=content,
            original_filename=image.filename or "upload.jpg",
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from None


def _initial_status() -> InspirationStatus:
    if get_settings().effective_ai_vision_enabled:
        return InspirationStatus.pending
    return InspirationStatus.skipped


async def _enqueue_analysis(
    service: InspirationService, look: InspirationLook, image_service: ImageService
) -> None:
    """Queue the AI analysis for a committed `pending` look. If queueing fails the look is
    marked `error`, which still lets the owner add garments by hand or retry."""
    if look.status != InspirationStatus.pending:
        return
    try:
        redis = await create_pool(get_redis_settings())
        try:
            await redis.enqueue_job(
                "analyze_inspiration_look",
                str(look.id),
                str(image_service.get_image_path(look.photo_path)),
                _queue_name=TAGGING_QUEUE,
            )
        finally:
            await redis.aclose()
    except Exception as e:
        logger.error(f"Failed to queue analysis for inspiration look {look.id}: {e}")
        await service.update_look(
            look,
            {"status": InspirationStatus.error, "error_message": "Could not queue the analysis"},
        )


def _parse_form_fields(
    title: str | None,
    source_url: str | None,
    notes: str | None,
    vote: str | None,
    tags: str | None,
) -> dict:
    raw: dict = {"title": title, "source_url": source_url, "notes": notes}
    if vote:
        raw["vote"] = vote
    if tags:
        raw["tags"] = [t for t in tags.split(",") if t.strip()]
    try:
        return InspirationLookUpdate(**raw).model_dump(exclude_none=True)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=e.errors(include_url=False, include_context=False, include_input=False),
        ) from None


@router.post("", response_model=InspirationLookResponse, status_code=status.HTTP_201_CREATED)
async def create_inspiration_look(
    db: DbSession,
    current_user: CurrentUser,
    image: UploadFile = File(...),
    title: str | None = Form(None),
    source_url: str | None = Form(None),
    notes: str | None = Form(None),
    vote: str | None = Form(None),
    tags: str | None = Form(None, description="Comma-separated situation tags"),
) -> InspirationLookResponse:
    await rate_limit_by_user(
        str(current_user.id), "inspiration_upload", max_requests=20, window_seconds=60
    )
    fields = _parse_form_fields(title, source_url, notes, vote, tags)
    image_service = ImageService()
    service = InspirationService(db, image_service)
    stored = await _store_photo(image, current_user, image_service)
    look = await service.create_look(current_user.id, stored, fields, _initial_status())
    await _enqueue_analysis(service, look, image_service)
    return await _full_response(service, look)


@router.get("", response_model=InspirationLookListResponse)
async def list_inspiration_looks(
    db: DbSession,
    current_user: CurrentUser,
    vote: InspirationVote | None = Query(None),
    tags: str | None = Query(None, description="Comma-separated; looks carrying all of them"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> InspirationLookListResponse:
    tag_list = tuple(dict.fromkeys(t.strip().lower() for t in (tags or "").split(",") if t.strip()))
    if len(tag_list) > MAX_OUTFIT_TAGS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Too many tags")
    service = InspirationService(db, ImageService())
    looks, total = await service.list_looks(
        current_user.id, InspirationListFilters(vote=vote, tags=tag_list), limit, offset
    )
    # Matches aren't resolved here: the grid only shows photos, votes and tags.
    return InspirationLookListResponse(
        looks=[look_to_response(look, with_garments=False) for look in looks], total=total
    )


@router.get("/{look_id}", response_model=InspirationLookResponse)
async def get_inspiration_look(
    look_id: UUID, db: DbSession, current_user: CurrentUser
) -> InspirationLookResponse:
    service = InspirationService(db, ImageService())
    look = await _get_look_or_404(service, look_id, current_user.id)
    return await _full_response(service, look)


@router.patch("/{look_id}", response_model=InspirationLookResponse)
async def update_inspiration_look(
    look_id: UUID, request: InspirationLookUpdate, db: DbSession, current_user: CurrentUser
) -> InspirationLookResponse:
    service = InspirationService(db, ImageService())
    look = await _get_look_or_404(service, look_id, current_user.id)
    await service.update_look(look, request.model_dump(exclude_unset=True))
    return await _full_response(service, look)


@router.put("/{look_id}/photo", response_model=InspirationLookResponse)
async def replace_inspiration_photo(
    look_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
    image: UploadFile = File(...),
) -> InspirationLookResponse:
    """Replace the photo. Its garments described the old photo, so they are removed and
    the new one is analyzed again when the AI is on."""
    await rate_limit_by_user(
        str(current_user.id), "inspiration_upload", max_requests=20, window_seconds=60
    )
    image_service = ImageService()
    service = InspirationService(db, image_service)
    look = await _get_look_or_404(service, look_id, current_user.id)
    stored = await _store_photo(image, current_user, image_service)
    await service.replace_photo(look, stored, _initial_status())
    await _enqueue_analysis(service, look, image_service)
    return await _full_response(service, look)


@router.post("/{look_id}/analyze", response_model=InspirationLookResponse)
async def reanalyze_inspiration_look(
    look_id: UUID, db: DbSession, current_user: CurrentUser
) -> InspirationLookResponse:
    """Run the AI analysis again, e.g. after it failed. Replaces all garments."""
    if not get_settings().effective_ai_vision_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "AI_VISION_DISABLED", "message": "AI analysis is disabled"},
        )
    await rate_limit_by_user(
        str(current_user.id), "inspiration_analyze", max_requests=10, window_seconds=60
    )
    image_service = ImageService()
    service = InspirationService(db, image_service)
    look = await _get_look_or_404(service, look_id, current_user.id)
    if look.status in ANALYSIS_RUNNING:
        raise _analysis_running()
    await service.update_look(look, {"status": InspirationStatus.pending, "error_message": None})
    await _enqueue_analysis(service, look, image_service)
    return await _full_response(service, look)


@router.delete("/{look_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inspiration_look(look_id: UUID, db: DbSession, current_user: CurrentUser) -> None:
    service = InspirationService(db, ImageService())
    look = await _get_look_or_404(service, look_id, current_user.id)
    await service.delete_look(look)


@router.post(
    "/{look_id}/garments",
    response_model=InspirationGarmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_inspiration_garment(
    look_id: UUID, request: InspirationGarmentCreate, db: DbSession, current_user: CurrentUser
) -> InspirationGarmentResponse:
    service = InspirationService(db, ImageService())
    look = await _get_look_or_404(service, look_id, current_user.id)
    try:
        garment = await service.add_garment(look, request.changes())
    except InspirationAnalysisRunningError:
        raise _analysis_running() from None
    return await _garment_response(service, look, garment)


@router.patch("/{look_id}/garments/{garment_id}", response_model=InspirationGarmentResponse)
async def update_inspiration_garment(
    look_id: UUID,
    garment_id: UUID,
    request: InspirationGarmentUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> InspirationGarmentResponse:
    service = InspirationService(db, ImageService())
    look = await _get_look_or_404(service, look_id, current_user.id)
    updates = request.changes()
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "NO_FIELDS", "message": "No fields to update"},
        )
    try:
        garment = await service.update_garment(look, garment_id, updates)
    except InspirationGarmentNotFoundError:
        raise _not_found("INSPIRATION_GARMENT_NOT_FOUND", "Garment not found") from None
    except InspirationAnalysisRunningError:
        raise _analysis_running() from None
    return await _garment_response(service, look, garment)


@router.delete("/{look_id}/garments/{garment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inspiration_garment(
    look_id: UUID, garment_id: UUID, db: DbSession, current_user: CurrentUser
) -> None:
    service = InspirationService(db, ImageService())
    look = await _get_look_or_404(service, look_id, current_user.id)
    try:
        await service.delete_garment(look, garment_id)
    except InspirationGarmentNotFoundError:
        raise _not_found("INSPIRATION_GARMENT_NOT_FOUND", "Garment not found") from None
    except InspirationAnalysisRunningError:
        raise _analysis_running() from None


@router.put("/{look_id}/garments/{garment_id}/match", response_model=InspirationGarmentResponse)
async def set_inspiration_garment_match(
    look_id: UUID,
    garment_id: UUID,
    request: InspirationMatchRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> InspirationGarmentResponse:
    """Link a wardrobe item to the garment, or clear the link with null."""
    service = InspirationService(db, ImageService())
    look = await _get_look_or_404(service, look_id, current_user.id)
    try:
        garment = await service.set_match(look, garment_id, request.wardrobe_item_id)
    except InspirationGarmentNotFoundError:
        raise _not_found("INSPIRATION_GARMENT_NOT_FOUND", "Garment not found") from None
    except WardrobeItemUnavailableError:
        raise _not_found("WARDROBE_ITEM_NOT_FOUND", "Wardrobe item not found") from None
    return await _garment_response(service, look, garment)


@router.post("/{look_id}/match", response_model=InspirationLookResponse)
async def rematch_inspiration_look(
    look_id: UUID, db: DbSession, current_user: CurrentUser
) -> InspirationLookResponse:
    """Match every garment against the wardrobe as it is now. Resets manual links."""
    await rate_limit_by_user(
        str(current_user.id), "inspiration_match", max_requests=20, window_seconds=60
    )
    service = InspirationService(db, ImageService())
    look = await _get_look_or_404(service, look_id, current_user.id)
    try:
        look = await service.rematch_look(look)
    except InspirationAnalysisRunningError:
        raise _analysis_running() from None
    return await _full_response(service, look)
