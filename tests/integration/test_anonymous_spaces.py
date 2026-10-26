from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config.settings import Settings
from app.container import build_container
from app.domain.models import AssetManifest, AssetRecord, TaskSpec
from app.main import create_app
from app.spaces import SpaceManager

BASE = "https://testserver"


@pytest.fixture
def site(tmp_path):
    settings = Settings(
        _env_file=None,
        app_env="test",
        anonymous_spaces_enabled=True,
        anonymous_spaces_path=tmp_path / "spaces",
        anonymous_cookie_secure=True,
        database_url=f"sqlite:///{tmp_path / 'original.sqlite'}",
        object_storage_path=tmp_path / "original-output",
        workflow_checkpoint_path=tmp_path / "original-checkpoints.sqlite",
        wechat_account_name="OWNER_ONLY",
        wechat_app_id="wx-owner",
        wechat_app_secret=SecretStr("owner-secret"),
        knowledge_base_enabled=True,
        knowledge_base_token=SecretStr("private-knowledge"),
        mcp_servers_path=tmp_path / "private-mcp.json",
    )
    original = build_container(settings)
    task = original.tasks.create(TaskSpec(mode="fixed_topic", request="OWNER_ARTICLE"))
    original.artifacts.write_json(task.id, "wechat_html", {"html": "<p>PRIVATE_BODY</p>"})
    original.artifacts.write_json(task.id, "article", {"private": "OWNER_ARTICLE"})
    manager = SpaceManager(settings)
    owner_code = manager.provision_owner()
    app = create_app(settings, original)
    return app, settings, owner_code, task, original


def visitor(app):
    client = TestClient(app, base_url=BASE)
    assert client.get("/tasks").status_code == 200
    return client


def restore(client, code):
    response = client.post("/api/v1/space/restore", json={"recovery_code": code})
    assert response.status_code == 200


def make_task(client, text):
    response = client.post("/api/v1/tasks", json={"mode": "fixed_topic", "request": text})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_first_visitor_never_claims_original_data(site):
    app, _, code, task, _ = site
    first = visitor(app)
    assert first.get("/api/v1/tasks").json() == []
    assert "OWNER_ARTICLE" not in first.get("/tasks").text
    restore(first, code)
    assert first.get("/api/v1/tasks").json()[0]["id"] == task.id
    assert "PRIVATE_BODY" in first.get(f"/api/v1/tasks/{task.id}/preview").text


def test_cookie_flags_and_no_cache(site):
    client = TestClient(site[0], base_url=BASE)
    response = client.get("/tasks")
    cookie = response.headers["set-cookie"]
    for flag in ["__Host-wechat_space=", "HttpOnly", "Secure", "SameSite=lax", "Path=/"]:
        assert flag in cookie
    assert "Domain=" not in cookie
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"
    assert client.get("/space").status_code == 200


def test_missing_and_forged_credentials_cannot_access_api(site):
    app = site[0]
    for token in [None, "a" * 43, "../../owner"]:
        client = TestClient(app, base_url=BASE)
        headers = {"Cookie": "__Host-wechat_space=" + token} if token else {}
        for path in ["/api/v1/tasks", f"/api/v1/tasks/{site[3].id}/preview", "/api/v1/space"]:
            assert client.get(path, headers=headers).status_code == 401
    health = TestClient(app, base_url=BASE).get("/health")
    assert health.status_code == 200 and "OWNER_ONLY" not in health.text


@pytest.mark.parametrize("suffix", ["", "/preview", "/steps", "/genui", "/assets", "/assets/cover"])
def test_known_owner_task_ids_are_private(site, suffix):
    client = visitor(site[0])
    response = client.get(f"/api/v1/tasks/{site[3].id}{suffix}")
    assert response.status_code == 404
    assert "PRIVATE_BODY" not in response.text
    assert client.get(f"/review/{site[3].id}").status_code == 404


def test_cross_space_writes_cannot_touch_owner(site):
    app, _, _, task, original = site
    client = visitor(app)
    paths = [
        f"/api/v1/tasks/{task.id}/run",
        f"/api/v1/tasks/{task.id}/propose-titles",
        f"/api/v1/tasks/{task.id}/choose-title",
        f"/api/v1/tasks/{task.id}/push-draft",
        f"/api/v1/articles/{task.id}/final-version",
        f"/api/v1/articles/{task.id}/mark-reviewed",
        f"/api/v1/articles/{task.id}/repurpose",
        f"/api/v1/articles/{task.id}/backfill-metrics",
    ]
    for path in paths:
        assert client.post(path, json={}).status_code == 404
    assert client.delete(f"/api/v1/tasks/{task.id}").status_code == 404
    assert original.tasks.get(task.id).request == "OWNER_ARTICLE"


def test_two_visitors_and_concurrent_requests_are_isolated(site):
    a, b = visitor(site[0]), visitor(site[0])
    ida = make_task(a, "PERSON_A")
    idb = make_task(b, "PERSON_B")

    def read(client):
        return [t["id"] for t in client.get("/api/v1/tasks").json()]

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(read, [a, b] * 10))
    assert results == [[ida], [idb]] * 10
    assert b.get(f"/api/v1/tasks/{ida}").status_code == 404
    assert a.delete(f"/api/v1/tasks/{idb}").status_code == 404


def test_recovery_after_cookie_loss_and_server_restart(site):
    app, settings, _, _, _ = site
    a = visitor(app)
    task_id = make_task(a, "SAVED_ARTICLE")
    code = a.post("/api/v1/space/recovery", json={}).json()["recovery_code"]
    a.cookies.clear()
    assert a.get("/api/v1/tasks").status_code == 401
    restarted = create_app(settings)
    b = TestClient(restarted, base_url=BASE)
    restore(b, code)
    assert b.get("/api/v1/tasks").json()[0]["id"] == task_id
    assert code not in b.get("/space").text
    with closing(restarted.state.spaces._connect()) as db:
        assert (
            db.execute("SELECT 1 FROM spaces WHERE recovery_hash = ?", (code,)).fetchone() is None
        )


def test_rotating_code_revokes_other_devices_and_old_code(site):
    app = site[0]
    a, b = visitor(app), TestClient(app, base_url=BASE)
    old = a.post("/api/v1/space/recovery", json={}).json()["recovery_code"]
    restore(b, old)
    assert b.get("/api/v1/space").json()["id"] == a.get("/api/v1/space").json()["id"]
    new = a.post("/api/v1/space/recovery", json={}).json()["recovery_code"]
    assert b.get("/api/v1/tasks").status_code == 401
    assert b.post("/api/v1/space/restore", json={"recovery_code": old}).status_code == 400
    assert a.get("/api/v1/tasks").status_code == 200
    restore(b, new)
    assert b.get("/api/v1/tasks").status_code == 200


def test_private_integrations_and_settings_are_not_inherited(site):
    app, settings, code, _, _ = site
    a, b = visitor(app), visitor(app)
    sid = a.get("/api/v1/space").json()["id"]
    container = app.state.spaces.container(sid)
    assert container.settings.wechat_app_id is None
    assert container.settings.wechat_app_secret is None
    assert not container.settings.knowledge_base_enabled
    assert container.settings.knowledge_base_token is None
    assert container.settings.mcp_servers_path != settings.mcp_servers_path
    assert a.get("/api/v1/mcp/servers").json() == []
    assert "OWNER_ONLY" not in a.get("/settings").text
    result = a.post(
        "/api/v1/settings/wechat",
        json={
            "account_name": "A_ACCOUNT",
            "app_id": "wx-a",
            "app_secret": "A_SECRET",
            "original_id": "gh_a",
            "draft_enabled": True,
        },
    )
    assert result.status_code == 200 and "A_SECRET" not in result.text
    assert "A_ACCOUNT" not in b.get("/settings").text
    restore(b, code)
    assert "OWNER_ONLY" in b.get("/settings").text
    # Evict the cache as a restart would; settings must come from the space's file.
    app.state.spaces._containers.clear()
    reloaded = app.state.spaces.container(sid).settings
    assert reloaded.wechat_app_id == "wx-a"
    assert reloaded.wechat_app_secret.get_secret_value() == "A_SECRET"
    assert settings.wechat_app_id == "wx-owner"


def test_metrics_and_skill_toggles_are_isolated(site):
    a, b = visitor(site[0]), visitor(site[0])
    assert a.post("/api/v1/metrics/import-demo").status_code == 200
    assert a.get("/api/v1/metrics/overview").json() != b.get("/api/v1/metrics/overview").json()
    skills = a.get("/api/v1/skills").json()
    optional = next(s for s in skills if s.get("name") == "human_writing")
    name = optional["name"]
    result = a.patch(f"/api/v1/skills/{name}", json={"enabled": not optional["enabled"]})
    assert result.status_code == 200
    other = next(s for s in b.get("/api/v1/skills").json() if s["name"] == name)
    assert other["enabled"] == optional["enabled"]


def test_cross_origin_writes_are_rejected(site):
    client = visitor(site[0])
    for headers in [
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
    ]:
        assert client.post("/api/v1/tasks", json={}, headers=headers).status_code == 403
        assert client.post("/api/v1/space/restore", json={}, headers=headers).status_code == 403
    assert (
        client.post(
            "/api/v1/tasks",
            json={"mode": "fixed_topic", "request": "SAME_ORIGIN"},
            headers={"Origin": BASE},
        ).status_code
        == 201
    )


def test_owner_assets_require_owner_session(site):
    from app.api.capabilities import PROBE_PNG

    app, _, code, task, original = site
    asset_dir = original.settings.object_storage_path / task.id / "assets"
    asset_dir.mkdir(parents=True)
    (asset_dir / "cover.png").write_bytes(PROBE_PNG)
    manifest = AssetManifest(
        task_id=task.id,
        items=[
            AssetRecord(
                asset_id="cover",
                kind="cover",
                file_name="cover.png",
                content_type="image/png",
            )
        ],
    )
    original.artifacts.write_json(task.id, "assets", manifest.model_dump(mode="json"))
    a, b = visitor(app), visitor(app)
    restore(a, code)
    path = f"/api/v1/tasks/{task.id}/assets/cover"
    assert a.get(path).content == PROBE_PNG
    assert b.get(path).status_code == 404
    assert TestClient(app, base_url=BASE).get(path).status_code == 401


def test_unprovisioned_service_fails_closed(tmp_path):
    settings = Settings(_env_file=None, anonymous_spaces_path=tmp_path / "unprovisioned")
    manager = SpaceManager(settings)
    with pytest.raises(RuntimeError):
        manager.require_owner()
    manager.rate_limit("restore", "client", 1, 900)
    with pytest.raises(HTTPException) as exc:
        manager.rate_limit("restore", "client", 1, 900)
    assert exc.value.status_code == 429
