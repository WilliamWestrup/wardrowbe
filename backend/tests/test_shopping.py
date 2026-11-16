from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inspiration import InspirationLook, InspirationStatus
from app.models.item import ClothingItem, ItemStatus
from app.models.shopping import DeclutterSuggestion, WardrobeGap
from app.models.user import User

BASE = "/api/v1/shopping"
GAPS = f"{BASE}/gaps"
DECLUTTER = f"{BASE}/declutter"


async def _other_user(db: AsyncSession) -> User:
    other = User(
        id=uuid4(),
        external_id=f"other-{uuid4()}",
        email=f"other-{uuid4()}@example.com",
        display_name="Other",
        timezone="UTC",
        is_active=True,
    )
    db.add(other)
    await db.commit()
    return other


async def _item(db: AsyncSession, user: User, type_: str = "jeans", **kw) -> ClothingItem:
    item = ClothingItem(
        user_id=user.id,
        type=type_,
        image_path=f"test/{uuid4()}.jpg",
        thumbnail_path=f"test/{uuid4()}_thumb.jpg",
        status=ItemStatus.ready,
        **kw,
    )
    db.add(item)
    await db.commit()
    return item


async def _look(db: AsyncSession, user: User, title: str | None = None) -> InspirationLook:
    look = InspirationLook(
        user_id=user.id,
        photo_path=f"test/{uuid4()}.jpg",
        title=title,
        status=InspirationStatus.skipped,
    )
    db.add(look)
    await db.commit()
    return look


def _product(**kw) -> dict:
    return {"name": "Example jacket", "store": "Example store", **kw}


async def _count(db: AsyncSession, model, user: User) -> int:
    return int(
        await db.scalar(select(func.count()).select_from(model).where(model.user_id == user.id))
    )


class TestGaps:
    @pytest.mark.asyncio
    async def test_create_with_everything_and_read_back(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        shirt = await _item(db_session, test_user, "shirt", name="White shirt")
        look = await _look(db_session, test_user, "Rainy day")
        resp = await client.post(
            GAPS,
            json={
                "title": "  Short rain jacket ",
                "type": "Jacket",
                "priority": "high",
                "reason": "Nothing for light rain",
                "look_for": "Hood, hip length",
                "avoid": "Shiny fabric",
                "size": "M",
                "tags": ["Rain", "casual"],
                "pairs_with_item_ids": [str(shirt.id), str(shirt.id)],
                "inspiration_look_ids": [str(look.id)],
                "products": [
                    _product(
                        url="https://shop.example.com/p/1",
                        price=49.9,
                        currency="eur",
                        checked_at="2026-11-16",
                    )
                ],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["title"] == "Short rain jacket"
        assert body["type"] == "jacket"
        assert body["priority"] == "high"
        assert body["status"] == "open"
        assert body["tags"] == ["casual", "rain"]
        assert body["pairs_with_item_ids"] == [str(shirt.id)]
        assert body["pairs_with"][0]["name"] == "White shirt"
        assert "sig=" in body["pairs_with"][0]["thumbnail_url"]
        assert body["inspiration_looks"][0]["title"] == "Rainy day"
        assert "sig=" in body["inspiration_looks"][0]["thumbnail_url"]
        product = body["products"][0]
        assert product["price"] == 49.9
        assert product["currency"] == "EUR"
        assert product["checked_at"] == "2026-11-16"

        resp = await client.get(f"{GAPS}/{body['id']}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["products"][0]["url"] == "https://shop.example.com/p/1"

    @pytest.mark.asyncio
    async def test_update_status_bought_item_and_clear_fields(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        gap = (
            await client.post(
                GAPS, json={"title": "Loafers", "notes": "brown"}, headers=auth_headers
            )
        ).json()
        bought = await _item(db_session, test_user, "shoes", is_archived=True)
        resp = await client.patch(
            f"{GAPS}/{gap['id']}",
            json={"status": "bought", "bought_item_id": str(bought.id), "notes": None},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "bought"
        assert body["bought_item"]["id"] == str(bought.id)
        assert body["notes"] is None

        for bad in ({"title": None}, {"status": None}, {"priority": "urgent"}, {"nope": 1}):
            resp = await client.patch(f"{GAPS}/{gap['id']}", json=bad, headers=auth_headers)
            assert resp.status_code == 422, bad
        resp = await client.patch(f"{GAPS}/{gap['id']}", json={}, headers=auth_headers)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_list_filters_order_and_isolation(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        low = await client.post(
            GAPS, json={"title": "Scarf", "priority": "low", "tags": ["cold"]}, headers=auth_headers
        )
        high = await client.post(
            GAPS,
            json={"title": "Boots", "priority": "high", "tags": ["cold", "rain"]},
            headers=auth_headers,
        )
        dropped = await client.post(
            GAPS, json={"title": "Hat", "status": "dropped"}, headers=auth_headers
        )
        other = await _other_user(db_session)
        db_session.add(WardrobeGap(user_id=other.id, title="Not mine"))
        await db_session.commit()

        resp = await client.get(GAPS, headers=auth_headers)
        titles = [g["title"] for g in resp.json()["gaps"]]
        assert titles == ["Boots", "Hat", "Scarf"]
        assert resp.json()["total"] == 3

        resp = await client.get(GAPS, params={"status": "open"}, headers=auth_headers)
        assert {g["id"] for g in resp.json()["gaps"]} == {low.json()["id"], high.json()["id"]}
        resp = await client.get(GAPS, params={"priority": "high"}, headers=auth_headers)
        assert [g["id"] for g in resp.json()["gaps"]] == [high.json()["id"]]
        resp = await client.get(GAPS, params={"tags": "cold,rain"}, headers=auth_headers)
        assert [g["id"] for g in resp.json()["gaps"]] == [high.json()["id"]]
        resp = await client.get(GAPS, params={"status": "dropped"}, headers=auth_headers)
        assert [g["id"] for g in resp.json()["gaps"]] == [dropped.json()["id"]]

    @pytest.mark.asyncio
    async def test_delete(self, client: AsyncClient, auth_headers):
        gap = (await client.post(GAPS, json={"title": "Belt"}, headers=auth_headers)).json()
        assert (await client.delete(f"{GAPS}/{gap['id']}", headers=auth_headers)).status_code == 204
        assert (await client.get(f"{GAPS}/{gap['id']}", headers=auth_headers)).status_code == 404

    @pytest.mark.asyncio
    async def test_cannot_touch_another_users_gap(
        self, client: AsyncClient, db_session, auth_headers
    ):
        other = await _other_user(db_session)
        gap = WardrobeGap(user_id=other.id, title="Not mine")
        db_session.add(gap)
        await db_session.commit()
        url = f"{GAPS}/{gap.id}"
        assert (await client.get(url, headers=auth_headers)).status_code == 404
        assert (
            await client.patch(url, json={"title": "Mine"}, headers=auth_headers)
        ).status_code == 404
        assert (await client.delete(url, headers=auth_headers)).status_code == 404
        await db_session.refresh(gap)
        assert gap.title == "Not mine"

    @pytest.mark.asyncio
    async def test_references_must_be_own_and_usable(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        other = await _other_user(db_session)
        foreign_item = await _item(db_session, other)
        foreign_look = await _look(db_session, other)
        archived = await _item(db_session, test_user, is_archived=True)
        cases = [
            ({"pairs_with_item_ids": [str(foreign_item.id)]}, "WARDROBE_ITEM_NOT_FOUND"),
            ({"pairs_with_item_ids": [str(archived.id)]}, "WARDROBE_ITEM_NOT_FOUND"),
            ({"pairs_with_item_ids": [str(uuid4())]}, "WARDROBE_ITEM_NOT_FOUND"),
            ({"inspiration_look_ids": [str(foreign_look.id)]}, "INSPIRATION_LOOK_NOT_FOUND"),
            ({"bought_item_id": str(foreign_item.id)}, "WARDROBE_ITEM_NOT_FOUND"),
        ]
        for fields, code in cases:
            resp = await client.post(GAPS, json={"title": "X", **fields}, headers=auth_headers)
            assert resp.status_code == 404, fields
            assert resp.json()["detail"]["error_code"] == code
        assert await _count(db_session, WardrobeGap, test_user) == 0

        gap = (await client.post(GAPS, json={"title": "X"}, headers=auth_headers)).json()
        resp = await client.patch(
            f"{GAPS}/{gap['id']}",
            json={"bought_item_id": str(foreign_item.id)},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_archived_pairing_drops_out_when_read(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        item = await _item(db_session, test_user)
        gap = (
            await client.post(
                GAPS,
                json={"title": "X", "pairs_with_item_ids": [str(item.id)]},
                headers=auth_headers,
            )
        ).json()
        item.is_archived = True
        await db_session.commit()
        body = (await client.get(f"{GAPS}/{gap['id']}", headers=auth_headers)).json()
        assert body["pairs_with"] == []
        assert body["pairs_with_item_ids"] == [str(item.id)]

    @pytest.mark.asyncio
    async def test_validation_limits(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        bad_bodies = [
            {"title": ""},
            {"title": "   "},
            {"title": "x" * 121},
            {"title": "X", "reason": "x" * 2001},
            {"title": "X", "type": "spaceship"},
            {"title": "X", "tags": ["nope"]},
            {"title": "X", "products": [_product(url="javascript:alert(1)")]},
            {"title": "X", "products": [_product(url="ftp://example.com/x")]},
            {"title": "X", "products": [_product(url="data:text/html,hi")]},
            {"title": "X", "products": [_product(url="https://")]},
            {"title": "X", "products": [_product(price=-1)]},
            {"title": "X", "products": [_product(currency="EURO")]},
            {"title": "X", "products": [_product(extra="no")]},
            {"title": "X", "products": [_product() for _ in range(11)]},
        ]
        for body in bad_bodies:
            resp = await client.post(GAPS, json=body, headers=auth_headers)
            assert resp.status_code == 422, body
        assert await _count(db_session, WardrobeGap, test_user) == 0
        resp = await client.post(
            GAPS,
            json={"title": "X", "products": [_product() for _ in range(10)]},
            headers=auth_headers,
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_bulk_is_all_or_nothing(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        other = await _other_user(db_session)
        foreign = await _item(db_session, other)
        resp = await client.post(
            f"{GAPS}/bulk",
            json={
                "gaps": [
                    {"title": "Ok"},
                    {"title": "Bad", "pairs_with_item_ids": [str(foreign.id)]},
                ]
            },
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert "gaps[1]" in resp.json()["detail"]["message"]
        resp = await client.post(
            f"{GAPS}/bulk",
            json={"gaps": [{"title": "Ok"}, {"title": "Bad", "priority": "urgent"}]},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        resp = await client.post(
            f"{GAPS}/bulk", json={"gaps": [{"title": "X"}] * 51}, headers=auth_headers
        )
        assert resp.status_code == 422
        assert await _count(db_session, WardrobeGap, test_user) == 0

        resp = await client.post(
            f"{GAPS}/bulk",
            json={"gaps": [{"title": "A"}, {"title": "B"}, {"title": "C"}]},
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        assert [g["position"] for g in resp.json()["gaps"]] == [0, 1, 2]
        assert resp.json()["total"] == 3


class TestDeclutter:
    @pytest.mark.asyncio
    async def test_create_read_update_delete(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        item = await _item(
            db_session, test_user, "sweater", name="Old sweater", primary_color="grey"
        )
        resp = await client.post(
            DECLUTTER,
            json={"item_id": str(item.id), "action": "donate", "reason": "Not worn in a year"},
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "open"
        assert body["item"]["name"] == "Old sweater"
        assert body["item"]["primary_color"] == "grey"
        assert "sig=" in body["item"]["thumbnail_url"]
        url = f"{DECLUTTER}/{body['id']}"

        resp = await client.patch(
            url, json={"action": "sell", "notes": "try online"}, headers=auth_headers
        )
        assert resp.json()["action"] == "sell"
        assert resp.json()["notes"] == "try online"
        for bad in (
            {"reason": None},
            {"reason": "  "},
            {"action": "burn"},
            {"item_id": str(uuid4())},
        ):
            assert (await client.patch(url, json=bad, headers=auth_headers)).status_code == 422, bad

        assert (await client.get(url, headers=auth_headers)).status_code == 200
        assert (await client.delete(url, headers=auth_headers)).status_code == 204
        assert (await client.get(url, headers=auth_headers)).status_code == 404

    @pytest.mark.asyncio
    async def test_done_does_not_archive_the_item(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        item = await _item(db_session, test_user)
        created = await client.post(
            DECLUTTER,
            json={"item_id": str(item.id), "action": "donate", "reason": "r"},
            headers=auth_headers,
        )
        resp = await client.patch(
            f"{DECLUTTER}/{created.json()['id']}", json={"status": "done"}, headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "done"
        await db_session.refresh(item)
        assert item.is_archived is False
        assert item.archived_at is None
        assert await db_session.get(ClothingItem, item.id) is not None

    @pytest.mark.asyncio
    async def test_one_open_suggestion_per_item(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        item = await _item(db_session, test_user)
        body = {"item_id": str(item.id), "reason": "r"}
        first = await client.post(DECLUTTER, json=body, headers=auth_headers)
        assert first.status_code == 201
        assert first.json()["action"] == "decide"
        again = await client.post(DECLUTTER, json=body, headers=auth_headers)
        assert again.status_code == 409
        assert again.json()["detail"]["error_code"] == "DECLUTTER_ALREADY_OPEN"

        first_url = f"{DECLUTTER}/{first.json()['id']}"
        await client.patch(first_url, json={"status": "dismissed"}, headers=auth_headers)
        second = await client.post(DECLUTTER, json=body, headers=auth_headers)
        assert second.status_code == 201
        reopen = await client.patch(first_url, json={"status": "open"}, headers=auth_headers)
        assert reopen.status_code == 409

        # The database enforces it too.
        db_session.add(
            DeclutterSuggestion(user_id=test_user.id, item_id=item.id, action="keep", reason="r")
        )
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_list_filters_and_isolation(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        a = await _item(db_session, test_user)
        b = await _item(db_session, test_user)
        await client.post(
            DECLUTTER,
            json={"item_id": str(a.id), "action": "donate", "reason": "r"},
            headers=auth_headers,
        )
        sell = await client.post(
            DECLUTTER,
            json={"item_id": str(b.id), "action": "sell", "reason": "r", "status": "done"},
            headers=auth_headers,
        )
        other = await _other_user(db_session)
        foreign = await _item(db_session, other)
        db_session.add(
            DeclutterSuggestion(user_id=other.id, item_id=foreign.id, action="donate", reason="r")
        )
        await db_session.commit()

        resp = await client.get(DECLUTTER, headers=auth_headers)
        assert resp.json()["total"] == 2
        resp = await client.get(DECLUTTER, params={"action": "sell"}, headers=auth_headers)
        assert [s["id"] for s in resp.json()["suggestions"]] == [sell.json()["id"]]
        resp = await client.get(DECLUTTER, params={"status": "open"}, headers=auth_headers)
        assert [s["item_id"] for s in resp.json()["suggestions"]] == [str(a.id)]

    @pytest.mark.asyncio
    async def test_item_and_suggestion_must_be_own(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        other = await _other_user(db_session)
        foreign = await _item(db_session, other)
        archived = await _item(db_session, test_user, is_archived=True)
        for item_id in (foreign.id, archived.id, uuid4()):
            resp = await client.post(
                DECLUTTER, json={"item_id": str(item_id), "reason": "r"}, headers=auth_headers
            )
            assert resp.status_code == 404
            assert resp.json()["detail"]["error_code"] == "WARDROBE_ITEM_NOT_FOUND"

        suggestion = DeclutterSuggestion(
            user_id=other.id, item_id=foreign.id, action="donate", reason="r"
        )
        db_session.add(suggestion)
        await db_session.commit()
        url = f"{DECLUTTER}/{suggestion.id}"
        assert (await client.get(url, headers=auth_headers)).status_code == 404
        assert (
            await client.patch(url, json={"status": "done"}, headers=auth_headers)
        ).status_code == 404
        assert (await client.delete(url, headers=auth_headers)).status_code == 404

    @pytest.mark.asyncio
    async def test_bulk_is_all_or_nothing(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        a = await _item(db_session, test_user)
        b = await _item(db_session, test_user)
        other = await _other_user(db_session)
        foreign = await _item(db_session, other)
        url = f"{DECLUTTER}/bulk"

        resp = await client.post(
            url,
            json={
                "suggestions": [
                    {"item_id": str(a.id), "reason": "r"},
                    {"item_id": str(foreign.id), "reason": "r"},
                ]
            },
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert "suggestions[1]" in resp.json()["detail"]["message"]
        resp = await client.post(
            url,
            json={"suggestions": [{"item_id": str(a.id), "reason": "r"}] * 2},
            headers=auth_headers,
        )
        assert resp.status_code == 409
        assert await _count(db_session, DeclutterSuggestion, test_user) == 0

        resp = await client.post(
            url,
            json={
                "suggestions": [
                    {"item_id": str(a.id), "reason": "r", "action": "donate"},
                    {"item_id": str(b.id), "reason": "r", "action": "keep"},
                ]
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        assert {UUID(s["item_id"]) for s in resp.json()["suggestions"]} == {a.id, b.id}
