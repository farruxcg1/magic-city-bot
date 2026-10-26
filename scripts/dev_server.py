"""Lokal sinov: Telegram'siz faqat admin panel, rahbar ilovasi va Mini App.

    DATABASE_URL=postgresql://... ADMIN_PASSWORD=... python scripts/dev_server.py
"""
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aiohttp import web  # noqa: E402

from mc import web as mcweb  # noqa: E402


async def index(_r):
    return web.FileResponse(ROOT / "webapp" / "index.html")


def main():
    logging.basicConfig(level=logging.INFO)
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_static("/vendor", ROOT / "webapp" / "vendor")
    mcweb.setup(app, bot=None)
    web.run_app(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8090)))


if __name__ == "__main__":
    main()
