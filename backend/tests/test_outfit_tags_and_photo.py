from datetime import date
from functools import partial
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import ClothingItem, ItemStatus
from app.models.outfit import Outfit, OutfitItem, OutfitSource, OutfitStatus
from app.models.user import User
from app.services.image_service import ImageService


async def _outfit(db: AsyncSession, user: User, tags: list[str] | None = None) -> Outfit:
    item = ClothingItem(
        user_id=user.id, type="shirt", image_path=f"test/{uuid4()}.jpg", status=ItemStatus.ready
    )
    db.add(item)
    await db.flush()
    outfit = Outfit(
        user_id=user.id,
        occasion="casual",
        scheduled_for=date.today(),
        status=OutfitStatus.pending,
        source=OutfitSource.manual,
        tags=tags or [],
    )
    outfit.items.append(OutfitItem(item_id=item.id, position=0))
    db.add(outfit)
    await db.commit()
    return outfit


def _jpeg_with_gps() -> bytes:
    image = Image.new("RGB", (400, 600), (40, 40, 40))
    exif = Image.Exif()
    exif[0x8825] = {2: (23.0, 33.0, 0.0)}  # GPSInfo with a latitude
    buf = BytesIO()
    image.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


@pytest.fixture
def storage(tmp_path):
    with patch("app.api.outfits.ImageService", partial(ImageService, storage_path=str(tmp_path))):
        yield tmp_path


class TestOutfitTags:
    @pytest.mark.asyncio
    async def test_patch_sets_tags_normalized_in_vocabulary_order(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        outfit = await _outfit(db_session, test_user)
        resp = await client.patch(
            f"/api/v1/outfits/{outfit.id}",
            json={"tags": ["Rain", "work", "work", " dinner "]},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["tags"] == ["work", "dinner", "rain"]

    @pytest.mark.asyncio
    async def test_unknown_tag_is_rejected(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        outfit = await _outfit(db_session, test_user)
        resp = await client.patch(
            f"/api/v1/outfits/{outfit.id}", json={"tags": ["work", "nope"]}, headers=auth_headers
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_list_clears_tags(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        outfit = await _outfit(db_session, test_user, tags=["work"])
        resp = await client.patch(
            f"/api/v1/outfits/{outfit.id}", json={"tags": []}, headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["tags"] == []

    @pytest.mark.asyncio
    async def test_list_filters_by_all_given_tags(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        work_rain = await _outfit(db_session, test_user, tags=["work", "rain"])
        await _outfit(db_session, test_user, tags=["work"])
        await _outfit(db_session, test_user, tags=["dinner"])

        resp = await client.get("/api/v1/outfits?tags=work", headers=auth_headers)
        assert resp.json()["total"] == 2
        resp = await client.get("/api/v1/outfits?tags=work,rain", headers=auth_headers)
        assert [o["id"] for o in resp.json()["outfits"]] == [str(work_rain.id)]

    @pytest.mark.asyncio
    async def test_avoid_filter_shows_or_hides_dont_wear_examples(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        avoid = await _outfit(db_session, test_user, tags=["casual", "avoid"])
        keep = await _outfit(db_session, test_user, tags=["casual"])

        resp = await client.get("/api/v1/outfits?avoid=true", headers=auth_headers)
        assert [o["id"] for o in resp.json()["outfits"]] == [str(avoid.id)]
        resp = await client.get("/api/v1/outfits?avoid=false", headers=auth_headers)
        assert [o["id"] for o in resp.json()["outfits"]] == [str(keep.id)]
        resp = await client.get("/api/v1/outfits", headers=auth_headers)
        assert resp.json()["total"] == 2

    @pytest.mark.asyncio
    async def test_avoid_is_a_valid_tag(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        outfit = await _outfit(db_session, test_user)
        resp = await client.patch(
            f"/api/v1/outfits/{outfit.id}", json={"tags": ["avoid", "work"]}, headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["tags"] == ["work", "avoid"]


class TestOutfitPhoto:
    @pytest.mark.asyncio
    async def test_upload_stores_photo_without_exif(
        self, client: AsyncClient, db_session, test_user, auth_headers, storage
    ):
        outfit = await _outfit(db_session, test_user)
        resp = await client.put(
            f"/api/v1/outfits/{outfit.id}/photo",
            files={"image": ("look.jpg", _jpeg_with_gps(), "image/jpeg")},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["photo_path"].startswith(f"{test_user.id}/")
        assert "sig=" in body["photo_url"] and "sig=" in body["photo_thumbnail_url"]
        stored = Image.open(storage / body["photo_path"])
        assert not stored.getexif().get(0x8825)

    @pytest.mark.asyncio
    async def test_replace_and_delete_remove_old_files(
        self, client: AsyncClient, db_session, test_user, auth_headers, storage
    ):
        outfit = await _outfit(db_session, test_user)
        url = f"/api/v1/outfits/{outfit.id}/photo"
        files = {"image": ("look.jpg", _jpeg_with_gps(), "image/jpeg")}
        first = (await client.put(url, files=files, headers=auth_headers)).json()["photo_path"]
        second = (await client.put(url, files=files, headers=auth_headers)).json()["photo_path"]
        assert not (storage / first).exists()
        assert (storage / second).exists()

        resp = await client.delete(url, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["photo_path"] is None
        assert not (storage / second).exists()

    @pytest.mark.asyncio
    async def test_deleting_outfit_removes_photo(
        self, client: AsyncClient, db_session, test_user, auth_headers, storage
    ):
        outfit = await _outfit(db_session, test_user)
        files = {"image": ("look.jpg", _jpeg_with_gps(), "image/jpeg")}
        path = (
            await client.put(
                f"/api/v1/outfits/{outfit.id}/photo", files=files, headers=auth_headers
            )
        ).json()["photo_path"]
        resp = await client.delete(f"/api/v1/outfits/{outfit.id}", headers=auth_headers)
        assert resp.status_code == 204
        assert not (storage / path).exists()

    @pytest.mark.asyncio
    async def test_cannot_touch_another_users_outfit(
        self, client: AsyncClient, db_session, test_user, auth_headers, storage
    ):
        other = User(
            id=uuid4(),
            external_id=f"other-{uuid4()}",
            email=f"other-{uuid4()}@example.com",
            display_name="Other",
            timezone="UTC",
            is_active=True,
        )
        db_session.add(other)
        await db_session.commit()
        outfit = await _outfit(db_session, other)
        files = {"image": ("look.jpg", _jpeg_with_gps(), "image/jpeg")}
        url = f"/api/v1/outfits/{outfit.id}/photo"
        assert (await client.put(url, files=files, headers=auth_headers)).status_code == 404
        assert (await client.delete(url, headers=auth_headers)).status_code == 404
        resp = await client.patch(
            f"/api/v1/outfits/{outfit.id}", json={"tags": ["work"]}, headers=auth_headers
        )
        assert resp.status_code == 404


class TestBulkDeleteByTag:
    @pytest.mark.asyncio
    async def test_select_all_deletes_only_matching_tag(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        work = await _outfit(db_session, test_user, tags=["work"])
        keep = await _outfit(db_session, test_user, tags=["dinner"])
        resp = await client.post(
            "/api/v1/outfits/bulk/delete",
            json={"select_all": True, "filters": {"tags": ["work"]}},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["deleted"] == 1
        ids = [
            o["id"]
            for o in (await client.get("/api/v1/outfits", headers=auth_headers)).json()["outfits"]
        ]
        assert str(keep.id) in ids and str(work.id) not in ids


async def _template(db: AsyncSession, user: User) -> tuple[Outfit, list[ClothingItem]]:
    """An undated outfit (lookbook template) with a shirt, pants and shoes, plus two spare shoes."""
    items = [
        ClothingItem(
            user_id=user.id, type=t, image_path=f"test/{uuid4()}.jpg", status=ItemStatus.ready
        )
        for t in ("shirt", "pants", "shoes", "shoes", "shoes")
    ]
    db.add_all(items)
    await db.flush()
    outfit = Outfit(
        user_id=user.id,
        occasion="work",
        scheduled_for=None,
        status=OutfitStatus.pending,
        source=OutfitSource.manual,
    )
    for pos, item in enumerate(items[:3]):
        outfit.items.append(OutfitItem(item_id=item.id, position=pos))
    db.add(outfit)
    await db.commit()
    return outfit, items


class TestOutfitAlternates:
    @pytest.mark.asyncio
    async def test_patch_sets_alternates_and_response_lists_them(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        outfit, items = await _template(db_session, test_user)
        shoes, alt1, alt2 = items[2], items[3], items[4]
        resp = await client.patch(
            f"/api/v1/outfits/{outfit.id}",
            json={"alternates": {str(shoes.id): [str(alt1.id), str(alt2.id), str(alt1.id)]}},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        by_id = {i["id"]: i for i in resp.json()["items"]}
        assert [a["id"] for a in by_id[str(shoes.id)]["alternates"]] == [str(alt1.id), str(alt2.id)]
        assert by_id[str(items[0].id)]["alternates"] == []

        resp = await client.patch(
            f"/api/v1/outfits/{outfit.id}", json={"alternates": {}}, headers=auth_headers
        )
        assert all(i["alternates"] == [] for i in resp.json()["items"])

    @pytest.mark.asyncio
    async def test_alternate_must_be_outside_the_outfit_and_key_inside(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        outfit, items = await _template(db_session, test_user)
        url = f"/api/v1/outfits/{outfit.id}"
        inside = {"alternates": {str(items[2].id): [str(items[0].id)]}}
        assert (await client.patch(url, json=inside, headers=auth_headers)).status_code == 400
        not_an_item = {"alternates": {str(items[3].id): [str(items[4].id)]}}
        assert (await client.patch(url, json=not_an_item, headers=auth_headers)).status_code == 400

    @pytest.mark.asyncio
    async def test_replacing_items_drops_alternates_of_removed_items(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        outfit, items = await _template(db_session, test_user)
        url = f"/api/v1/outfits/{outfit.id}"
        await client.patch(
            url,
            json={
                "alternates": {
                    str(items[2].id): [str(items[3].id)],
                    str(items[1].id): [str(items[4].id)],
                }
            },
            headers=auth_headers,
        )
        # Swap the shoes for their alternate: the shoes' alternates go, the pants' stay
        resp = await client.patch(
            url,
            json={"items": [str(items[0].id), str(items[1].id), str(items[3].id)]},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        by_id = {i["id"]: i for i in resp.json()["items"]}
        assert [a["id"] for a in by_id[str(items[1].id)]["alternates"]] == [str(items[4].id)]
        assert by_id[str(items[3].id)]["alternates"] == []

    @pytest.mark.asyncio
    async def test_wear_today_wears_the_chosen_alternate(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        outfit, items = await _template(db_session, test_user)
        shoes, alt = items[2], items[3]
        await client.patch(
            f"/api/v1/outfits/{outfit.id}",
            json={"alternates": {str(shoes.id): [str(alt.id)]}},
            headers=auth_headers,
        )
        resp = await client.post(
            f"/api/v1/outfits/{outfit.id}/wear-today",
            json={"swaps": {str(shoes.id): str(alt.id)}},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        worn_ids = {i["id"] for i in resp.json()["items"]}
        assert str(alt.id) in worn_ids and str(shoes.id) not in worn_ids
        await db_session.refresh(alt)
        await db_session.refresh(shoes)
        assert alt.wear_count == 1 and shoes.wear_count == 0

    @pytest.mark.asyncio
    async def test_wear_today_rejects_a_swap_that_is_not_an_alternate(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        outfit, items = await _template(db_session, test_user)
        resp = await client.post(
            f"/api/v1/outfits/{outfit.id}/wear-today",
            json={"swaps": {str(items[2].id): str(items[4].id)}},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_list_filters_by_item_including_alternates(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        outfit, items = await _template(db_session, test_user)
        other = await _outfit(db_session, test_user)
        await client.patch(
            f"/api/v1/outfits/{outfit.id}",
            json={"alternates": {str(items[2].id): [str(items[3].id)]}},
            headers=auth_headers,
        )
        for item, expected in (
            (items[0], {str(outfit.id)}),
            (items[3], {str(outfit.id)}),
            (items[4], set()),
        ):
            resp = await client.get(
                "/api/v1/outfits", params={"item_id": str(item.id)}, headers=auth_headers
            )
            assert resp.status_code == 200, resp.text
            assert {o["id"] for o in resp.json()["outfits"]} == expected
        assert other.id
