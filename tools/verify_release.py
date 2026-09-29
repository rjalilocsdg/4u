"""Exercise native modules in isolation without opening network listeners."""
import asyncio
import importlib
import importlib.machinery
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile


async def verify(release):
    import httpx

    with tempfile.TemporaryDirectory(prefix="x4g-check-") as data:
        os.environ.update(DATA_DIR=data, SECRET_KEY="build-verification-only",
                          ADMIN_PASSWORD="build-check-password", TELEGRAM_BOT_TOKEN="")
        sys.path.insert(0, str(release))
        main = importlib.import_module("main")
        for name in ("main", "pages", "relay_vless", "speed_limit", "telegram_bot", "xhttp_siz10"):
            module = importlib.import_module(name)
            path = Path(module.__file__).resolve()
            assert path.parent == release, (name, path)
            assert any(str(path).endswith(s) for s in importlib.machinery.EXTENSION_SUFFIXES)
        assert inspect.iscoroutinefunction(main.health)
        assert main.health.__doc__ is None
        try:
            inspect.getsource(main.health)
        except (TypeError, OSError):
            pass
        else:
            raise AssertionError("Release exposes Python function source")
        from fastapi.routing import APIRoute
        for route in main.app.routes:
            if isinstance(route, APIRoute):
                assert inspect.iscoroutinefunction(route.endpoint), route.path
        await main.startup()
        try:
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                assert (await client.get("/health")).json()["status"] == "ok"
                assert (await client.get("/")).json()["service"] == "X4G"
                assert (await client.get("/stats")).status_code == 401
                assert (await client.get("/login")).status_code == 200
                assert (await client.post("/api/login", json={"password": "wrong"})).status_code == 401
                assert (await client.post("/api/login", json={"password": "build-check-password"})).status_code == 200
                assert (await client.get("/api/me")).json()["authenticated"] is True
                assert (await client.get("/dashboard")).status_code == 200
                assert (await client.get("/stats")).status_code == 200
                assert (await client.post("/api/logout")).status_code == 200
                assert (await client.get("/stats")).status_code == 401
            relay = importlib.import_module("relay_vless")
            packet = b"\x00" + bytes(16) + b"\x00\x01\x01\xbb\x01\x7f\x00\x00\x01payload"
            assert await relay.parse_vless_header(packet) == (1, "127.0.0.1", 443, b"payload")
            speed = importlib.import_module("speed_limit")
            await speed.throttle("missing-link", 1024)
            bucket = speed._Bucket(1024)
            await bucket.consume(100)
            assert bucket.tokens < bucket.capacity
            uid, link = await main.make_link(label="build-check", protocol="xhttp")
            assert link["protocol"] == "xhttp"
            assert importlib.import_module("telegram_bot").LINKS is main.LINKS
            assert importlib.import_module("xhttp_siz10").LINKS is main.LINKS
            assert relay.LINKS is main.LINKS
            await main.save_state()
            assert (Path(data) / "x4g_state.json").is_file()
            saved = json.loads((Path(data) / "x4g_state.json").read_text())
            assert saved["links"][uid]["label"] == "build-check"
            assert await main.remove_link(uid) == "build-check"
            await main.save_state()
        finally:
            await main.shutdown()
    print("PASS: native imports, async routes, authentication, pages, VLESS parser, throttling, persistence")


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("Verification requires assertions; unset PYTHONOPTIMIZE")
    asyncio.run(verify(Path(sys.argv[1]).resolve()))
