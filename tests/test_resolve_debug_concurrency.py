import asyncio
from collections.abc import Mapping

import httpx
import pytest

from a1_factor_engine.api import AuthorizationContext, create_admin_app
from a1_factor_engine.engine import A1FactorResolutionEngine


@pytest.mark.parametrize("first_kind", ["public", "debug"])
@pytest.mark.parametrize("cross_scope", [False, True])
async def test_debug_and_public_resolve_preserve_owner(first_kind, cross_scope):
    entered, release = asyncio.Event(), asyncio.Event()

    class PausedEngine(A1FactorResolutionEngine):
        async def resolve(self, request):
            if first_kind == "public" and isinstance(request, Mapping):
                entered.set()
                await release.wait()
            return await super().resolve(request)

        async def resolve_debug(self, request):
            if first_kind == "debug":
                entered.set()
                await release.wait()
            return await super().resolve_debug(request)

    def authorize(headers, permission):
        return AuthorizationContext(
            "reviewer", headers["tenant"], "project",
            ("resolve:execute", "resolve:debug", "trace:read"),
        )

    engine = PausedEngine()
    app = create_admin_app(engine=engine, authorizer=authorize)
    routes = {"public": "/api/v1/resolve", "debug": "/api/v1/debug/resolve"}
    second_kind = "debug" if first_kind == "public" else "public"
    payload = {"request_id": "race-owner", "material_name": "steel", "quantity": 1, "quantity_unit": "kg"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = asyncio.create_task(client.post(routes[first_kind], json=payload, headers={"tenant": "A"}))
        await asyncio.wait_for(entered.wait(), 3)
        second = asyncio.create_task(client.post(
            routes[second_kind], json=payload, headers={"tenant": "B" if cross_scope else "A"},
        ))
        try:
            await asyncio.sleep(0.05)
            assert second.done() is cross_scope
        finally:
            release.set()
        r1, r2 = await asyncio.wait_for(asyncio.gather(first, second), 3)
        assert r1.status_code == 200, r1.text
        assert r2.status_code == 409, r2.text
        own = await client.get("/api/v1/traces/race-owner", headers={"tenant": "A"})
        other = await client.get("/api/v1/traces/race-owner", headers={"tenant": "B"})
        assert own.status_code == 200, own.text
        assert other.status_code == 404, other.text
        assert await engine.state("race-owner") is not None
