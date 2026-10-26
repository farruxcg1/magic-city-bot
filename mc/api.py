"""Admin panel va rahbar ilovasi uchun JSON API (/api/...)."""
import asyncio
import io
import json
import logging
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from aiohttp import web

from . import db, finance
from .auth import (ROLE_NAMES, ROLES, check_password, create_session, current_user, hash_password,
                   note_fail, require, set_cookie, too_many, COOKIE)

routes = web.RouteTableDef()

STAGES = {"new": "Yangi", "called": "Qo‘ng‘iroq qilindi", "visited": "Ko‘rishga keldi",
          "contract": "Shartnoma", "lost": "Rad etdi"}
METHODS = {"cash": "Naqd", "card": "Plastik karta", "bank": "Bank o‘tkazmasi", "other": "Boshqa"}
SOURCES = {"bot": "Telegram bot", "office": "Ofis", "phone": "Telefon", "ref": "Tavsiya", "other": "Boshqa"}
UNIT_STATUS = {"free": "Bo‘sh", "held": "Band", "sold": "Sotilgan"}


# ---------- yordamchilar ----------

_tasks = set()


def _bg(coro):
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)

def _default(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    raise TypeError(type(o))


def J(data, status=200):
    return web.Response(text=json.dumps(data, default=_default, ensure_ascii=False),
                        status=status, content_type="application/json")


def bad(msg, status=400):
    """Foydalanuvchiga ko'rsatiladigan xato (raise bad(...))."""
    return _err(msg, status)


def _err(msg, status):
    cls = {400: web.HTTPBadRequest, 403: web.HTTPForbidden, 404: web.HTTPNotFound,
           409: web.HTTPConflict}.get(status, web.HTTPBadRequest)
    return cls(text=json.dumps({"error": msg}, ensure_ascii=False), content_type="application/json")


async def body(request) -> dict:
    try:
        d = await request.json()
    except Exception:
        raise bad("JSON kutilgan edi")
    if not isinstance(d, dict):
        raise bad("JSON obyekt kutilgan edi")
    return d


def s(v, maxlen=500):
    v = ("" if v is None else str(v)).strip()
    return v[:maxlen] or None


def as_int(v, name, lo=None, hi=None):
    try:
        if isinstance(v, str):
            v = re.sub(r"[\s ,]", "", v)
        x = int(round(float(v)))
    except (TypeError, ValueError):
        raise bad(f"{name}: son kiriting")
    if lo is not None and x < lo or hi is not None and x > hi:
        raise bad(f"{name}: qiymat chegaradan tashqarida")
    return x


def as_date(v, name, required=True):
    if not v:
        if required:
            raise bad(f"{name}: sanani kiriting")
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise bad(f"{name}: sana noto‘g‘ri")


def norm_phone(p):
    p = s(p, 40)
    if not p:
        return None
    digits = re.sub(r"\D", "", p)
    if len(digits) == 9:
        digits = "998" + digits
    if len(digits) == 12 and digits.startswith("998"):
        return f"+998 {digits[3:5]} {digits[5:8]} {digits[8:10]} {digits[10:]}"
    return p


# ---------- kirish ----------

@routes.post("/api/login")
async def login(request):
    if not db.pool:
        raise _err("Baza ulanmagan (DATABASE_URL)", 400)
    d = await body(request)
    lg = (s(d.get("login"), 60) or "").lower()
    if too_many(request, lg):
        raise _err("Juda ko‘p urinish. 10 daqiqadan keyin qayta urinib ko‘ring.", 403)
    u = await db.pool.fetchrow("SELECT * FROM users WHERE login=$1 AND active", lg)
    if not u or not check_password(str(d.get("password") or ""), u["pass_hash"]):
        note_fail(request, lg)
        raise _err("Login yoki parol noto‘g‘ri", 403)
    token = await create_session(request, u["id"])
    async with db.pool.acquire() as c:
        await db.audit(c, u["id"], "login")
    resp = J({"ok": True, "user": {"id": u["id"], "name": u["name"], "role": u["role"]}})
    set_cookie(resp, token, secure=request.secure or request.headers.get("X-Forwarded-Proto") == "https")
    return resp


@routes.post("/api/logout")
async def logout(request):
    token = request.cookies.get(COOKIE)
    if token and db.pool:
        await db.pool.execute("DELETE FROM sessions WHERE token=$1", token)
    resp = J({"ok": True})
    resp.del_cookie(COOKIE, path="/")
    return resp


@routes.get("/api/me")
async def me(request):
    if not db.pool:
        return J({"db": False, "user": None})
    u = await current_user(request)
    if not u:
        return J({"db": True, "user": None})
    st = await db.get_settings()
    return J({"db": True, "user": u, "roles": ROLE_NAMES, "stages": STAGES, "methods": METHODS,
              "sources": SOURCES, "unit_status": UNIT_STATUS,
              "settings": {"terms": st["terms"], "min_down_pct": st["min_down_pct"],
                           "max_months": st["max_months"], "company": st["company"]},
              "bot_username": request.app.get("bot_username")})


@routes.post("/api/me/password")
@require()
async def change_password(request, user):
    d = await body(request)
    row = await db.pool.fetchrow("SELECT pass_hash FROM users WHERE id=$1", user["id"])
    if not check_password(str(d.get("old") or ""), row["pass_hash"]):
        raise bad("Eski parol noto‘g‘ri")
    new = str(d.get("new") or "")
    if len(new) < 8:
        raise bad("Yangi parol kamida 8 belgidan iborat bo‘lsin")
    async with db.pool.acquire() as c:
        await c.execute("UPDATE users SET pass_hash=$1 WHERE id=$2", hash_password(new), user["id"])
        await c.execute("DELETE FROM sessions WHERE user_id=$1 AND token<>$2", user["id"],
                        request.cookies.get(COOKIE))
        await db.audit(c, user["id"], "password_change", "user", user["id"])
    return J({"ok": True})


# ---------- uylar ----------

@routes.get("/api/public/units")
async def public_units(request):
    """Mini App uchun: har bir uyning holati va narxi (shaxsiy ma'lumot yo'q)."""
    if not db.pool:
        return J({"units": None})
    rows = await db.pool.fetch("SELECT id, status, price FROM units ORDER BY id")
    st = await db.get_settings()
    cfg = {"terms": st["terms"], "min_down_pct": st["min_down_pct"], "max_months": st["max_months"],
           "phone": st["company"].get("phone")}
    resp = J({"units": [dict(r) for r in rows], "config": cfg})
    resp.headers["Cache-Control"] = "no-store"
    return resp


@routes.get("/api/units")
@require()
async def units_list(request, user):
    rows = await db.pool.fetch(
        """SELECT u.*, c.id AS contract_id, c.number AS contract_number, cl.full_name AS client_name
           FROM units u
           LEFT JOIN contracts c ON c.unit_id=u.id AND c.status='active'
           LEFT JOIN clients cl ON cl.id=c.client_id
           ORDER BY u.block, u.floor, u.n""")
    return J({"units": [dict(r) for r in rows]})


@routes.patch("/api/units/{id}")
@require("admin", "director", "manager")
async def unit_update(request, user):
    uid = request.match_info["id"]
    d = await body(request)
    async with db.pool.acquire() as c, c.transaction():
        u = await c.fetchrow("SELECT * FROM units WHERE id=$1 FOR UPDATE", uid)
        if not u:
            raise bad("Uy topilmadi", 404)
        has_contract = await c.fetchval(
            "SELECT 1 FROM contracts WHERE unit_id=$1 AND status='active'", uid)
        price, status, note = u["price"], u["status"], u["note"]
        if "price" in d:
            if user["role"] == "manager":
                raise bad("Narxni faqat admin yoki rahbar o‘zgartiradi", 403)
            price = as_int(d["price"], "Narx", 1)
        if "status" in d:
            status = d["status"]
            if status not in UNIT_STATUS:
                raise bad("Holat noto‘g‘ri")
            if has_contract and status != "sold":
                raise bad("Bu uyda faol shartnoma bor. Avval shartnomani bekor qiling.", 409)
        if "note" in d:
            note = s(d["note"])
        await c.execute("UPDATE units SET price=$1, status=$2, note=$3, updated_at=now() WHERE id=$4",
                        price, status, note, uid)
        await db.audit(c, user["id"], "unit_update", "unit", uid,
                       before={"price": u["price"], "status": u["status"]},
                       after={"price": price, "status": status})
    return J({"ok": True})


# ---------- mijozlar ----------

CLIENT_FIELDS = ("full_name", "phone", "phone2", "passport", "passport_issued", "pinfl", "birth_date",
                 "address", "source", "stage", "interest", "manager_id", "note")


def _client_values(d, partial=False):
    out = {}
    for k in CLIENT_FIELDS:
        if k not in d:
            continue
        v = d[k]
        if k in ("phone", "phone2"):
            v = norm_phone(v)
        elif k == "birth_date":
            v = as_date(v, "Tug‘ilgan sana", required=False)
        elif k == "manager_id":
            v = as_int(v, "Menejer") if v not in (None, "") else None
        elif k == "stage":
            if v not in STAGES:
                raise bad("Bosqich noto‘g‘ri")
        elif k == "source":
            if v not in SOURCES:
                v = "other"
        elif k == "passport":
            v = (s(v, 20) or "").upper().replace(" ", "") or None
        else:
            v = s(v, 2000 if k in ("note", "interest", "address") else 200)
        out[k] = v
    if not partial and not out.get("full_name"):
        raise bad("Mijozning F.I.Sh. ni kiriting")
    if "full_name" in out and not out["full_name"]:
        raise bad("Mijozning F.I.Sh. ni kiriting")
    return out


@routes.get("/api/clients")
@require()
async def clients_list(request, user):
    q = s(request.query.get("q"), 100)
    stage = request.query.get("stage")
    args, where = [], ["TRUE"]
    if q:
        args.append(f"%{q.lower()}%")
        digits = re.sub(r"\D", "", q)
        cond = f"(lower(cl.full_name) LIKE ${len(args)} OR lower(coalesce(cl.passport,'')) LIKE ${len(args)}"
        if len(digits) >= 3:
            args.append(f"%{digits}%")
            cond += (f" OR regexp_replace(coalesce(cl.phone,'')||coalesce(cl.phone2,''),'\\D','','g') "
                     f"LIKE ${len(args)}")
        where.append(cond + ")")
    if stage in STAGES:
        args.append(stage)
        where.append(f"cl.stage=${len(args)}")
    rows = await db.pool.fetch(
        f"""SELECT cl.id, cl.full_name, cl.phone, cl.tg_id, cl.tg_username, cl.source, cl.stage, cl.interest,
                   cl.created_at, cl.updated_at, m.name AS manager_name,
                   (SELECT count(*) FROM contracts c WHERE c.client_id=cl.id AND c.status='active') AS contracts
            FROM clients cl LEFT JOIN users m ON m.id=cl.manager_id
            WHERE {' AND '.join(where)} ORDER BY cl.updated_at DESC LIMIT 500""", *args)
    counts = await db.pool.fetch("SELECT stage, count(*) AS n FROM clients GROUP BY 1")
    return J({"clients": [dict(r) for r in rows], "counts": {r["stage"]: r["n"] for r in counts}})


@routes.post("/api/clients")
@require("admin", "director", "manager")
async def client_create(request, user):
    v = _client_values(await body(request))
    v.setdefault("source", "office")
    v.setdefault("manager_id", user["id"] if user["role"] == "manager" else None)
    keys = list(v)
    async with db.pool.acquire() as c, c.transaction():
        cid = await c.fetchval(
            f"INSERT INTO clients({','.join(keys)}) VALUES({','.join(f'${i + 1}' for i in range(len(keys)))}) "
            "RETURNING id", *v.values())
        await db.audit(c, user["id"], "client_create", "client", cid, name=v["full_name"])
    return J({"id": cid})


@routes.get("/api/clients/{id}")
@require()
async def client_get(request, user):
    cid = as_int(request.match_info["id"], "id")
    r = await db.pool.fetchrow(
        "SELECT cl.*, m.name AS manager_name FROM clients cl LEFT JOIN users m ON m.id=cl.manager_id "
        "WHERE cl.id=$1", cid)
    if not r:
        raise bad("Mijoz topilmadi", 404)
    async with db.pool.acquire() as c:
        cs = await finance.load_contracts(c, "c.client_id=$1", (cid,))
    for x in cs:
        x.pop("schedule", None)
    return J({"client": dict(r), "contracts": cs})


@routes.patch("/api/clients/{id}")
@require("admin", "director", "manager")
async def client_update(request, user):
    cid = as_int(request.match_info["id"], "id")
    v = _client_values(await body(request), partial=True)
    if not v:
        return J({"ok": True})
    sets = ", ".join(f"{k}=${i + 1}" for i, k in enumerate(v))
    async with db.pool.acquire() as c, c.transaction():
        n = await c.execute(f"UPDATE clients SET {sets}, updated_at=now() WHERE id=${len(v) + 1}",
                            *v.values(), cid)
        if n.endswith(" 0"):
            raise bad("Mijoz topilmadi", 404)
        await db.audit(c, user["id"], "client_update", "client", cid, fields=list(v))
    return J({"ok": True})


async def upsert_bot_client(tg_id: int, full_name: str, username: str | None = None, phone: str | None = None,
                            interest: str | None = None, ref_by: int | None = None, note: str | None = None):
    """Botdan kelgan ariza yoki kontaktni mijozlar bazasiga yozadi (bor bo'lsa yangilaydi)."""
    if not db.pool:
        return None
    phone = norm_phone(phone)
    async with db.pool.acquire() as c, c.transaction():
        row = await c.fetchrow("SELECT id, stage, note FROM clients WHERE tg_id=$1", tg_id)
        if row:
            await c.execute(
                "UPDATE clients SET phone=COALESCE($2, phone), tg_username=COALESCE($3, tg_username), "
                "interest=COALESCE($4, interest), note=CASE WHEN $5::text IS NULL THEN note "
                "ELSE concat_ws(E'\\n', note, $5::text) END, "
                "stage=CASE WHEN stage='lost' THEN 'new' ELSE stage END, updated_at=now() WHERE id=$1",
                row["id"], phone, username, interest, note)
            return row["id"]
        cid = await c.fetchval(
            "INSERT INTO clients(full_name, phone, tg_id, tg_username, source, stage, interest, ref_by, note) "
            "VALUES($1,$2,$3,$4,$5,'new',$6,$7,$8) RETURNING id",
            full_name or "Telegram foydalanuvchisi", phone, tg_id, username,
            "ref" if ref_by else "bot", interest, ref_by, note)
        await db.audit(c, None, "client_from_bot", "client", cid, tg_id=tg_id)
        return cid


# ---------- shartnomalar ----------

def _plan_from(d, st):
    price = as_int(d.get("price"), "Narx", 1)
    down = as_int(d.get("down_payment") or 0, "Boshlang‘ich to‘lov", 0, price)
    months = as_int(d.get("months") or 0, "Muddat", 0, int(st.get("max_months") or 120))
    if down < price and months == 0:
        raise bad("Muddatni kiriting yoki to‘liq summani boshlang‘ich to‘lov qiling")
    if down == price:
        months = 0
    if d.get("markup_pct") in (None, ""):
        markup = round(finance.markup_for(months, st["terms"]), 1) if months else 0.0
    else:
        try:
            markup = float(d["markup_pct"])
        except (TypeError, ValueError):
            raise bad("Ustama: son kiriting")
        if not 0 <= markup <= 300:
            raise bad("Ustama 0–300% oralig‘ida bo‘lsin")
    cdate = as_date(d.get("contract_date") or db.today().isoformat(), "Shartnoma sanasi")
    first = as_date(d.get("first_due"), "Birinchi to‘lov sanasi", required=False) or finance.add_months(cdate, 1)
    if first < cdate:
        raise bad("Birinchi oylik to‘lov shartnoma sanasidan oldin bo‘lishi mumkin emas")
    rows, total = finance.build_schedule(price, down, months, markup, cdate, first)
    return {"price": price, "down_payment": down, "months": months, "markup_pct": markup,
            "contract_date": cdate, "first_due": first, "total": total, "schedule": rows,
            "monthly": rows[1]["amount"] if len(rows) > 1 and rows[0]["n"] == 0 else (rows[0]["amount"] if rows else 0)}


@routes.post("/api/contracts/preview")
@require()
async def contract_preview(request, user):
    st = await db.get_settings()
    return J(_plan_from(await body(request), st))


@routes.post("/api/contracts")
@require("admin", "director", "manager")
async def contract_create(request, user):
    d = await body(request)
    st = await db.get_settings()
    p = _plan_from(d, st)
    client_id = as_int(d.get("client_id"), "Mijoz")
    unit_id = s(d.get("unit_id"), 20)
    manager_id = as_int(d["manager_id"], "Menejer") if d.get("manager_id") else (
        user["id"] if user["role"] == "manager" else None)
    paid_now = bool(d.get("down_paid")) and p["down_payment"] > 0
    method = d.get("down_method") if d.get("down_method") in METHODS else "cash"
    async with db.pool.acquire() as c, c.transaction():
        cl = await c.fetchrow("SELECT id, full_name, passport FROM clients WHERE id=$1", client_id)
        if not cl:
            raise bad("Mijoz topilmadi", 404)
        u = await c.fetchrow("SELECT * FROM units WHERE id=$1 FOR UPDATE", unit_id)
        if not u:
            raise bad("Uy topilmadi", 404)
        if await c.fetchval("SELECT 1 FROM contracts WHERE unit_id=$1 AND status='active'", unit_id):
            raise bad(f"{unit_id} uyga allaqachon shartnoma tuzilgan", 409)
        await c.execute("SELECT pg_advisory_xact_lock(424242)")
        year = p["contract_date"].year
        prefix = f"{st.get('contract_prefix') or 'MC'}-{year}-"
        last = await c.fetchval(
            "SELECT max(substring(number from '([0-9]+)$')::int) FROM contracts WHERE number LIKE $1", prefix + "%")
        number = f"{prefix}{(last or 0) + 1:04d}"
        cid = await c.fetchval(
            """INSERT INTO contracts(number, client_id, unit_id, contract_date, price, down_payment, months,
                 markup_pct, total, manager_id, note, created_by)
               VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) RETURNING id""",
            number, client_id, unit_id, p["contract_date"], p["price"], p["down_payment"], p["months"],
            p["markup_pct"], p["total"], manager_id, s(d.get("note"), 2000), user["id"])
        await c.executemany("INSERT INTO installments(contract_id, n, due_date, amount) VALUES($1,$2,$3,$4)",
                            [(cid, r["n"], r["due_date"], r["amount"]) for r in p["schedule"]])
        await c.execute("UPDATE units SET status='sold', updated_at=now() WHERE id=$1", unit_id)
        await c.execute("UPDATE clients SET stage='contract', updated_at=now(), "
                        "manager_id=COALESCE(manager_id, $2) WHERE id=$1", client_id, manager_id)
        await db.audit(c, user["id"], "contract_create", "contract", cid, number=number, unit=unit_id,
                       client=cl["full_name"], total=p["total"])
        pay_id = None
        if paid_now:
            pay_id = await c.fetchval(
                "INSERT INTO payments(contract_id, amount, paid_at, method, note, created_by) "
                "VALUES($1,$2,$3,$4,'Boshlang‘ich to‘lov',$5) RETURNING id",
                cid, p["down_payment"], p["contract_date"], method, user["id"])
            await db.audit(c, user["id"], "payment_add", "payment", pay_id, contract=number,
                           amount=p["down_payment"])
    if pay_id:
        _bg(send_receipt(request.app, pay_id))
    return J({"id": cid, "number": number})


@routes.get("/api/contracts")
@require()
async def contracts_list(request, user):
    status = request.query.get("status", "active")
    q = s(request.query.get("q"), 100)
    where, args = ["c.status=$1" if status in ("active", "cancelled") else "TRUE"], []
    if status in ("active", "cancelled"):
        args.append(status)
    if q:
        args.append(f"%{q.lower()}%")
        where.append(f"(lower(c.number) LIKE ${len(args)} OR lower(cl.full_name) LIKE ${len(args)} "
                     f"OR lower(c.unit_id) LIKE ${len(args)})")
    async with db.pool.acquire() as c:
        cs = await finance.load_contracts(c, " AND ".join(where), tuple(args))
    for x in cs:
        x.pop("schedule", None)
    state = request.query.get("state")
    if state in ("overdue", "ok", "paid"):
        cs = [x for x in cs if x["state"] == state]
    return J({"contracts": cs})


@routes.get("/api/contracts/{id}")
@require()
async def contract_get(request, user):
    cid = as_int(request.match_info["id"], "id")
    async with db.pool.acquire() as c:
        cs = await finance.load_contracts(c, "c.id=$1", (cid,))
        if not cs:
            raise bad("Shartnoma topilmadi", 404)
        pays = await c.fetch(
            "SELECT p.*, u.name AS created_by_name, d.name AS deleted_by_name FROM payments p "
            "LEFT JOIN users u ON u.id=p.created_by LEFT JOIN users d ON d.id=p.deleted_by "
            "WHERE p.contract_id=$1 ORDER BY p.paid_at DESC, p.id DESC", cid)
        client = await c.fetchrow("SELECT * FROM clients WHERE id=$1", cs[0]["client_id"])
    return J({"contract": cs[0], "payments": [dict(p) for p in pays], "client": dict(client)})


@routes.post("/api/contracts/{id}/cancel")
@require("admin", "director")
async def contract_cancel(request, user):
    cid = as_int(request.match_info["id"], "id")
    reason = s((await body(request)).get("reason"), 500)
    if not reason:
        raise bad("Bekor qilish sababini yozing")
    async with db.pool.acquire() as c, c.transaction():
        row = await c.fetchrow("SELECT * FROM contracts WHERE id=$1 FOR UPDATE", cid)
        if not row or row["status"] != "active":
            raise bad("Faol shartnoma topilmadi", 404)
        await c.execute("UPDATE contracts SET status='cancelled', cancelled_at=now(), cancel_reason=$2 "
                        "WHERE id=$1", cid, reason)
        await c.execute("UPDATE units SET status='free', updated_at=now() WHERE id=$1", row["unit_id"])
        await db.audit(c, user["id"], "contract_cancel", "contract", cid, number=row["number"], reason=reason)
    return J({"ok": True})


@routes.get("/api/contracts/{id}/docx")
@require()
async def contract_docx(request, user):
    from .docs import render_contract
    cid = as_int(request.match_info["id"], "id")
    async with db.pool.acquire() as c:
        cs = await finance.load_contracts(c, "c.id=$1", (cid,))
        if not cs:
            raise bad("Shartnoma topilmadi", 404)
        client = await c.fetchrow("SELECT * FROM clients WHERE id=$1", cs[0]["client_id"])
        st = await db.get_settings(c)
    data = render_contract(cs[0], dict(client), st)
    name = f"Shartnoma_{cs[0]['number']}.docx"
    return web.Response(body=data, headers={
        "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "Content-Disposition": f'attachment; filename="{name}"'})


# ---------- to'lovlar ----------

@routes.post("/api/payments")
@require("admin", "director", "manager")
async def payment_add(request, user):
    d = await body(request)
    cid = as_int(d.get("contract_id"), "Shartnoma")
    amount = as_int(d.get("amount"), "Summa", 1)
    paid_at = as_date(d.get("paid_at") or db.today().isoformat(), "To‘lov sanasi")
    if paid_at > db.today():
        raise bad("Kelajakdagi sana bilan to‘lov kiritib bo‘lmaydi")
    method = d.get("method") if d.get("method") in METHODS else "cash"
    async with db.pool.acquire() as c, c.transaction():
        row = await c.fetchrow("SELECT id, number, status, total FROM contracts WHERE id=$1 FOR UPDATE", cid)
        if not row or row["status"] != "active":
            raise bad("Faol shartnoma topilmadi", 404)
        paid = await c.fetchval("SELECT COALESCE(sum(amount),0) FROM payments WHERE contract_id=$1 "
                                "AND deleted_at IS NULL", cid)
        if paid + amount > row["total"] and not d.get("allow_over"):
            raise bad(f"Summa qolgan qarzdan ({row['total'] - paid:,} so‘m) ko‘p. "
                      "Tekshirib qayta kiriting.".replace(",", " "), 409)
        pid = await c.fetchval(
            "INSERT INTO payments(contract_id, amount, paid_at, method, note, created_by) "
            "VALUES($1,$2,$3,$4,$5,$6) RETURNING id", cid, amount, paid_at, method, s(d.get("note")), user["id"])
        await db.audit(c, user["id"], "payment_add", "payment", pid, contract=row["number"], amount=amount,
                       paid_at=paid_at.isoformat(), method=method)
    _bg(send_receipt(request.app, pid))
    return J({"id": pid})


@routes.post("/api/payments/{id}/delete")
@require("admin", "director")
async def payment_delete(request, user):
    pid = as_int(request.match_info["id"], "id")
    reason = s((await body(request)).get("reason"), 500)
    if not reason:
        raise bad("O‘chirish sababini yozing")
    async with db.pool.acquire() as c, c.transaction():
        row = await c.fetchrow(
            "SELECT p.*, c.number FROM payments p JOIN contracts c ON c.id=p.contract_id "
            "WHERE p.id=$1 AND p.deleted_at IS NULL FOR UPDATE OF p", pid)
        if not row:
            raise bad("To‘lov topilmadi", 404)
        await c.execute("UPDATE payments SET deleted_at=now(), deleted_by=$2, delete_reason=$3 WHERE id=$1",
                        pid, user["id"], reason)
        await db.audit(c, user["id"], "payment_delete", "payment", pid, contract=row["number"],
                       amount=row["amount"], paid_at=row["paid_at"].isoformat(), reason=reason)
    return J({"ok": True})


@routes.get("/api/payments")
@require()
async def payments_list(request, user):
    t = db.today()
    d0 = as_date(request.query.get("from") or t.replace(day=1).isoformat(), "Boshlanish")
    d1 = as_date(request.query.get("to") or t.isoformat(), "Tugash")
    rows = await db.pool.fetch(
        """SELECT p.id, p.amount, p.paid_at, p.method, p.note, p.created_at, p.contract_id,
                  c.number, c.unit_id, cl.full_name AS client, u.name AS created_by_name
           FROM payments p JOIN contracts c ON c.id=p.contract_id JOIN clients cl ON cl.id=c.client_id
           LEFT JOIN users u ON u.id=p.created_by
           WHERE p.deleted_at IS NULL AND p.paid_at BETWEEN $1 AND $2
           ORDER BY p.paid_at DESC, p.id DESC""", d0, d1)
    by_method = {}
    for r in rows:
        by_method[r["method"]] = by_method.get(r["method"], 0) + r["amount"]
    return J({"payments": [dict(r) for r in rows], "total": sum(r["amount"] for r in rows),
              "by_method": by_method, "from": d0, "to": d1})


@routes.get("/api/payments/{id}/receipt")
@require()
async def payment_receipt(request, user):
    from .docs import receipt_html
    pid = as_int(request.match_info["id"], "id")
    async with db.pool.acquire() as c:
        p = await c.fetchrow("SELECT p.*, u.name AS created_by_name FROM payments p "
                             "LEFT JOIN users u ON u.id=p.created_by WHERE p.id=$1", pid)
        if not p:
            raise bad("To‘lov topilmadi", 404)
        cs = await finance.load_contracts(c, "c.id=$1", (p["contract_id"],))
        st = await db.get_settings(c)
    return web.Response(text=receipt_html(dict(p), cs[0], st, METHODS), content_type="text/html")


async def send_receipt(app, pid: int):
    """To'lov kiritilgach mijozga Telegram'da kvitansiya (mijoz botga ulangan bo'lsa)."""
    bot = app.get("bot")
    if not bot or not db.pool:
        return
    try:
        async with db.pool.acquire() as c:
            p = await c.fetchrow("SELECT * FROM payments WHERE id=$1 AND deleted_at IS NULL", pid)
            if not p:
                return
            cs = await finance.load_contracts(c, "c.id=$1", (p["contract_id"],))
        ct = cs[0]
        if not ct["client_tg"]:
            return
        from .docs import money
        nd = ct["next_due"]
        text = (f"✅ To‘lov qabul qilindi\n\n"
                f"Shartnoma: {ct['number']} (uy {ct['unit_id']})\n"
                f"Summa: {money(p['amount'])}\n"
                f"Sana: {p['paid_at'].strftime('%d.%m.%Y')}\n"
                f"Kvitansiya №{p['id']}\n\n"
                f"Jami to‘langan: {money(ct['paid'])}\n"
                f"Qolgan: {money(ct['remaining'])}")
        if ct["overdue_amount"]:
            text += f"\n⚠️ Muddati o‘tgan qarz: {money(ct['overdue_amount'])}"
        elif nd:
            text += f"\nKeyingi to‘lov: {nd['due_date'].strftime('%d.%m.%Y')}, {money(nd['left'])}"
        await bot.send_message(ct["client_tg"], text)
    except Exception:
        logging.exception("Kvitansiyani mijozga yuborib bo'lmadi (to'lov %s)", pid)


# ---------- kalendar va hisobot ----------

@routes.get("/api/dues")
@require()
async def dues(request, user):
    kind = request.query.get("kind", "overdue")
    async with db.pool.acquire() as c:
        rows = await finance.dues(c, kind)
    return J({"rows": rows, "total": sum(r["left"] for r in rows)})


@routes.get("/api/dashboard")
@require()
async def dashboard(request, user):
    m = request.query.get("month")
    month = as_date(m + "-01", "Oy") if m else None
    async with db.pool.acquire() as c:
        return J(await finance.dashboard(c, month))


# ---------- sozlamalar, xodimlar, jurnal ----------

@routes.get("/api/settings")
@require()
async def settings_get(request, user):
    st = await db.get_settings()
    st["demo_clients"] = await db.pool.fetchval("SELECT count(*) FROM clients WHERE note LIKE '[demo]%'")
    return J(st)


@routes.post("/api/demo/clear")
@require("admin")
async def demo_clear(request, user):
    from . import demo
    n = await demo.clear()
    async with db.pool.acquire() as c:
        await db.audit(c, user["id"], "demo_clear", None, None, clients=n)
    return J({"ok": True, "clients": n})


@routes.put("/api/settings")
@require("admin")
async def settings_put(request, user):
    d = await body(request)
    vals = {}
    if "company" in d and isinstance(d["company"], dict):
        vals["company"] = {k: s(d["company"].get(k), 300) or "" for k in db.DEFAULT_SETTINGS["company"]}
    if "contract_prefix" in d:
        p = re.sub(r"[^A-Za-z0-9]", "", str(d["contract_prefix"]))[:8]
        vals["contract_prefix"] = p or "MC"
    if "min_down_pct" in d:
        vals["min_down_pct"] = as_int(d["min_down_pct"], "Eng kam boshlang‘ich to‘lov", 0, 100)
    if "max_months" in d:
        vals["max_months"] = as_int(d["max_months"], "Eng uzun muddat", 1, 360)
    if "report_hour" in d:
        vals["report_hour"] = as_int(d["report_hour"], "Hisobot soati", 0, 23)
    if "client_reminders" in d:
        vals["client_reminders"] = bool(d["client_reminders"])
    if "terms" in d:
        terms = []
        for t in d["terms"] or []:
            m = as_int(t.get("m"), "Muddat", 1, 360)
            try:
                mk = float(t.get("markup") or 0)
            except (TypeError, ValueError):
                raise bad("Ustama: son kiriting")
            terms.append({"m": m, "markup": round(mk, 2)})
        if not terms:
            raise bad("Kamida bitta muddat bo‘lsin")
        vals["terms"] = sorted({t["m"]: t for t in terms}.values(), key=lambda x: x["m"])
    async with db.pool.acquire() as c, c.transaction():
        for k, v in vals.items():
            await c.execute("INSERT INTO settings(key, value) VALUES($1,$2) "
                            "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", k, v)
        await db.audit(c, user["id"], "settings_update", "settings", None, keys=list(vals))
    return J({"ok": True})


@routes.get("/api/users")
@require()
async def users_list(request, user):
    rows = await db.pool.fetch(
        "SELECT id, login, name, role, phone, active, tg_id IS NOT NULL AS tg_linked, created_at "
        "FROM users ORDER BY active DESC, name")
    return J({"users": [dict(r) for r in rows]})


@routes.post("/api/users")
@require("admin")
async def user_create(request, user):
    d = await body(request)
    login_ = (s(d.get("login"), 40) or "").lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", login_):
        raise bad("Login: kamida 3 ta lotin harf yoki raqam")
    pw = str(d.get("password") or "")
    if len(pw) < 8:
        raise bad("Parol kamida 8 belgi")
    role = d.get("role")
    if role not in ROLES:
        raise bad("Rol noto‘g‘ri")
    name = s(d.get("name"), 100)
    if not name:
        raise bad("Ismni kiriting")
    async with db.pool.acquire() as c, c.transaction():
        if await c.fetchval("SELECT 1 FROM users WHERE login=$1", login_):
            raise bad("Bu login band", 409)
        uid = await c.fetchval("INSERT INTO users(login, pass_hash, name, role, phone) VALUES($1,$2,$3,$4,$5) "
                               "RETURNING id", login_, hash_password(pw), name, role, norm_phone(d.get("phone")))
        await db.audit(c, user["id"], "user_create", "user", uid, login=login_, role=role)
    return J({"id": uid})


@routes.patch("/api/users/{id}")
@require("admin")
async def user_update(request, user):
    uid = as_int(request.match_info["id"], "id")
    d = await body(request)
    sets, args = [], []
    if "name" in d:
        args.append(s(d["name"], 100) or "—"); sets.append(f"name=${len(args)}")
    if "phone" in d:
        args.append(norm_phone(d["phone"])); sets.append(f"phone=${len(args)}")
    if "role" in d:
        if d["role"] not in ROLES:
            raise bad("Rol noto‘g‘ri")
        if uid == user["id"] and d["role"] != "admin":
            raise bad("O‘zingizni admin rolidan chiqara olmaysiz")
        args.append(d["role"]); sets.append(f"role=${len(args)}")
    if "active" in d:
        if uid == user["id"] and not d["active"]:
            raise bad("O‘zingizni o‘chira olmaysiz")
        args.append(bool(d["active"])); sets.append(f"active=${len(args)}")
    if d.get("password"):
        if len(str(d["password"])) < 8:
            raise bad("Parol kamida 8 belgi")
        args.append(hash_password(str(d["password"]))); sets.append(f"pass_hash=${len(args)}")
    if d.get("unlink_tg"):
        sets.append("tg_id=NULL")
    if not sets:
        return J({"ok": True})
    args.append(uid)
    async with db.pool.acquire() as c, c.transaction():
        await c.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=${len(args)}", *args)
        if d.get("password") or d.get("active") is False:
            await c.execute("DELETE FROM sessions WHERE user_id=$1", uid)
        await db.audit(c, user["id"], "user_update", "user", uid,
                       fields=[k for k in d if k != "password"] + (["password"] if d.get("password") else []))
    return J({"ok": True})


AUDIT_NAMES = {
    "login": "Tizimga kirdi", "password_change": "Parolini o‘zgartirdi", "unit_update": "Uyni o‘zgartirdi",
    "client_create": "Mijoz qo‘shdi", "client_update": "Mijozni tahrirladi", "client_from_bot": "Botdan yangi mijoz",
    "contract_create": "Shartnoma tuzdi", "contract_cancel": "Shartnomani bekor qildi",
    "payment_add": "To‘lov kiritdi", "payment_delete": "To‘lovni o‘chirdi", "settings_update": "Sozlamalarni o‘zgartirdi",
    "user_create": "Xodim qo‘shdi", "user_update": "Xodimni o‘zgartirdi", "tg_link": "Telegram ulandi",
    "client_tg_link": "Mijoz Telegram'ga ulandi", "demo_clear": "Namuna ma’lumotni o‘chirdi",
}


@routes.get("/api/audit")
@require("admin", "director")
async def audit_list(request, user):
    rows = await db.pool.fetch(
        "SELECT a.*, u.name AS user_name FROM audit a LEFT JOIN users u ON u.id=a.user_id "
        "WHERE ($1::text IS NULL OR a.action=$1) ORDER BY a.id DESC LIMIT 300", request.query.get("action") or None)
    return J({"rows": [dict(r) for r in rows], "names": AUDIT_NAMES})


# ---------- Telegram'ga ulash (rahbar va xodimlar kunlik hisobot oladi) ----------

@routes.post("/api/me/tg-link")
@require()
async def tg_link(request, user):
    bot_username = request.app.get("bot_username")
    if not bot_username:
        raise bad("Bot ulanmagan")
    token = secrets.token_urlsafe(18)
    await db.pool.execute("DELETE FROM tg_links WHERE expires_at < now()")
    await db.pool.execute("INSERT INTO tg_links(token, user_id, expires_at) VALUES($1,$2,$3)",
                          token, user["id"], datetime.now(timezone.utc) + timedelta(minutes=30))
    return J({"url": f"https://t.me/{bot_username}?start=staff_{token}"})


async def consume_tg_link(token: str, tg_id: int):
    if not db.pool:
        return None
    async with db.pool.acquire() as c, c.transaction():
        row = await c.fetchrow("DELETE FROM tg_links WHERE token=$1 AND expires_at > now() RETURNING user_id", token)
        if not row:
            return None
        await c.execute("UPDATE users SET tg_id=NULL WHERE tg_id=$1", tg_id)
        u = await c.fetchrow("UPDATE users SET tg_id=$1 WHERE id=$2 RETURNING id, name, role", tg_id, row["user_id"])
        await db.audit(c, u["id"], "tg_link", "user", u["id"])
        return dict(u)


@routes.post("/api/clients/{id}/tg-link")
@require("admin", "director", "manager")
async def client_tg_link(request, user):
    from .reminders import client_link_code
    cid = as_int(request.match_info["id"], "id")
    if not await db.pool.fetchval("SELECT 1 FROM clients WHERE id=$1", cid):
        raise bad("Mijoz topilmadi", 404)
    bot_username = request.app.get("bot_username")
    if not bot_username:
        raise bad("Bot ulanmagan")
    code = await client_link_code(cid)
    return J({"url": f"https://t.me/{bot_username}?start=c_{code}"})


# ---------- Excel ----------

@routes.get("/api/export/{kind}")
@require()
async def export(request, user):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    kind = request.match_info["kind"]
    wb = Workbook()
    ws = wb.active
    async with db.pool.acquire() as c:
        if kind == "contracts":
            ws.title = "Shartnomalar"
            ws.append(["Raqam", "Sana", "Mijoz", "Telefon", "Uy", "Narx", "Boshlang‘ich", "Muddat (oy)",
                       "Ustama %", "Jami", "To‘langan", "Qolgan", "Muddati o‘tgan", "Kechikish (kun)",
                       "Keyingi to‘lov", "Menejer"])
            for x in await finance.load_contracts(c):
                nd = x["next_due"]
                ws.append([x["number"], x["contract_date"], x["client_name"], x["client_phone"], x["unit_id"],
                           x["price"], x["down_payment"], x["months"], x["markup_pct"], x["total"],
                           x["paid"], x["remaining"], x["overdue_amount"], x["overdue_days"] or None,
                           nd["due_date"] if nd else None, x["manager_name"]])
        elif kind == "payments":
            t = db.today()
            d0 = as_date(request.query.get("from") or t.replace(day=1).isoformat(), "Boshlanish")
            d1 = as_date(request.query.get("to") or t.isoformat(), "Tugash")
            ws.title = "To‘lovlar"
            ws.append(["№", "Sana", "Shartnoma", "Mijoz", "Uy", "Summa", "Usul", "Izoh", "Kiritdi"])
            for r in await c.fetch(
                    """SELECT p.id, p.paid_at, c.number, cl.full_name, c.unit_id, p.amount, p.method, p.note, u.name
                       FROM payments p JOIN contracts c ON c.id=p.contract_id JOIN clients cl ON cl.id=c.client_id
                       LEFT JOIN users u ON u.id=p.created_by
                       WHERE p.deleted_at IS NULL AND p.paid_at BETWEEN $1 AND $2 ORDER BY p.paid_at, p.id""",
                    d0, d1):
                ws.append([r[0], r[1], r[2], r[3], r[4], r[5], METHODS.get(r[6], r[6]), r[7], r[8]])
        elif kind == "overdue":
            ws.title = "Qarzdorlar"
            ws.append(["Shartnoma", "Mijoz", "Telefon", "Uy", "Oy №", "To‘lov sanasi", "Qarz", "Kechikish (kun)"])
            for r in await finance.dues(c, "overdue"):
                ws.append([r["number"], r["client"], r["phone"], r["unit"], r["n"], r["due_date"], r["left"],
                           r["days"]])
        elif kind == "clients":
            ws.title = "Mijozlar"
            ws.append(["ID", "F.I.Sh.", "Telefon", "Telegram", "Manba", "Bosqich", "Qiziqish", "Qo‘shilgan"])
            for r in await c.fetch("SELECT id, full_name, phone, tg_username, source, stage, interest, created_at "
                                   "FROM clients ORDER BY id"):
                ws.append([r[0], r[1], r[2], ("@" + r[3]) if r[3] else None, SOURCES.get(r[4], r[4]),
                           STAGES.get(r[5], r[5]), r[6], r[7].astimezone(db.TZ).replace(tzinfo=None)])
        else:
            raise bad("Noma’lum eksport", 404)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for col in ws.columns:
        width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 40)
        for cell in col[1:]:
            if isinstance(cell.value, int) and cell.value >= 1000:
                cell.number_format = "#,##0"
            elif isinstance(cell.value, (date, datetime)):
                cell.number_format = "DD.MM.YYYY"
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return web.Response(body=buf.getvalue(), headers={
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": f'attachment; filename="magic-city-{kind}-{db.today().isoformat()}.xlsx"'})
