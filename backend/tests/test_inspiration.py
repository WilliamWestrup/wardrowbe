from functools import partial
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from arq import Retry
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.inspiration import (
    InspirationGarment,
    InspirationLook,
    InspirationStatus,
    InspirationVote,
)
from app.models.item import ClothingItem, ItemStatus
from app.models.user import User
from app.services.ai_service import AIService, ClothingTags
from app.services.image_service import ImageService
from app.workers import inspiration as inspiration_worker

BASE = "/api/v1/inspiration"


def _jpeg_with_gps() -> bytes:
    image = Image.new("RGB", (400, 600), (40, 40, 40))
    exif = Image.Exif()
    exif[0x8825] = {2: (23.0, 33.0, 0.0)}  # GPSInfo with a latitude
    buf = BytesIO()
    image.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _files() -> dict:
    return {"image": ("look.jpg", _jpeg_with_gps(), "image/jpeg")}


def _vision(enabled: bool):
    return get_settings().model_copy(
        update={"ai_internal_enabled": enabled, "ai_vision_enabled": enabled}
    )


def _redis():
    redis = MagicMock()
    redis.enqueue_job = AsyncMock(return_value=MagicMock(job_id="job-1"))
    redis.aclose = AsyncMock()
    return redis


@pytest.fixture
def storage(tmp_path):
    with patch(
        "app.api.inspiration.ImageService", partial(ImageService, storage_path=str(tmp_path))
    ):
        yield tmp_path


@pytest.fixture
def ai_off():
    with patch("app.api.inspiration.get_settings", return_value=_vision(False)):
        yield


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
        status=ItemStatus.ready,
        **kw,
    )
    db.add(item)
    await db.commit()
    return item


async def _look(
    db: AsyncSession,
    user: User,
    *,
    vote: InspirationVote | None = None,
    tags: list[str] | None = None,
    status: InspirationStatus = InspirationStatus.analyzed,
    garments: list[str] | None = None,
) -> InspirationLook:
    look = InspirationLook(
        user_id=user.id,
        photo_path=f"test/{uuid4()}.jpg",
        vote=vote,
        tags=tags or [],
        status=status,
    )
    for position, type_ in enumerate(garments or []):
        look.garments.append(InspirationGarment(position=position, type=type_))
    db.add(look)
    await db.commit()
    return look


class TestCreateAndList:
    @pytest.mark.asyncio
    async def test_ai_off_saves_look_with_fields_and_strips_exif(
        self, client: AsyncClient, db_session, test_user, auth_headers, storage, ai_off
    ):
        with patch("app.api.inspiration.create_pool", new_callable=AsyncMock) as pool:
            resp = await client.post(
                BASE,
                files=_files(),
                data={
                    "title": " Linen look ",
                    "source_url": "https://example.com/pin/1",
                    "notes": "great colours",
                    "vote": "love",
                    "tags": "Hot,work",
                },
                headers=auth_headers,
            )
        assert resp.status_code == 201, resp.text
        pool.assert_not_called()
        body = resp.json()
        assert body["status"] == "skipped"
        assert body["title"] == "Linen look"
        assert body["source_url"] == "https://example.com/pin/1"
        assert body["vote"] == "love"
        assert body["tags"] == ["work", "hot"]
        assert body["garments"] == []
        assert "sig=" in body["photo_url"] and "sig=" in body["photo_thumbnail_url"]

        look = await db_session.get(InspirationLook, UUID(body["id"]))
        assert look.photo_path.startswith(f"{test_user.id}/")
        stored = Image.open(storage / look.photo_path)
        assert stored.format == "JPEG"
        assert not stored.getexif().get(0x8825)

    @pytest.mark.asyncio
    async def test_ai_on_queues_analysis(self, client: AsyncClient, auth_headers, storage):
        redis = _redis()
        with (
            patch("app.api.inspiration.get_settings", return_value=_vision(True)),
            patch("app.api.inspiration.create_pool", AsyncMock(return_value=redis)),
        ):
            resp = await client.post(BASE, files=_files(), headers=auth_headers)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "pending"
        args = redis.enqueue_job.call_args.args
        assert args[0] == "analyze_inspiration_look"
        assert args[1] == body["id"]
        assert args[2].startswith(str(storage))

    @pytest.mark.asyncio
    async def test_queue_failure_leaves_a_usable_look(
        self, client: AsyncClient, auth_headers, storage
    ):
        with (
            patch("app.api.inspiration.get_settings", return_value=_vision(True)),
            patch("app.api.inspiration.create_pool", AsyncMock(side_effect=OSError("down"))),
        ):
            resp = await client.post(BASE, files=_files(), headers=auth_headers)
        assert resp.status_code == 201
        look_id = resp.json()["id"]
        assert resp.json()["status"] == "error"
        resp = await client.post(
            f"{BASE}/{look_id}/garments", json={"type": "jeans"}, headers=auth_headers
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_reanalyze_requeues_a_failed_look(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        look = await _look(db_session, test_user, status=InspirationStatus.error)
        redis = _redis()
        with (
            patch("app.api.inspiration.get_settings", return_value=_vision(True)),
            patch("app.api.inspiration.create_pool", AsyncMock(return_value=redis)),
        ):
            resp = await client.post(f"{BASE}/{look.id}/analyze", headers=auth_headers)
            assert resp.status_code == 200, resp.text
            assert resp.json()["status"] == "pending"
            redis.enqueue_job.assert_awaited_once()
            again = await client.post(f"{BASE}/{look.id}/analyze", headers=auth_headers)
            assert again.status_code == 409
        with patch("app.api.inspiration.get_settings", return_value=_vision(False)):
            resp = await client.post(f"{BASE}/{look.id}/analyze", headers=auth_headers)
            assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_rejects_bad_fields_without_storing_anything(
        self, client: AsyncClient, auth_headers, storage, ai_off
    ):
        for data in (
            {"source_url": "javascript:alert(1)"},
            {"source_url": "file:///etc/passwd"},
            {"tags": "work,nope"},
            {"vote": "meh"},
        ):
            resp = await client.post(BASE, files=_files(), data=data, headers=auth_headers)
            assert resp.status_code == 422, data
        assert not any(p.is_file() for p in storage.rglob("*"))

    @pytest.mark.asyncio
    async def test_rejects_non_image(self, client: AsyncClient, auth_headers, storage, ai_off):
        resp = await client.post(
            BASE,
            files={"image": ("x.txt", b"not an image", "text/plain")},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_list_filters_by_vote_and_tags_and_hides_other_users(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        loved_work = await _look(
            db_session, test_user, vote=InspirationVote.love, tags=["work", "hot"]
        )
        liked_work = await _look(db_session, test_user, vote=InspirationVote.like, tags=["work"])
        await _look(db_session, test_user, tags=["dinner"])
        other = await _other_user(db_session)
        await _look(db_session, other, vote=InspirationVote.love, tags=["work"])

        async def ids(query: str) -> set[str]:
            resp = await client.get(f"{BASE}{query}", headers=auth_headers)
            assert resp.status_code == 200, resp.text
            return {look["id"] for look in resp.json()["looks"]}

        assert len(await ids("")) == 3
        assert await ids("?vote=love") == {str(loved_work.id)}
        assert await ids("?tags=work") == {str(loved_work.id), str(liked_work.id)}
        assert await ids("?tags=work,hot") == {str(loved_work.id)}
        assert await ids("?vote=like&tags=hot") == set()
        resp = await client.get(f"{BASE}?vote=meh", headers=auth_headers)
        assert resp.status_code == 422


class TestUpdate:
    @pytest.mark.asyncio
    async def test_patch_sets_and_clears_fields(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        look = await _look(db_session, test_user)
        url = f"{BASE}/{look.id}"
        resp = await client.patch(
            url,
            json={"vote": "like", "tags": ["rain", "Work"], "notes": "for autumn"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body["vote"], body["tags"], body["notes"]) == (
            "like",
            ["work", "rain"],
            "for autumn",
        )

        resp = await client.patch(url, json={"vote": None, "tags": []}, headers=auth_headers)
        body = resp.json()
        assert body["vote"] is None and body["tags"] == []
        assert body["notes"] == "for autumn"

    @pytest.mark.asyncio
    async def test_patch_validation(self, client: AsyncClient, db_session, test_user, auth_headers):
        look = await _look(db_session, test_user)
        url = f"{BASE}/{look.id}"
        for payload in (
            {"tags": ["nope"]},
            {"vote": "hate"},
            {"source_url": "javascript:alert(1)"},
            {"source_url": "https://"},
            {"unknown": 1},
            {"tags": ["work"] * 11},
        ):
            assert (await client.patch(url, json=payload, headers=auth_headers)).status_code == 422


class TestOwnership:
    @pytest.mark.asyncio
    async def test_cannot_touch_another_users_look(
        self, client: AsyncClient, db_session, auth_headers, storage
    ):
        other = await _other_user(db_session)
        look = await _look(db_session, other, garments=["jeans"])
        garment_id = look.garments[0].id
        url = f"{BASE}/{look.id}"
        assert (await client.get(url, headers=auth_headers)).status_code == 404
        assert (
            await client.patch(url, json={"vote": "love"}, headers=auth_headers)
        ).status_code == 404
        assert (
            await client.put(f"{url}/photo", files=_files(), headers=auth_headers)
        ).status_code == 404
        assert (
            await client.post(f"{url}/garments", json={"type": "shirt"}, headers=auth_headers)
        ).status_code == 404
        assert (
            await client.patch(
                f"{url}/garments/{garment_id}", json={"type": "shirt"}, headers=auth_headers
            )
        ).status_code == 404
        assert (
            await client.put(
                f"{url}/garments/{garment_id}/match",
                json={"wardrobe_item_id": None},
                headers=auth_headers,
            )
        ).status_code == 404
        assert (await client.post(f"{url}/match", headers=auth_headers)).status_code == 404
        assert (await client.delete(url, headers=auth_headers)).status_code == 404

    @pytest.mark.asyncio
    async def test_garment_of_another_look_is_404(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        mine = await _look(db_session, test_user, garments=["jeans"])
        other = await _other_user(db_session)
        theirs = await _look(db_session, other, garments=["jeans"])
        resp = await client.delete(
            f"{BASE}/{mine.id}/garments/{theirs.garments[0].id}", headers=auth_headers
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_match_only_accepts_own_ready_items(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        look = await _look(db_session, test_user, garments=["jeans"])
        url = f"{BASE}/{look.id}/garments/{look.garments[0].id}/match"
        other = await _other_user(db_session)
        theirs = await _item(db_session, other)
        archived = await _item(db_session, test_user, is_archived=True)
        mine = await _item(db_session, test_user, name="Blue jeans")

        for bad in (theirs.id, archived.id, uuid4()):
            resp = await client.put(url, json={"wardrobe_item_id": str(bad)}, headers=auth_headers)
            assert resp.status_code == 404

        resp = await client.put(url, json={"wardrobe_item_id": str(mine.id)}, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["matched_item"]["name"] == "Blue jeans"
        detail = (await client.get(f"{BASE}/{look.id}", headers=auth_headers)).json()
        assert detail["garments"][0]["matched_item"]["id"] == str(mine.id)

        resp = await client.put(url, json={"wardrobe_item_id": None}, headers=auth_headers)
        assert resp.json()["matched_item"] is None


class TestGarments:
    @pytest.mark.asyncio
    async def test_add_update_delete_by_hand(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        look = await _look(db_session, test_user, status=InspirationStatus.skipped)
        url = f"{BASE}/{look.id}/garments"
        resp = await client.post(
            url,
            json={"type": "Jeans", "primary_color": "Navy", "pattern": " Solid ", "fit": "slim"},
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        garment = resp.json()
        assert (garment["type"], garment["primary_color"], garment["pattern"]) == (
            "jeans",
            "navy",
            "solid",
        )
        second = (await client.post(url, json={"type": "shirt"}, headers=auth_headers)).json()
        assert second["position"] == garment["position"] + 1

        resp = await client.patch(
            f"{url}/{garment['id']}",
            json={"description": "wide jeans", "style": ["casual"]},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "wide jeans"
        assert resp.json()["fit"] == "slim"

        assert (
            await client.delete(f"{url}/{garment['id']}", headers=auth_headers)
        ).status_code == 204
        detail = (await client.get(f"{BASE}/{look.id}", headers=auth_headers)).json()
        assert [g["id"] for g in detail["garments"]] == [second["id"]]

    @pytest.mark.asyncio
    async def test_garment_validation(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        look = await _look(db_session, test_user, garments=["jeans"])
        url = f"{BASE}/{look.id}/garments"
        for payload in ({"type": "spacesuit"}, {"type": "jeans", "pattern": "nope"}, {}):
            assert (await client.post(url, json=payload, headers=auth_headers)).status_code == 422
        resp = await client.patch(
            f"{url}/{look.garments[0].id}", json={"type": None}, headers=auth_headers
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_no_edits_while_analysis_runs(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        look = await _look(db_session, test_user, status=InspirationStatus.pending)
        resp = await client.post(
            f"{BASE}/{look.id}/garments", json={"type": "jeans"}, headers=auth_headers
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_rematch_links_best_wardrobe_item(
        self, client: AsyncClient, db_session, test_user, auth_headers
    ):
        look = await _look(db_session, test_user, garments=["jeans", "sneakers"])
        look.garments[0].primary_color = "navy"
        await db_session.commit()
        await _item(db_session, test_user, "jeans", primary_color="black")
        navy = await _item(db_session, test_user, "jeans", primary_color="navy")
        other = await _other_user(db_session)
        await _item(db_session, other, "jeans", primary_color="navy")

        resp = await client.post(f"{BASE}/{look.id}/match", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        jeans, sneakers = resp.json()["garments"]
        assert jeans["matched_item_id"] == str(navy.id)
        assert len(jeans["suggested_items"]) == 2
        assert sneakers["matched_item_id"] is None
        assert resp.json()["matched_at"] is not None


class TestFiles:
    @pytest.mark.asyncio
    async def test_delete_removes_files(
        self, client: AsyncClient, test_user, auth_headers, storage, ai_off
    ):
        look_id = (await client.post(BASE, files=_files(), headers=auth_headers)).json()["id"]
        files = [p for p in storage.rglob("*") if p.is_file()]
        assert len(files) >= 2
        resp = await client.delete(f"{BASE}/{look_id}", headers=auth_headers)
        assert resp.status_code == 204
        assert not any(p.exists() for p in files)
        assert (await client.get(f"{BASE}/{look_id}", headers=auth_headers)).status_code == 404

    @pytest.mark.asyncio
    async def test_replace_removes_old_files_and_garments(
        self, client: AsyncClient, test_user, auth_headers, storage, ai_off
    ):
        look_id = (await client.post(BASE, files=_files(), headers=auth_headers)).json()["id"]
        await client.post(
            f"{BASE}/{look_id}/garments", json={"type": "jeans"}, headers=auth_headers
        )
        old = {p for p in storage.rglob("*") if p.is_file()}

        resp = await client.put(f"{BASE}/{look_id}/photo", files=_files(), headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["garments"] == []
        assert resp.json()["status"] == "skipped"
        assert not any(p.exists() for p in old)
        new = {p for p in storage.rglob("*") if p.is_file()}
        assert new and not (new & old)

    @pytest.mark.asyncio
    async def test_failed_save_removes_stored_files(
        self, client: AsyncClient, db_session, auth_headers, storage, ai_off
    ):
        with (
            patch.object(db_session, "commit", AsyncMock(side_effect=RuntimeError("db down"))),
            pytest.raises(RuntimeError),
        ):
            await client.post(BASE, files=_files(), headers=auth_headers)
        assert not any(p.is_file() for p in storage.rglob("*"))


class TestAnalyzeLook:
    @pytest.mark.asyncio
    async def test_parses_one_tag_set_per_garment(self):
        service = AIService()
        reply = (
            '{"garments": [{"type": "Jeans", "primary_color": "navy", "pattern": "solid",'
            ' "description": "wide jeans"}, {"type": "sneakers", "colors": ["white"]},'
            ' {"nothing": true}]}'
        )
        call = AsyncMock(return_value=(reply, None, None))
        with (
            patch.object(service, "_preprocess_image", return_value="image-data"),
            patch.object(service, "_call_with_fallback", call),
        ):
            garments = await service.analyze_look("unused.jpg", locale="de")
        assert [g.type for g in garments] == ["jeans", "sneakers"]
        assert garments[0].description == "wide jeans"
        assert garments[1].colors == ["white"]
        prompt = call.call_args.args[0][0]["content"]
        assert "German" in prompt and "<<" not in prompt

    @pytest.mark.asyncio
    async def test_raises_when_no_endpoint_answers(self):
        service = AIService()
        call = AsyncMock(return_value=(None, RuntimeError("unreachable"), None))
        with (
            patch.object(service, "_preprocess_image", return_value="image-data"),
            patch.object(service, "_call_with_fallback", call),
            pytest.raises(RuntimeError, match="unreachable"),
        ):
            await service.analyze_look("unused.jpg", locale="en")


def _worker_db(db_session):
    return (
        patch("app.workers.inspiration.get_db_session", return_value=db_session),
        patch.object(db_session, "close", new_callable=AsyncMock),
    )


class TestWorker:
    @pytest.mark.asyncio
    async def test_stores_garments_and_matches_wardrobe(
        self, db_session: AsyncSession, test_user, monkeypatch, tmp_path
    ):
        photo = tmp_path / "look.jpg"
        photo.write_bytes(_jpeg_with_gps())
        look = await _look(db_session, test_user, status=InspirationStatus.pending)
        look_id = look.id
        look.photo_path = "look.jpg"
        await db_session.commit()
        jeans = await _item(db_session, test_user, "jeans", primary_color="navy")
        jeans_id = jeans.id

        class _StubAI:
            def __init__(self, *args, **kwargs):
                pass

            async def analyze_look(self, path, locale="en"):
                return [
                    ClothingTags(type="jeans", primary_color="navy", description="jeans"),
                    ClothingTags(type="hat"),
                ]

        monkeypatch.setattr(inspiration_worker, "AIService", _StubAI)
        db_patch, close_patch = _worker_db(db_session)
        with (
            db_patch,
            close_patch,
            patch("app.workers.inspiration.get_settings", return_value=_vision(True)),
        ):
            result = await inspiration_worker.analyze_inspiration_look({}, str(look_id), str(photo))

        assert result["status"] == "success" and result["matched"] is True
        db_session.expire_all()
        refreshed = await db_session.scalar(
            select(InspirationLook).where(InspirationLook.id == look_id)
        )
        assert refreshed.status == InspirationStatus.analyzed
        garments = (
            await db_session.scalars(
                select(InspirationGarment)
                .where(InspirationGarment.look_id == look_id)
                .order_by(InspirationGarment.position)
            )
        ).all()
        assert [g.type for g in garments] == ["jeans", "hat"]
        assert garments[0].matched_item_id == jeans_id
        assert garments[1].matched_item_id is None

    @pytest.mark.asyncio
    async def test_final_failure_marks_error(
        self, db_session: AsyncSession, test_user, monkeypatch, tmp_path
    ):
        photo = tmp_path / "look.jpg"
        photo.write_bytes(b"x")
        look = await _look(db_session, test_user, status=InspirationStatus.pending)
        look_id = look.id

        class _FailingAI:
            def __init__(self, *args, **kwargs):
                pass

            async def analyze_look(self, path, locale="en"):
                raise RuntimeError("provider down")

        monkeypatch.setattr(inspiration_worker, "AIService", _FailingAI)
        db_patch, close_patch = _worker_db(db_session)
        with (
            db_patch,
            close_patch,
            patch("app.workers.inspiration.get_settings", return_value=_vision(True)),
        ):
            with pytest.raises(Retry):
                await inspiration_worker.analyze_inspiration_look(
                    {"job_try": 1}, str(look_id), str(photo)
                )
            with pytest.raises(RuntimeError):
                await inspiration_worker.analyze_inspiration_look(
                    {"job_try": 3}, str(look_id), str(photo)
                )
        look_id = look_id
        db_session.expire_all()
        refreshed = await db_session.get(InspirationLook, look_id)
        assert refreshed.status == InspirationStatus.error
        assert "provider down" in refreshed.error_message

    @pytest.mark.asyncio
    async def test_vision_disabled_marks_skipped(self, db_session: AsyncSession, test_user):
        look = await _look(db_session, test_user, status=InspirationStatus.pending)
        look_id = look.id
        db_patch, close_patch = _worker_db(db_session)
        with (
            db_patch,
            close_patch,
            patch("app.workers.inspiration.get_settings", return_value=_vision(False)),
        ):
            result = await inspiration_worker.analyze_inspiration_look(
                {}, str(look_id), "/nonexistent.jpg"
            )
        assert result["status"] == "skipped"
        look_id = look_id
        db_session.expire_all()
        assert (await db_session.get(InspirationLook, look_id)).status == InspirationStatus.skipped
