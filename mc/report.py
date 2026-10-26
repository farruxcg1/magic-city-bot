"""Rahbar va adminlarga har kuni Telegram'da qisqa hisobot."""
import asyncio
import logging
from datetime import date, datetime

from . import db, finance
from .docs import money

MONTH_NAMES = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr",
               "noyabr", "dekabr"]


def short(n: int) -> str:
    """12 345 678 → "12,3 mln"; mayda summalar to'liq."""
    n = int(n)
    if abs(n) >= 1_000_000_000:
        return f"{n / 1e9:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " mlrd"
    if abs(n) >= 1_000_000:
        return f"{n / 1e6:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " mln"
    return money(n)


async def build_report() -> str:
    t = db.today()
    async with db.pool.acquire() as c:
        d = await finance.dashboard(c)
        yday = await c.fetchval(
            "SELECT COALESCE(sum(p.amount),0)::bigint FROM payments p JOIN contracts c ON c.id=p.contract_id "
            "WHERE p.deleted_at IS NULL AND c.status='active' AND p.paid_at = $1",
            date.fromordinal(t.toordinal() - 1))
        today_due = await finance.dues(c, "today")
    pct = round(100 * d["plan_covered"] / d["plan"]) if d["plan"] else 0
    lines = [
        f"📊 Magic City · {t.day}-{MONTH_NAMES[t.month - 1]}",
        "",
        f"Kecha tushgan: {short(yday)}",
        f"{MONTH_NAMES[t.month - 1].capitalize()} rejasi: {short(d['plan'])}, to‘landi {short(d['plan_covered'])} ({pct}%)",
        f"Oy davomida jami tushum: {short(d['collected'])}",
        "",
        f"⚠️ Muddati o‘tgan: {short(d['overdue_total'])} · {d['overdue_count']} ta mijoz",
    ]
    for o in d["overdue"][:5]:
        lines.append(f"  • {o['client']} ({o['unit']}) — {short(o['amount'])}, {o['days']} kun")
    if today_due:
        lines += ["", f"📅 Bugun to‘lashi kerak: {len(today_due)} ta, {short(sum(r['left'] for r in today_due))}"]
    lines += ["", f"🏠 Bo‘sh {d['units']['free']} · band {d['units']['held']} · sotilgan {d['units']['sold']}",
              f"Bu oy shartnoma: {d['sales_month']['count']} ta · yangi mijoz: {d['leads_month']} ta"]
    return "\n".join(lines)


async def send_daily(bot, force_to: int | None = None):
    text = await build_report()
    if force_to:
        await bot.send_message(force_to, text)
        return
    rows = await db.pool.fetch("SELECT tg_id FROM users WHERE active AND tg_id IS NOT NULL "
                               "AND role IN ('director','admin')")
    for r in rows:
        try:
            await bot.send_message(r["tg_id"], text)
        except Exception:
            logging.exception("Hisobotni %s ga yuborib bo'lmadi", r["tg_id"])


async def loop(bot):
    """Har daqiqada tekshiradi: sozlamadagi soat kelganda kuniga bir marta yuboradi."""
    while True:
        try:
            if db.pool:
                st = await db.get_settings()
                now = datetime.now(db.TZ)
                if now.hour >= int(st.get("report_hour", 9)):
                    key = f"daily-{now.date().isoformat()}"
                    got = await db.pool.fetchval(
                        "INSERT INTO sent_reports(key) VALUES($1) ON CONFLICT DO NOTHING RETURNING key", key)
                    if got:
                        await send_daily(bot)
                        from .reminders import send_client_reminders
                        await send_client_reminders(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Kunlik hisobot xatosi")
        await asyncio.sleep(60)
