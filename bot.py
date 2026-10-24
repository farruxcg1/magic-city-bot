"""Magic City Telegram bot (demo).

Ikki rejim:
  * Server (Railway, Render va h.k.): BASE_URL (yoki Railway bergan RAILWAY_PUBLIC_DOMAIN,
    Render bergan RENDER_EXTERNAL_URL) bor boʻlsa,
    bot webhook bilan ishlaydi va shu serverning oʻzi Mini App sahifasini "/" da beradi.
  * Lokal: BASE_URL yoʻq boʻlsa, polling rejimi; WEBAPP_URL ni alohida bering.

Muhit oʻzgaruvchilari: BOT_TOKEN, MANAGER_CHAT_ID, (BASE_URL yoki WEBAPP_URL), PORT.
"""
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import (
    KeyboardButton, Message, ReplyKeyboardMarkup, WebAppInfo,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
_RAILWAY = os.environ.get("RAILWAY_PUBLIC_DOMAIN")  # Railway domen beradi, "https://" siz
BASE_URL = (os.environ.get("BASE_URL")
            or (f"https://{_RAILWAY}" if _RAILWAY else "")
            or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
WEBAPP_URL = os.environ.get("WEBAPP_URL") or (BASE_URL + "/")
MANAGER_CHAT_ID = int(os.environ.get("MANAGER_CHAT_ID") or 0)  # 0 = hali ulanmagan
WEBAPP_FILE = Path(__file__).parent / "webapp" / "index.html"
WEBHOOK_PATH = "/tg-webhook"
# Telegram webhook so'roviga qo'shadigan maxfiy kalit (tokendan hosil qilinadi, begona so'rovlarni to'sadi)
WEBHOOK_SECRET = hashlib.sha256(BOT_TOKEN.encode()).hexdigest()[:48]

dp = Dispatcher()


async def notify(bot: Bot, text: str):
    """Arizani menejerlar guruhiga yuboradi (guruh hali ulanmagan boʻlsa, logga yozadi)."""
    if not MANAGER_CHAT_ID:
        logging.warning("MANAGER_CHAT_ID yoʻq, ariza: %s", text)
        return
    try:
        await bot.send_message(MANAGER_CHAT_ID, text)
    except Exception:  # guruh ID xato yoki bot guruhdan chiqarilgan bo'lsa ham mijozga javob ketsin
        logging.exception("Menejerlar guruhiga yuborib bo'lmadi, ariza: %s", text)


def main_kb() -> ReplyKeyboardMarkup:
    # Mini ilova klaviatura tugmasi orqali ochilsa, tg.sendData() ariza yubora oladi
    return ReplyKeyboardMarkup(
        resize_keyboard=True,
        keyboard=[
            [KeyboardButton(text="🏢 Kvartira tanlash va hisoblash", web_app=WebAppInfo(url=WEBAPP_URL))],
            [KeyboardButton(text="📞 Raqamimni yuborish", request_contact=True),
             KeyboardButton(text="📍 Manzil")],
        ],
    )


@dp.message(CommandStart())
async def start(m: Message, command: CommandObject):
    ref = command.args or ""
    if ref.startswith("ref_"):
        await notify(m.bot,
            f"🔗 Taklif havolasi orqali yangi foydalanuvchi: {m.from_user.full_name} "
            f"(id {m.from_user.id}), taklif qilgan: {ref[4:]}",
        )
    await m.answer(
        f"Assalomu alaykum, {m.from_user.first_name}! 👋\n\n"
        "Magic City turar-joy majmuasi, Kattaqoʻrgʻon.\n"
        "Pastdagi tugmani bosing: boʻsh kvartiralar, narxlar, planirovka va "
        "boʻlib toʻlash kalkulyatori bir joyda.",
        reply_markup=main_kb(),
    )


@dp.message(F.web_app_data)
async def webapp_lead(m: Message):
    d = json.loads(m.web_app_data.data)
    calc = d.get("calc", {})
    calc_txt = (f"ipoteka, {calc.get('years')} yil, boshlangʻich {calc.get('down')}%"
                if calc.get("mortgage") else
                f"boshlangʻich {calc.get('down')}%, {calc.get('term')} oy")
    u = m.from_user
    await notify(m.bot,
        "🏢 Yangi ariza · Magic City\n"
        f"👤 {d.get('name')}  (@{u.username or '—'}, id {u.id})\n"
        f"📞 {d.get('phone')}\n"
        f"🏠 {d.get('interest')}\n"
        f"📅 {d.get('want')}, {d.get('time')}\n"
        f"🧮 {calc_txt}",
    )
    await m.answer("✅ Arizangiz qabul qilindi. Menejer tez orada qoʻngʻiroq qiladi.", reply_markup=main_kb())


@dp.message(F.contact)
async def contact(m: Message):
    await notify(m.bot,
        f"📞 Qoʻngʻiroq soʻraldi: {m.contact.first_name} {m.contact.phone_number} (id {m.from_user.id})",
    )
    await m.answer("Rahmat! Menejer siz bilan bogʻlanadi.", reply_markup=main_kb())


@dp.message(F.text == "📍 Manzil")
async def address(m: Message):
    # Haqiqiy koordinatalar bilan almashtiring
    await m.answer_location(latitude=39.8989, longitude=66.2561)
    await m.answer("Sotuv ofisi: har kuni 9:00–19:00.")


@dp.message(Command("id"), F.chat.type.in_({"group", "supergroup"}))  # "/id" va "/id@BotNomi" ikkalasi ham
async def chat_id(m: Message):
    # Menejerlar guruhida /id yozilsa, guruh ID sini koʻrsatadi
    await m.answer(f"Guruh ID: {m.chat.id}")


async def index(_request):
    return web.FileResponse(WEBAPP_FILE)


async def health(_request):
    return web.Response(text="ok")


def run_webhook():
    bot = Bot(BOT_TOKEN)

    async def on_startup(_app):
        await bot.set_webhook(BASE_URL + WEBHOOK_PATH, secret_token=WEBHOOK_SECRET,
                              drop_pending_updates=True)

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    # three.js va boshqa kutubxonalar (three.min.js.gz bo'lsa, aiohttp siqilgan holda beradi)
    app.router.add_static("/vendor", WEBAPP_FILE.parent / "vendor")
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    app.on_startup.append(on_startup)
    web.run_app(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))


async def run_polling():
    bot = Bot(BOT_TOKEN)
    await bot.delete_webhook()
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if BASE_URL:
        run_webhook()
    elif os.environ.get("WEBAPP_URL"):
        asyncio.run(run_polling())
    else:
        raise SystemExit(
            "Server manzili topilmadi. Railway: Settings → Networking → Generate Domain, "
            "keyin Redeploy. Lokal sinov uchun WEBAPP_URL bering."
        )
