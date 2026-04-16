from __future__ import annotations

import asyncio

from app.services.takealot_api import TakealotSellerAPI


def test_get_offer_detail_falls_back_to_paginated_offers_when_direct_lookup_misses(monkeypatch):
    async def _run():
        api = TakealotSellerAPI("test-key")
        calls: list[tuple[str, dict | None]] = []

        async def _fake_request(method: str, path: str, params: dict | None = None, body=None, timeout: float = 30.0):
            calls.append((path, params))
            if path == "/offers" and params == {"offer_id": "232783053", "page_size": 1}:
                return {"offers": []}
            if path == "/offers" and params == {"page_number": 1, "page_size": 100}:
                return {
                    "offers": [
                        {"offer_id": "111111", "status": "Not Buyable"},
                        {"offer_id": "232783053", "status": "Not Buyable", "leadtime_days": None},
                    ],
                    "total_results": 2,
                }
            raise AssertionError(f"unexpected request: {method} {path} {params}")

        monkeypatch.setattr(api, "_request", _fake_request)

        offer = await api.get_offer_detail("232783053")

        assert offer == {
            "offer_id": "232783053",
            "status": "Not Buyable",
            "leadtime_days": None,
        }
        assert calls == [
            ("/offers", {"offer_id": "232783053", "page_size": 1}),
            ("/offers", {"page_number": 1, "page_size": 100}),
        ]

    asyncio.run(_run())


def test_update_offer_fields_sends_minus_one_for_clearing_leadtime(monkeypatch):
    async def _run():
        api = TakealotSellerAPI("test-key")
        captured: dict = {}

        async def _fake_request(method: str, path: str, params: dict | None = None, body=None, timeout: float = 30.0):
            captured["method"] = method
            captured["path"] = path
            captured["body"] = body
            return {
                "offer": {
                    "offer_id": 232783053,
                    "leadtime_days": None,
                    "status": "Not Buyable",
                },
                "validation_errors": [],
            }

        monkeypatch.setattr(api, "_request", _fake_request)

        ok, resp = await api.update_offer_fields("232783053", {"leadtime_days": -1})

        assert ok is True
        assert resp["offer"]["leadtime_days"] is None
        assert captured == {
            "method": "PATCH",
            "path": "/offers/offer/ID232783053",
            "body": {"leadtime_days": -1},
        }

    asyncio.run(_run())
