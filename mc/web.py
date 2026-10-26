"""Admin panel (/admin), rahbar ilovasi (/rahbar) va API'ni bot serveriga ulaydi."""
import asyncio
import logging
from pathlib import Path

from aiohttp import web

from . import api, db, report

ROOT = Path(__file__).resolve().parent.parent
ADMIN = ROOT / "admin"
RAHBAR = ROOT / "rahbar"

NO_CACHE = {"Cache-Control": "no-cache"}


def _page(path: Path):
    async def h(_request):
        return web.FileResponse(path, headers=NO_CACHE)
    return h


@web.middleware
async def security_headers(request, handler):
    resp = await handler(request)
    if request.path.startswith(("/admin", "/rahbar", "/api/")):
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


def setup(app: web.Application, bot=None):
    app.middlewares.append(security_headers)
    app["bot"] = bot
    app.router.add_routes(api.routes)
    app.router.add_get("/admin", _page(ADMIN / "index.html"))
    app.router.add_get("/admin/", _page(ADMIN / "index.html"))
    app.router.add_get("/rahbar", _page(RAHBAR / "index.html"))
    app.router.add_get("/rahbar/", _page(RAHBAR / "index.html"))
    # Service worker sahifa bilan bir papkada bo'lishi kerak (iPhone'da ilova sifatida o'rnatish uchun)
    app.router.add_get("/rahbar/sw.js", _page(RAHBAR / "sw.js"))
    app.router.add_get("/rahbar/manifest.webmanifest", manifest)
    app.router.add_static("/rahbar/static", RAHBAR / "static")

    async def on_startup(app):
        try:
            await db.init()
        except Exception:
            logging.exception("Bazaga ulanib bo'lmadi: admin panel o'chiq, bot ishlayveradi")
            db.pool = None
        if bot:
            try:
                me = await bot.get_me()
                app["bot_username"] = me.username
            except Exception:
                logging.exception("Bot ma'lumotini olib bo'lmadi")
            if db.pool:
                app["report_task"] = asyncio.create_task(report.loop(bot))

    async def on_cleanup(app):
        t = app.get("report_task")
        if t:
            t.cancel()
        await db.close()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)


async def manifest(_request):
    return web.json_response({
        "name": "Magic City · Rahbar",
        "short_name": "Magic City",
        "start_url": "/rahbar/",
        "scope": "/rahbar/",
        "display": "standalone",
        "background_color": "#f2f4f7",
        "theme_color": "#17327a",
        "lang": "uz",
        "icons": [
            {"src": "/rahbar/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/rahbar/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/rahbar/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }, content_type="application/manifest+json", headers=NO_CACHE)
