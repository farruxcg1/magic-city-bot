"""Namuna (demo) ma'lumot: yozish yoki o'chirish (mc/demo.py).

    DATABASE_URL=postgresql://... python scripts/demo_data.py          # yozish (bazada shartnoma bo'lmasa)
    DATABASE_URL=postgresql://... python scripts/demo_data.py --clear  # o'chirish

Railway'da buning o'rniga: Variables → DEMO_DATA=1; o'chirish: admin panel → Sozlamalar.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mc import db, demo  # noqa: E402


async def main():
    await db.init()
    if "--clear" in sys.argv:
        print("O'chirildi:", await demo.clear(), "ta mijoz")
    else:
        print("Yozildi" if await demo.seed() else "Bazada shartnoma bor, demo yozilmadi")
    await db.close()


if __name__ == "__main__":
    if not os.environ.get("DATABASE_URL"):
        sys.exit("DATABASE_URL kerak")
    asyncio.run(main())
