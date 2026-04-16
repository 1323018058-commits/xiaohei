from __future__ import annotations

from types import SimpleNamespace

from app.models.extension import ExtensionAction
from app.models.store import StoreBinding
from app.tasks import extension_tasks


class _FakeDb:
    def __init__(self, action, store):
        self.action = action
        self.store = store
        self.commit_count = 0

    async def get(self, model, pk):
        if model is ExtensionAction and pk == self.action.id:
            return self.action
        if model is StoreBinding and pk == self.store.id:
            return self.store
        return None

    async def commit(self):
        self.commit_count += 1


class _FakeSessionCtx:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_action(**overrides):
    data = dict(
        id=11,
        user_id=2,
        store_id=7,
        action_type="list_now",
        action_source="takealot_extension",
        plid="PL-11",
        page_url="https://example.com/p/11",
        title="Sample item",
        image_url="",
        barcode="6001234567890",
        brand_name="Brand",
        buybox_price_zar=120.0,
        page_price_zar=149.0,
        target_price_zar=139.0,
        offer_id="",
        task_id="",
        action_status="recorded",
        error_code="",
        error_msg="",
        pricing_snapshot_json="",
        raw_json="",
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def _make_store(**overrides):
    data = dict(
        id=7,
        api_key="encrypted-key",
        api_secret="encrypted-secret",
        is_active=1,
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def test_process_extension_list_now_success(monkeypatch):
    action = _make_action()
    store = _make_store()
    fake_db = _FakeDb(action, store)
    captured = {}

    class _FakeApi:
        def __init__(self, api_key, api_secret=""):
            captured["credentials"] = (api_key, api_secret)

        async def create_offer_by_barcode(self, barcode, sku, selling_price, rrp, leadtime_days=5):
            captured["request"] = {
                "barcode": barcode,
                "sku": sku,
                "selling_price": selling_price,
                "rrp": rrp,
                "leadtime_days": leadtime_days,
            }
            return {
                "offer": {
                    "offer_id": "987654321",
                    "status": "Buyable",
                },
                "validation_errors": [],
            }

    monkeypatch.setattr(extension_tasks, "task_db_session", lambda: _FakeSessionCtx(fake_db))
    monkeypatch.setattr(extension_tasks, "decrypt", lambda value: f"plain:{value}")
    monkeypatch.setattr(extension_tasks, "TakealotSellerAPI", _FakeApi)

    result = extension_tasks.process_extension_list_now.run(action.id)

    assert result == {"ok": True, "action_id": action.id, "status": "submitted", "offer_id": "987654321"}
    assert captured["credentials"] == ("plain:encrypted-key", "plain:encrypted-secret")
    assert captured["request"] == {
        "barcode": "6001234567890",
        "sku": "PL-11",
        "selling_price": 139,
        "rrp": 149,
        "leadtime_days": 14,
    }
    assert action.action_status == "submitted"
    assert action.offer_id == "987654321"
    assert action.error_code == ""
    assert action.error_msg == ""
    assert "\"offer_id\": \"987654321\"" in action.raw_json
    assert fake_db.commit_count == 2


def test_process_extension_list_now_rejects_invalid_barcode(monkeypatch):
    action = _make_action(barcode="abc-123")
    store = _make_store()
    fake_db = _FakeDb(action, store)
    api_called = {"value": False}

    class _FakeApi:
        def __init__(self, *args, **kwargs):
            pass

        async def create_offer_by_barcode(self, *args, **kwargs):
            api_called["value"] = True
            raise AssertionError("API should not be called for invalid barcode")

    monkeypatch.setattr(extension_tasks, "task_db_session", lambda: _FakeSessionCtx(fake_db))
    monkeypatch.setattr(extension_tasks, "decrypt", lambda value: value)
    monkeypatch.setattr(extension_tasks, "TakealotSellerAPI", _FakeApi)

    result = extension_tasks.process_extension_list_now.run(action.id)

    assert result == {"ok": False, "action_id": action.id, "error": "invalid barcode"}
    assert api_called["value"] is False
    assert action.action_status == "failed"
    assert action.error_code == "INVALID_BARCODE"
    assert "条码无效" in action.error_msg
    assert fake_db.commit_count == 2


def test_process_extension_list_now_marks_api_failure(monkeypatch):
    action = _make_action()
    store = _make_store()
    fake_db = _FakeDb(action, store)

    class _FakeApi:
        def __init__(self, *args, **kwargs):
            pass

        async def create_offer_by_barcode(self, *args, **kwargs):
            raise RuntimeError("network down")

    monkeypatch.setattr(extension_tasks, "task_db_session", lambda: _FakeSessionCtx(fake_db))
    monkeypatch.setattr(extension_tasks, "decrypt", lambda value: value)
    monkeypatch.setattr(extension_tasks, "TakealotSellerAPI", _FakeApi)

    result = extension_tasks.process_extension_list_now.run(action.id)

    assert result == {"ok": False, "action_id": action.id, "error": "offer create failed"}
    assert action.action_status == "failed"
    assert action.error_code == "OFFER_CREATE_FAILED"
    assert "network down" in action.error_msg
    assert "\"error\": \"network down\"" in action.raw_json
    assert fake_db.commit_count == 2


def test_process_extension_list_now_skips_duplicate_execution(monkeypatch):
    action = _make_action(action_status="submitted", offer_id="987654321")
    store = _make_store()
    fake_db = _FakeDb(action, store)
    api_called = {"value": False}

    class _FakeApi:
        def __init__(self, *args, **kwargs):
            pass

        async def create_offer_by_barcode(self, *args, **kwargs):
            api_called["value"] = True
            raise AssertionError("API should not be called for submitted actions")

    monkeypatch.setattr(extension_tasks, "task_db_session", lambda: _FakeSessionCtx(fake_db))
    monkeypatch.setattr(extension_tasks, "decrypt", lambda value: value)
    monkeypatch.setattr(extension_tasks, "TakealotSellerAPI", _FakeApi)

    result = extension_tasks.process_extension_list_now.run(action.id)

    assert result == {
        "ok": True,
        "action_id": action.id,
        "status": "submitted",
        "offer_id": "987654321",
    }
    assert api_called["value"] is False
    assert action.action_status == "submitted"
    assert action.offer_id == "987654321"
    assert fake_db.commit_count == 0
