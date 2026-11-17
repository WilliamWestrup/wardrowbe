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
