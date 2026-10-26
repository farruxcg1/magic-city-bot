"""Mijozlar uchun: to'lov eslatmalari, botda "Mening to'lovlarim", shartnomani Telegram'ga ulash."""
import logging
import secrets

from . import db, finance
from .docs import dmy, money

REMIND_BEFORE = (3,)            # to'lovdan necha kun oldin
OVERDUE_DAYS = (1, 7, 15)       # kechikkanidan necha kun keyin; keyin har 30 kunda


async def send_client_reminders(bot):
    st = await db.get_settings()
    if not st.get("client_reminders", True):
        return 0
    t = db.today()
    phone = st["company"].get("phone") or ""
    sent = 0
    async with db.pool.acquire() as c:
        contracts = await finance.load_contracts(c, "c.status='active' AND cl.tg_id IS NOT NULL", today=t)
    for ct in contracts:
        msgs = []
        od = ct["overdue_days"]
        if ct["overdue_amount"] and (od in OVERDUE_DAYS or (od >= 30 and od % 30 == 0)):
            msgs.append((f"od-{ct['overdue_since']}-{ct['overdue_days']}",
                         f"⚠️ Hurmatli {ct['client_name']}!\n\n"
                         f"{ct['number']} shartnoma (uy {ct['unit_id']}) bo‘yicha to‘lov muddati "
                         f"{ct['overdue_days']} kunga o‘tib ketdi.\n"
                         f"Muddati o‘tgan summa: {money(ct['overdue_amount'])}\n\n"
                         f"Iltimos, to‘lovni imkon qadar tezroq amalga oshiring. Savol bo‘lsa: {phone}"))
        for it in ct["schedule"]:
            if not it["left"] or it["n"] == 0:
                continue
            days = (it["due_date"] - t).days
            if days in REMIND_BEFORE:
                msgs.append((f"pre-{it['n']}",
                             f"🔔 Eslatma: {dmy(it['due_date'])} kuni navbatdagi to‘lov.\n"
                             f"Shartnoma {ct['number']}, uy {ct['unit_id']}\n"
                             f"Summa: {money(it['left'])}"))
            elif days == 0:
                msgs.append((f"day-{it['n']}",
                             f"📅 Bugun to‘lov kuni.\nShartnoma {ct['number']}, uy {ct['unit_id']}\n"
                             f"Summa: {money(it['left'])}\n\nTo‘lov qilgach, kvitansiya shu yerga keladi."))
        for key, text in msgs:
            k = f"rem-{ct['id']}-{key}"
            got = await db.pool.fetchval(
                "INSERT INTO sent_reports(key) VALUES($1) ON CONFLICT DO NOTHING RETURNING key", k)
            if not got:
                continue
            try:
                await bot.send_message(ct["client_tg"], text)
                sent += 1
            except Exception:
                logging.warning("Eslatma yuborilmadi: mijoz %s (bot bloklangan bo'lishi mumkin)", ct["client_tg"])
    if sent:
        logging.info("Mijozlarga %s ta eslatma yuborildi", sent)
    return sent


async def my_payments_text(tg_id: int) -> str | None:
    """Botdagi "Mening to'lovlarim": mijozning faol shartnomalari bo'yicha qisqa holat."""
    if not db.pool:
        return None
    async with db.pool.acquire() as c:
        cs = await finance.load_contracts(c, "c.status='active' AND cl.tg_id=$1", (tg_id,))
    if not cs:
        return None
    parts = []
    for ct in cs:
        lines = [f"🏠 Uy {ct['unit_id']} · shartnoma {ct['number']}",
                 f"Jami: {money(ct['total'])}",
                 f"To‘langan: {money(ct['paid'])}",
                 f"Qolgan: {money(ct['remaining'])}"]
        if ct["state"] == "paid":
            lines.append("✅ Shartnoma bo‘yicha to‘lov to‘liq yopilgan. Rahmat!")
        elif ct["overdue_amount"]:
            lines.append(f"⚠️ Muddati o‘tgan: {money(ct['overdue_amount'])} ({ct['overdue_days']} kun)")
        if ct["next_due"] and ct["state"] != "paid":
            nd = ct["next_due"]
            lines.append(f"📅 Keyingi to‘lov: {dmy(nd['due_date'])}, {money(nd['left'])}")
        t = db.today()
        upcoming = [i for i in ct["schedule"] if i["left"] and i["n"] > 0 and i["due_date"] >= t][:3]
        if upcoming:
            lines.append("\nYaqin to‘lovlar:")
            for i in upcoming:
                lines.append(f"  {dmy(i['due_date'])} — {money(i['left'])}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


async def client_link_code(client_id: int) -> str:
    code = await db.pool.fetchval("SELECT link_code FROM clients WHERE id=$1", client_id)
    if code:
        return code
    code = secrets.token_urlsafe(9).replace("-", "x").replace("_", "y")
    await db.pool.execute("UPDATE clients SET link_code=$1 WHERE id=$2", code, client_id)
    return code


async def link_client(code: str, tg_id: int, username: str | None):
    """Mijoz ofisda berilgan havola orqali botga kirsa, shartnomasi uning Telegram'iga ulanadi."""
    if not db.pool:
        return None
    async with db.pool.acquire() as c, c.transaction():
        row = await c.fetchrow("SELECT id, full_name, tg_id FROM clients WHERE link_code=$1 FOR UPDATE", code)
        if not row:
            return None
        if row["tg_id"] != tg_id:
            # Shu Telegram bilan botdan avval ariza qoldirgan bo'lsa, o'sha yozuvdan ajratamiz
            await c.execute("UPDATE clients SET tg_id=NULL WHERE tg_id=$1 AND id<>$2", tg_id, row["id"])
            await c.execute("UPDATE clients SET tg_id=$1, tg_username=COALESCE($2, tg_username), updated_at=now() "
                            "WHERE id=$3", tg_id, username, row["id"])
            await db.audit(c, None, "client_tg_link", "client", row["id"], tg_id=tg_id)
        return dict(row)
