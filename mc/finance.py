"""To'lov grafigi, to'lovlarni grafik bo'yicha taqsimlash va hisob-kitoblar.

Pul hamma joyda butun so'mda (int). To'lovlar grafikdagi eng eski qarzdan boshlab yopiladi.
"""
import calendar
from datetime import date

from . import db


def markup_for(months: int, terms: list[dict]) -> float:
    """Mini App'dagi markupFor bilan bir xil: jadvaldagi muddat bo'lmasa chiziqli hisoblanadi."""
    t = sorted(terms, key=lambda x: x["m"])
    for x in t:
        if x["m"] == months:
            return float(x["markup"])
    if not t:
        return 0.0
    if months <= t[0]["m"]:
        return float(t[0]["markup"])
    for i in range(1, len(t)):
        if months < t[i]["m"]:
            a, b = t[i - 1], t[i]
            return a["markup"] + (b["markup"] - a["markup"]) * (months - a["m"]) / (b["m"] - a["m"])
    if len(t) == 1:
        return float(t[0]["markup"])
    a, b = t[-2], t[-1]
    return b["markup"] + (b["markup"] - a["markup"]) / (b["m"] - a["m"]) * (months - b["m"])


def add_months(d: date, k: int, day: int | None = None) -> date:
    m = d.month - 1 + k
    y, m = d.year + m // 12, m % 12 + 1
    day = day or d.day
    return date(y, m, min(day, calendar.monthrange(y, m)[1]))


def build_schedule(price: int, down: int, months: int, markup_pct: float,
                   contract_date: date, first_due: date):
    """Grafik: n=0 boshlang'ich to'lov (shartnoma kuni), keyin har oy. Oylik 1000 so'mga yaxlitlanadi,
    qoldiq oxirgi oyga qo'shiladi."""
    rows = []
    if down > 0:
        rows.append({"n": 0, "due_date": contract_date, "amount": int(down)})
    rest = price - down
    total_rest = int(round(rest * (1 + markup_pct / 100)))
    if months > 0 and total_rest > 0:
        monthly = (total_rest // months) // 1000 * 1000
        for k in range(months):
            amt = monthly if k < months - 1 else total_rest - monthly * (months - 1)
            rows.append({"n": k + 1, "due_date": add_months(first_due, k, first_due.day), "amount": int(amt)})
    return rows, int(down) + total_rest


def allocate(items: list[dict], paid: int, today: date) -> dict:
    """items: grafik (due_date bo'yicha tartiblangan). Har biriga covered/left/status qo'shadi."""
    left_money = paid
    overdue_amount = 0
    overdue_since = None
    next_due = None
    for it in items:
        cov = min(it["amount"], left_money)
        left_money -= cov
        it["covered"] = cov
        it["left"] = it["amount"] - cov
        if it["left"] == 0:
            it["state"] = "paid"
        elif it["due_date"] < today:
            it["state"] = "overdue"
            overdue_amount += it["left"]
            overdue_since = overdue_since or it["due_date"]
        elif it["due_date"] == today:
            it["state"] = "today"
        else:
            it["state"] = "partial" if cov else "upcoming"
        if it["left"] and it["due_date"] >= today and next_due is None:
            next_due = {"due_date": it["due_date"], "left": it["left"], "n": it["n"]}
    total = sum(i["amount"] for i in items)
    return {
        "paid": paid,
        "remaining": max(total - paid, 0),
        "credit": max(left_money, 0),
        "overdue_amount": overdue_amount,
        "overdue_since": overdue_since,
        "overdue_days": (today - overdue_since).days if overdue_since else 0,
        "next_due": next_due,
        "state": "paid" if total and paid >= total else "overdue" if overdue_amount else "ok",
    }


CONTRACT_SQL = """
SELECT c.*, cl.full_name AS client_name, cl.phone AS client_phone, cl.tg_id AS client_tg,
       u.block, u.floor, u.n AS unit_n, u.rooms, u.area,
       m.name AS manager_name,
       COALESCE((SELECT sum(amount) FROM payments p WHERE p.contract_id=c.id AND p.deleted_at IS NULL),0)::bigint AS paid,
       (SELECT max(paid_at) FROM payments p WHERE p.contract_id=c.id AND p.deleted_at IS NULL) AS last_paid_at
FROM contracts c
JOIN clients cl ON cl.id = c.client_id
JOIN units u ON u.id = c.unit_id
LEFT JOIN users m ON m.id = c.manager_id
"""


async def load_contracts(conn, where: str = "c.status='active'", args: tuple = (), today: date | None = None):
    """Shartnomalarni grafigi va hisoblangan holati bilan qaytaradi."""
    today = today or db.today()
    rows = await conn.fetch(CONTRACT_SQL + " WHERE " + where + " ORDER BY c.contract_date DESC, c.id DESC", *args)
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    inst = await conn.fetch(
        "SELECT contract_id, n, due_date, amount FROM installments WHERE contract_id = ANY($1) "
        "ORDER BY contract_id, due_date, n", ids)
    by = {}
    for i in inst:
        by.setdefault(i["contract_id"], []).append(
            {"n": i["n"], "due_date": i["due_date"], "amount": i["amount"]})
    out = []
    for r in rows:
        c = dict(r)
        c["markup_pct"] = float(c["markup_pct"])
        c["area"] = float(c["area"])
        c["schedule"] = by.get(c["id"], [])
        c.update(allocate(c["schedule"], c["paid"], today))
        out.append(c)
    return out


def month_bounds(d: date):
    start = d.replace(day=1)
    return start, add_months(start, 1, 1)


async def dashboard(conn, month: date | None = None):
    t = db.today()
    month = (month or t).replace(day=1)
    m0, m1 = month_bounds(month)
    cs = await load_contracts(conn, today=t)

    plan = plan_cov = 0
    buckets = {"1-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
    overdue = []
    upcoming = []
    week = date.fromordinal(t.toordinal() + 7)
    for c in cs:
        for it in c["schedule"]:
            if m0 <= it["due_date"] < m1:
                plan += it["amount"]
                plan_cov += it["covered"]
            if it["left"] and t <= it["due_date"] <= week:
                upcoming.append(_due_row(c, it, t))
        if c["overdue_amount"]:
            d = c["overdue_days"]
            k = "1-30" if d <= 30 else "31-60" if d <= 60 else "61-90" if d <= 90 else "90+"
            buckets[k] += c["overdue_amount"]
            overdue.append({"contract_id": c["id"], "number": c["number"], "client": c["client_name"],
                            "phone": c["client_phone"], "unit": c["unit_id"], "amount": c["overdue_amount"],
                            "days": d, "since": c["overdue_since"]})
    overdue.sort(key=lambda x: (-x["days"], -x["amount"]))
    upcoming.sort(key=lambda x: (x["due_date"], x["client"]))

    collected = await conn.fetchval(
        "SELECT COALESCE(sum(p.amount),0)::bigint FROM payments p JOIN contracts c ON c.id=p.contract_id "
        "WHERE p.deleted_at IS NULL AND c.status='active' AND p.paid_at >= $1 AND p.paid_at < $2", m0, m1)
    today_sum = await conn.fetchval(
        "SELECT COALESCE(sum(p.amount),0)::bigint FROM payments p JOIN contracts c ON c.id=p.contract_id "
        "WHERE p.deleted_at IS NULL AND c.status='active' AND p.paid_at = $1", t)

    # 12 oylik grafik: reja (grafik bo'yicha) va amalda tushgan pul
    start = add_months(month, -11, 1)
    series = []
    plan_rows = await conn.fetch(
        "SELECT date_trunc('month', i.due_date)::date AS m, sum(i.amount)::bigint AS s FROM installments i "
        "JOIN contracts c ON c.id=i.contract_id WHERE c.status='active' AND i.due_date >= $1 AND i.due_date < $2 "
        "GROUP BY 1", start, m1)
    paid_rows = await conn.fetch(
        "SELECT date_trunc('month', p.paid_at)::date AS m, sum(p.amount)::bigint AS s FROM payments p "
        "JOIN contracts c ON c.id=p.contract_id WHERE p.deleted_at IS NULL AND c.status='active' "
        "AND p.paid_at >= $1 AND p.paid_at < $2 GROUP BY 1", start, m1)
    pm = {r["m"]: r["s"] for r in plan_rows}
    cm = {r["m"]: r["s"] for r in paid_rows}
    for k in range(12):
        d = add_months(start, k, 1)
        series.append({"month": d.isoformat()[:7], "plan": pm.get(d, 0), "paid": cm.get(d, 0)})

    units = {r["status"]: r["n"] for r in await conn.fetch("SELECT status, count(*) AS n FROM units GROUP BY 1")}
    sales_m = await conn.fetchrow(
        "SELECT count(*) AS n, COALESCE(sum(total),0)::bigint AS s FROM contracts "
        "WHERE status='active' AND contract_date >= $1 AND contract_date < $2", m0, m1)
    managers = await conn.fetch(
        """SELECT u.id, u.name,
             (SELECT count(*) FROM contracts c WHERE c.manager_id=u.id AND c.status='active'
                AND c.contract_date >= $1 AND c.contract_date < $2) AS contracts_month,
             (SELECT COALESCE(sum(total),0)::bigint FROM contracts c WHERE c.manager_id=u.id AND c.status='active'
                AND c.contract_date >= $1 AND c.contract_date < $2) AS sales_month,
             (SELECT count(*) FROM contracts c WHERE c.manager_id=u.id AND c.status='active') AS contracts_all,
             (SELECT count(*) FROM clients cl WHERE cl.manager_id=u.id AND cl.created_at >= $1 AND cl.created_at < $2) AS clients_month
           FROM users u WHERE u.active AND u.role IN ('manager','admin','director') ORDER BY u.name""", m0, m1)
    leads_m = await conn.fetchval(
        "SELECT count(*) FROM clients WHERE created_at >= $1 AND created_at < $2", m0, m1)

    total_value = sum(c["total"] for c in cs)
    total_paid = sum(min(c["paid"], c["total"]) for c in cs)
    return {
        "today": t, "month": month.isoformat()[:7],
        "plan": plan, "plan_covered": plan_cov, "collected": collected, "today_collected": today_sum,
        "overdue_total": sum(buckets.values()), "overdue_count": len(overdue), "overdue_buckets": buckets,
        "overdue": overdue[:50], "upcoming": upcoming[:50],
        "contracts": len(cs), "total_value": total_value, "total_paid": total_paid,
        "receivable": total_value - total_paid,
        "paid_off": sum(1 for c in cs if c["state"] == "paid"),
        "units": {"free": units.get("free", 0), "held": units.get("held", 0), "sold": units.get("sold", 0)},
        "sales_month": {"count": sales_m["n"], "sum": sales_m["s"]}, "leads_month": leads_m,
        "series": series,
        "managers": [dict(r) for r in managers if r["contracts_all"] or r["clients_month"]],
    }


def _due_row(c, it, t):
    return {"contract_id": c["id"], "number": c["number"], "client": c["client_name"],
            "phone": c["client_phone"], "client_tg": c["client_tg"], "unit": c["unit_id"],
            "n": it["n"], "due_date": it["due_date"], "amount": it["amount"], "left": it["left"],
            "state": it["state"], "days": (t - it["due_date"]).days}


async def dues(conn, kind: str):
    """kind: overdue | today | week | month — to'lanmagan grafik qatorlari."""
    t = db.today()
    end = {"today": t, "week": date.fromordinal(t.toordinal() + 7),
           "month": date.fromordinal(t.toordinal() + 31)}.get(kind, t)
    out = []
    for c in await load_contracts(conn, today=t):
        for it in c["schedule"]:
            if not it["left"]:
                continue
            if kind == "overdue":
                ok = it["due_date"] < t
            elif kind == "today":
                ok = it["due_date"] == t
            else:
                ok = t <= it["due_date"] <= end
            if ok:
                out.append(_due_row(c, it, t))
    out.sort(key=lambda x: (x["due_date"], x["client"]))
    return out
