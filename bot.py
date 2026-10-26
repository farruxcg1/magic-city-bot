"""Magic City Telegram bot (demo).

Ikki rejim:
  * Server (Railway, Render va h.k.): BASE_URL (yoki Railway bergan RAILWAY_PUBLIC_DOMAIN,
    Render bergan RENDER_EXTERNAL_URL) bor boʻlsa,
    bot webhook bilan ishlaydi va shu serverning oʻzi Mini App sahifasini "/" da beradi.
  * Lokal: BASE_URL yoʻq boʻlsa, polling rejimi; WEBAPP_URL ni alohida bering.

Muhit oʻzgaruvchilari: BOT_TOKEN, MANAGER_CHAT_ID, (BASE_URL yoki WEBAPP_URL), PORT,
DATABASE_URL (PostgreSQL: admin panel uchun), ADMIN_PASSWORD (birinchi admin paroli).
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

from mc import db as mcdb
from mc import web as mcweb
from mc.api import consume_tg_link, upsert_bot_client
from mc.reminders import link_client, my_payments_text

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


async def safe(coro):
    """Bazaga yozishdagi xato mijozga javob ketishiga to'sqinlik qilmasin."""
    try:
        return await coro
    except Exception:
        logging.exception("Bazaga yozib bo'lmadi")


MY_PAYMENTS = "💳 Mening toʻlovlarim"


def main_kb() -> ReplyKeyboardMarkup:
    # Mini ilova klaviatura tugmasi orqali ochilsa, tg.sendData() ariza yubora oladi
    return ReplyKeyboardMarkup(
        resize_keyboard=True,
        keyboard=[
            [KeyboardButton(text="🏢 Kvartira tanlash va hisoblash", web_app=WebAppInfo(url=WEBAPP_URL))],
            [KeyboardButton(text="📞 Raqamimni yuborish", request_contact=True),
             KeyboardButton(text="📍 Manzil")],
            [KeyboardButton(text=MY_PAYMENTS)],
        ],
    )


@dp.message(CommandStart())
async def start(m: Message, command: CommandObject):
    ref = command.args or ""
    u = m.from_user
    if ref.startswith("staff_"):
        # Xodim (rahbar, admin) admin paneldagi "Telegram'ga ulash" havolasi orqali keldi
        staff = await consume_tg_link(ref[6:], u.id)
        if staff:
            await m.answer(f"✅ {staff['name']}, Telegram ulandi. Har kuni ertalab shu yerga hisobot keladi.\n"
                           "Hozirgi holatni ko'rish: /hisobot")
        else:
            await m.answer("Havola eskirgan. Paneldan yangi havola oling.")
        return
    if ref.startswith("c_"):
        # Mijoz ofisda berilgan havola orqali shartnomasini Telegram'ga uladi
        cl = await link_client(ref[2:], u.id, u.username)
        if cl:
            await m.answer(f"✅ {cl['full_name']}, shartnomangiz Telegram'ga ulandi.\n"
                           "Endi toʻlov kvitansiyalari va eslatmalar shu yerga keladi.", reply_markup=main_kb())
            return
    if ref.startswith("ref_"):
        await notify(m.bot,
            f"🔗 Taklif havolasi orqali yangi foydalanuvchi: {m.from_user.full_name} "
            f"(id {m.from_user.id}), taklif qilgan: {ref[4:]}",
        )
        ref_by = ref[4:]
        if ref_by.isdigit() and int(ref_by) != u.id:
            await safe(upsert_bot_client(u.id, u.full_name, u.username, ref_by=int(ref_by),
                                         note="Taklif havolasi orqali keldi"))
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
    await safe(upsert_bot_client(
        u.id, d.get("name") or u.full_name, u.username, d.get("phone"),
        interest=f"{d.get('interest')} · {calc_txt}",
        note=f"Mini App arizasi: {d.get('want')}, {d.get('time')}"))
    await m.answer("✅ Arizangiz qabul qilindi. Menejer tez orada qoʻngʻiroq qiladi.", reply_markup=main_kb())


@dp.message(F.contact)
async def contact(m: Message):
    await notify(m.bot,
        f"📞 Qoʻngʻiroq soʻraldi: {m.contact.first_name} {m.contact.phone_number} (id {m.from_user.id})",
    )
    u = m.from_user
    if m.contact.user_id in (None, u.id):  # o'zining raqami
        await safe(upsert_bot_client(u.id, u.full_name, u.username, m.contact.phone_number,
                                     note="Qoʻngʻiroq soʻradi"))
    await m.answer("Rahmat! Menejer siz bilan bogʻlanadi.", reply_markup=main_kb())


@dp.message(F.text == MY_PAYMENTS)
async def my_payments(m: Message):
    text = await safe(my_payments_text(m.from_user.id))
    if text:
        await m.answer(text, reply_markup=main_kb())
    else:
        await m.answer("Sizning nomingizga shartnoma topilmadi.\n\n"
                       "Shartnoma tuzgan boʻlsangiz, menejerdan «Telegram'ga ulash» havolasini soʻrang: "
                       "havolani bossangiz, toʻlovlaringiz shu yerda koʻrinadi.", reply_markup=main_kb())


@dp.message(Command("hisobot"))
async def staff_report(m: Message):
    if not mcdb.pool:
        return
    staff = await mcdb.pool.fetchrow("SELECT id FROM users WHERE tg_id=$1 AND active", m.from_user.id)
    if not staff:
        return
    from mc.report import send_daily
    await send_daily(m.bot, force_to=m.chat.id)


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
    mcweb.setup(app, bot)  # admin panel (/admin), rahbar ilovasi (/rahbar), API va baza
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
