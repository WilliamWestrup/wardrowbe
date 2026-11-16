"""Shopping list (wardrobe gaps) and declutter suggestions.

Built to be written by an external agent and read by the owner. Product links and prices
are stored as sent; nothing here fetches a URL. Marking a declutter suggestion done only
records the decision: archiving an item stays a separate action in the wardrobe.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import DbSession
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
from app.models.user import User
from app.schemas.outfit import MAX_OUTFIT_TAGS
from app.schemas.shopping import (
    DeclutterBulkCreate,
    DeclutterCreate,
    DeclutterListResponse,
    DeclutterResponse,
    DeclutterUpdate,
    ItemSummary,
    LookSummary,
    WardrobeGapBulkCreate,
    WardrobeGapCreate,
    WardrobeGapListResponse,
    WardrobeGapResponse,
    WardrobeGapUpdate,
)
from app.services.shopping_service import (
    DeclutterAlreadyOpenError,
    DeclutterFilters,
    GapFilters,
    ShoppingReferenceError,
    ShoppingService,
)
from app.utils.auth import get_current_user
from app.utils.signed_urls import sign_optional

router = APIRouter(prefix="/shopping", tags=["Shopping"])

CurrentUser = Annotated[User, Depends(get_current_user)]


def _item_summary(item: ClothingItem) -> ItemSummary:
    return ItemSummary(
        id=item.id,
        name=item.name,
        type=item.type,
        primary_color=item.primary_color,
        thumbnail_url=sign_optional(item.thumbnail_path, item.image_path),
        is_archived=bool(item.is_archived),
    )


def _look_summary(look: InspirationLook) -> LookSummary:
    return LookSummary(
        id=look.id,
        title=look.title,
        thumbnail_url=sign_optional(look.photo_thumbnail_path, look.photo_path),
    )


async def _gap_responses(
    service: ShoppingService, user_id: UUID, gaps: list[WardrobeGap]
) -> list[WardrobeGapResponse]:
    """Resolve every reference in one query per kind. pairs_with keeps only usable items
    (own, not archived); the bought item is shown even once archived."""
    pair_ids = {i for gap in gaps for i in gap.pairs_with_item_ids or []}
    bought_ids = {gap.bought_item_id for gap in gaps if gap.bought_item_id is not None}
    items = await service.owned_items(user_id, pair_ids | bought_ids, include_archived=True)
    looks = await service.owned_looks(
        user_id, {i for gap in gaps for i in gap.inspiration_look_ids or []}
    )
    responses = []
    for gap in gaps:
        bought = items.get(gap.bought_item_id) if gap.bought_item_id else None
        responses.append(
            WardrobeGapResponse(
                id=gap.id,
                title=gap.title,
                type=gap.type,
                priority=gap.priority,
                status=gap.status,
                reason=gap.reason,
                look_for=gap.look_for,
                avoid=gap.avoid,
                size=gap.size,
                notes=gap.notes,
                tags=gap.tags or [],
                pairs_with_item_ids=gap.pairs_with_item_ids or [],
                inspiration_look_ids=gap.inspiration_look_ids or [],
                bought_item_id=gap.bought_item_id,
                products=gap.products or [],
                position=gap.position,
                created_at=gap.created_at,
                updated_at=gap.updated_at,
                pairs_with=[
                    _item_summary(items[i])
                    for i in gap.pairs_with_item_ids or []
                    if i in items and not items[i].is_archived
                ],
                inspiration_looks=[
                    _look_summary(looks[i]) for i in gap.inspiration_look_ids or [] if i in looks
                ],
                bought_item=_item_summary(bought) if bought is not None else None,
            )
        )
    return responses


async def _declutter_responses(
    service: ShoppingService, user_id: UUID, suggestions: list[DeclutterSuggestion]
) -> list[DeclutterResponse]:
    items = await service.owned_items(
        user_id, {s.item_id for s in suggestions}, include_archived=True
    )
    return [
        DeclutterResponse(
            id=s.id,
            item_id=s.item_id,
            action=s.action,
            reason=s.reason,
            status=s.status,
            notes=s.notes,
            created_at=s.created_at,
            updated_at=s.updated_at,
            item=_item_summary(items[s.item_id]),
        )
        for s in suggestions
        if s.item_id in items
    ]


def _not_found(error_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error_code": error_code, "message": message},
    )


def _reference_error(e: ShoppingReferenceError) -> HTTPException:
    return _not_found(e.error_code, e.message)


def _already_open(e: DeclutterAlreadyOpenError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error_code": "DECLUTTER_ALREADY_OPEN",
            "message": f"Item {e.item_id} already has an open declutter suggestion",
        },
    )


def _no_fields() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error_code": "NO_FIELDS", "message": "No fields to update"},
    )


def _parse_tags(tags: str | None) -> tuple[str, ...]:
    tag_list = tuple(dict.fromkeys(t.strip().lower() for t in (tags or "").split(",") if t.strip()))
    if len(tag_list) > MAX_OUTFIT_TAGS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Too many tags")
    return tag_list


async def _get_gap_or_404(service: ShoppingService, gap_id: UUID, user_id: UUID) -> WardrobeGap:
    gap = await service.get_gap(gap_id, user_id)
    if gap is None:
        raise _not_found("WARDROBE_GAP_NOT_FOUND", "Shopping list entry not found")
    return gap


async def _get_suggestion_or_404(
    service: ShoppingService, suggestion_id: UUID, user_id: UUID
) -> DeclutterSuggestion:
    suggestion = await service.get_suggestion(suggestion_id, user_id)
    if suggestion is None:
        raise _not_found("DECLUTTER_SUGGESTION_NOT_FOUND", "Declutter suggestion not found")
    return suggestion


# --- gaps ---------------------------------------------------------------------------------


@router.get("/gaps", response_model=WardrobeGapListResponse)
async def list_gaps(
    db: DbSession,
    current_user: CurrentUser,
    status_: GapStatus | None = Query(None, alias="status"),
    priority: GapPriority | None = Query(None),
    tags: str | None = Query(None, description="Comma-separated; gaps carrying all of them"),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> WardrobeGapListResponse:
    """Ordered by priority (high first), then position, then creation."""
    service = ShoppingService(db)
    filters = GapFilters(status=status_, priority=priority, tags=_parse_tags(tags))
    gaps, total = await service.list_gaps(current_user.id, filters, limit, offset)
    return WardrobeGapListResponse(
        gaps=await _gap_responses(service, current_user.id, gaps), total=total
    )


@router.post("/gaps", response_model=WardrobeGapResponse, status_code=status.HTTP_201_CREATED)
async def create_gap(
    request: WardrobeGapCreate, db: DbSession, current_user: CurrentUser
) -> WardrobeGapResponse:
    service = ShoppingService(db)
    try:
        gaps = await service.create_gaps(current_user.id, [request.changes()])
    except ShoppingReferenceError as e:
        raise _reference_error(e) from None
    return (await _gap_responses(service, current_user.id, gaps))[0]


@router.post(
    "/gaps/bulk", response_model=WardrobeGapListResponse, status_code=status.HTTP_201_CREATED
)
async def bulk_create_gaps(
    request: WardrobeGapBulkCreate, db: DbSession, current_user: CurrentUser
) -> WardrobeGapListResponse:
    """Create up to 50 gaps. If any one is invalid, none is created."""
    service = ShoppingService(db)
    try:
        gaps = await service.create_gaps(
            current_user.id, [g.changes() for g in request.gaps], bulk=True
        )
    except ShoppingReferenceError as e:
        raise _reference_error(e) from None
    return WardrobeGapListResponse(
        gaps=await _gap_responses(service, current_user.id, gaps), total=len(gaps)
    )


@router.get("/gaps/{gap_id}", response_model=WardrobeGapResponse)
async def get_gap(gap_id: UUID, db: DbSession, current_user: CurrentUser) -> WardrobeGapResponse:
    service = ShoppingService(db)
    gap = await _get_gap_or_404(service, gap_id, current_user.id)
    return (await _gap_responses(service, current_user.id, [gap]))[0]


@router.patch("/gaps/{gap_id}", response_model=WardrobeGapResponse)
async def update_gap(
    gap_id: UUID, request: WardrobeGapUpdate, db: DbSession, current_user: CurrentUser
) -> WardrobeGapResponse:
    service = ShoppingService(db)
    gap = await _get_gap_or_404(service, gap_id, current_user.id)
    updates = request.changes()
    if not updates:
        raise _no_fields()
    try:
        gap = await service.update_gap(gap, updates)
    except ShoppingReferenceError as e:
        raise _reference_error(e) from None
    return (await _gap_responses(service, current_user.id, [gap]))[0]


@router.delete("/gaps/{gap_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gap(gap_id: UUID, db: DbSession, current_user: CurrentUser) -> None:
    service = ShoppingService(db)
    gap = await _get_gap_or_404(service, gap_id, current_user.id)
    await service.delete_gap(gap)


# --- declutter ----------------------------------------------------------------------------


@router.get("/declutter", response_model=DeclutterListResponse)
async def list_declutter(
    db: DbSession,
    current_user: CurrentUser,
    status_: DeclutterStatus | None = Query(None, alias="status"),
    action: DeclutterAction | None = Query(None),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> DeclutterListResponse:
    """Newest first."""
    service = ShoppingService(db)
    suggestions, total = await service.list_suggestions(
        current_user.id, DeclutterFilters(status=status_, action=action), limit, offset
    )
    return DeclutterListResponse(
        suggestions=await _declutter_responses(service, current_user.id, suggestions),
        total=total,
    )


@router.post("/declutter", response_model=DeclutterResponse, status_code=status.HTTP_201_CREATED)
async def create_declutter(
    request: DeclutterCreate, db: DbSession, current_user: CurrentUser
) -> DeclutterResponse:
    service = ShoppingService(db)
    try:
        suggestions = await service.create_suggestions(current_user.id, [request.model_dump()])
    except ShoppingReferenceError as e:
        raise _reference_error(e) from None
    except DeclutterAlreadyOpenError as e:
        raise _already_open(e) from None
    return (await _declutter_responses(service, current_user.id, suggestions))[0]


@router.post(
    "/declutter/bulk", response_model=DeclutterListResponse, status_code=status.HTTP_201_CREATED
)
async def bulk_create_declutter(
    request: DeclutterBulkCreate, db: DbSession, current_user: CurrentUser
) -> DeclutterListResponse:
    """Create up to 50 suggestions. If any one is invalid, none is created."""
    service = ShoppingService(db)
    try:
        suggestions = await service.create_suggestions(
            current_user.id, [s.model_dump() for s in request.suggestions], bulk=True
        )
    except ShoppingReferenceError as e:
        raise _reference_error(e) from None
    except DeclutterAlreadyOpenError as e:
        raise _already_open(e) from None
    return DeclutterListResponse(
        suggestions=await _declutter_responses(service, current_user.id, suggestions),
        total=len(suggestions),
    )


@router.get("/declutter/{suggestion_id}", response_model=DeclutterResponse)
async def get_declutter(
    suggestion_id: UUID, db: DbSession, current_user: CurrentUser
) -> DeclutterResponse:
    service = ShoppingService(db)
    suggestion = await _get_suggestion_or_404(service, suggestion_id, current_user.id)
    return (await _declutter_responses(service, current_user.id, [suggestion]))[0]


@router.patch("/declutter/{suggestion_id}", response_model=DeclutterResponse)
async def update_declutter(
    suggestion_id: UUID, request: DeclutterUpdate, db: DbSession, current_user: CurrentUser
) -> DeclutterResponse:
    service = ShoppingService(db)
    suggestion = await _get_suggestion_or_404(service, suggestion_id, current_user.id)
    updates = request.model_dump(exclude_unset=True)
    if not updates:
        raise _no_fields()
    try:
        suggestion = await service.update_suggestion(suggestion, updates)
    except DeclutterAlreadyOpenError as e:
        raise _already_open(e) from None
    return (await _declutter_responses(service, current_user.id, [suggestion]))[0]


@router.delete("/declutter/{suggestion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_declutter(suggestion_id: UUID, db: DbSession, current_user: CurrentUser) -> None:
    service = ShoppingService(db)
    suggestion = await _get_suggestion_or_404(service, suggestion_id, current_user.id)
    await service.delete_suggestion(suggestion)
