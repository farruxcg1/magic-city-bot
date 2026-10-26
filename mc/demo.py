"""Taqdimot uchun namuna mijozlar, shartnomalar va to'lovlar (izohida "[demo]" bor).

Railway Variables'da DEMO_DATA=1 bo'lsa va bazada shartnoma bo'lmasa, ishga tushganda yoziladi.
Admin panel → Sozlamalar → "Namuna ma'lumotni o'chirish" bilan tozalanadi.
"""
import random
from datetime import timedelta

from . import db, finance

NAMES = ["Aliyev Sardor Baxtiyorovich", "Karimova Dilnoza Rustamovna", "Toshpo‘latov Jasur Akmalovich",
         "Rahimova Nilufar Shuhratovna", "Ergashev Bekzod Olimjonovich", "Yusupova Madina Anvarovna",
         "Normatov Otabek Farxodovich", "Xolmirzayev Ulug‘bek Sobirovich", "Qodirova Gulnora Ilhomovna",
         "Sattorov Behruz Zafarovich", "Mirzayeva Sevara Komilovna", "Abdullayev Shoxrux Nodirovich",
         "Hamroyev Doniyor Alisherovich", "Ismoilova Zarina Botirovna", "Jo‘rayev Akbar Hamidovich",
         "Nazarova Malika Ulug‘bekovna", "Tursunov Azizbek Erkinovich", "Umarova Shahnoza Bahodirovna"]
TAG = "[demo]"


async def clear() -> int:
    async with db.pool.acquire() as c, c.transaction():
        ids = [r["id"] for r in await c.fetch("SELECT id FROM clients WHERE note LIKE $1", TAG + "%")]
        cids = [r["id"] for r in await c.fetch("SELECT id, unit_id FROM contracts WHERE client_id = ANY($1)", ids)]
        units = [r["unit_id"] for r in await c.fetch("SELECT unit_id FROM contracts WHERE id = ANY($1)", cids)]
        await c.execute("DELETE FROM payments WHERE contract_id = ANY($1)", cids)
        await c.execute("DELETE FROM contracts WHERE id = ANY($1)", cids)
        await c.execute("UPDATE units SET status='free' WHERE id = ANY($1)", units)
        await c.execute("DELETE FROM clients WHERE id = ANY($1)", ids)
    return len(ids)


async def seed() -> bool:
    if await db.pool.fetchval("SELECT count(*) FROM contracts"):
        return False  # haqiqiy shartnomalar bor: demo yozilmaydi
    if not await db.pool.fetchval(
            "INSERT INTO sent_reports(key) VALUES('demo-seeded') ON CONFLICT DO NOTHING RETURNING key"):
        return False  # avval bir marta yozilgan (o'chirilgan bo'lsa ham qayta yozilmaydi)
    rnd = random.Random(42)
    t = db.today()
    st = await db.get_settings()
    async with db.pool.acquire() as c, c.transaction():
        mgr = await c.fetchval("SELECT id FROM users WHERE role='manager' AND active ORDER BY id LIMIT 1")
        free = [r["id"] for r in await c.fetch(
            "SELECT id FROM units WHERE status='free' AND id NOT IN (SELECT unit_id FROM contracts WHERE status='active') "
            "ORDER BY id")]
        rnd.shuffle(free)
        k = 0
        for i, name in enumerate(NAMES):
            phone = f"+998 9{rnd.randint(0, 9)} {rnd.randint(100, 999)} {rnd.randint(10, 99)} {rnd.randint(10, 99)}"
            stage = "contract" if i < 12 else rnd.choice(["new", "called", "visited", "new"])
            cid = await c.fetchval(
                "INSERT INTO clients(full_name, phone, passport, address, source, stage, interest, manager_id, note, created_at) "
                "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9, now() - ($10 || ' days')::interval) RETURNING id",
                name, phone, f"A{chr(65 + i % 26)}{rnd.randint(1000000, 9999999)}", "Kattaqo‘rg‘on sh.",
                rnd.choice(["bot", "office", "ref", "bot"]), stage, f"{rnd.randint(1, 4)} xonali", mgr,
                f"{TAG} namuna yozuv", str(rnd.randint(1, 200)))
            if stage != "contract":
                continue
            unit = await c.fetchrow("SELECT * FROM units WHERE id=$1", free[k]); k += 1
            months = rnd.choice([12, 24, 24, 36, 36, 60])
            cdate = t - timedelta(days=rnd.randint(40, 330))
            down = round(unit["price"] * rnd.choice([0.2, 0.3, 0.3, 0.4, 0.5]) / 100000) * 100000
            markup = round(finance.markup_for(months, st["terms"]), 1)
            first = finance.add_months(cdate, 1)
            rows, total = finance.build_schedule(unit["price"], down, months, markup, cdate, first)
            num = f"DEMO-{i + 1:03d}"
            ctid = await c.fetchval(
                "INSERT INTO contracts(number, client_id, unit_id, contract_date, price, down_payment, months, "
                "markup_pct, total, manager_id, created_by) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$10) RETURNING id",
                num, cid, unit["id"], cdate, unit["price"], down, months, markup, total, mgr)
            await c.executemany("INSERT INTO installments(contract_id, n, due_date, amount) VALUES($1,$2,$3,$4)",
                                [(ctid, r["n"], r["due_date"], r["amount"]) for r in rows])
            await c.execute("UPDATE units SET status='sold' WHERE id=$1", unit["id"])
            # to'lov odati: intizomli / biroz kechikadi / qarzdor
            habit = rnd.choice(["good", "good", "good", "late", "bad"])
            for r in rows:
                if r["due_date"] > t:
                    break
                if r["n"] == 0:
                    pay_day = r["due_date"]
                elif habit == "good":
                    pay_day = r["due_date"] - timedelta(days=rnd.randint(0, 4))
                elif habit == "late":
                    pay_day = r["due_date"] + timedelta(days=rnd.randint(3, 20))
                else:
                    if (t - r["due_date"]).days < 75:
                        continue
                    pay_day = r["due_date"] + timedelta(days=rnd.randint(5, 25))
                if pay_day > t:
                    continue
                await c.execute("INSERT INTO payments(contract_id, amount, paid_at, method, created_by) "
                                "VALUES($1,$2,$3,$4,$5)", ctid, r["amount"], pay_day,
                                rnd.choice(["cash", "cash", "card", "bank"]), mgr)
    return True
