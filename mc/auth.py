"""Kirish, sessiyalar va rollar.

Rollar: admin (hammasi), director (rahbar: hammasini ko'radi, to'lovni o'chira oladi),
manager (mijoz, shartnoma, to'lov kiritadi, lekin o'chira olmaydi).
"""
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone

from aiohttp import web

from . import db

COOKIE = "mc_s"
SESSION_DAYS = 60
ROLES = ("admin", "director", "manager")
ROLE_NAMES = {"admin": "Administrator", "director": "Rahbar", "manager": "Menejer"}


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()
    return f"pbkdf2${salt}${h}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()
    return hmac.compare_digest(calc, h)


# Parol tanlashga urinishni sekinlatish: bitta IP yoki bitta login uchun 10 daqiqada 8 ta xato
_fails: dict[str, list[float]] = {}


def _ip(request) -> str:
    # Railway proksisi haqiqiy IP ni X-Forwarded-For oxiriga qo'shadi (boshidagisini mijoz soxtalashtirishi mumkin)
    return (request.headers.get("X-Forwarded-For") or request.remote or "?").split(",")[-1].strip()


def _recent(key: str) -> list[float]:
    now = time.time()
    lst = [t for t in _fails.get(key, []) if now - t < 600]
    _fails[key] = lst
    return lst


def too_many(request, login: str = "") -> bool:
    return len(_recent("ip:" + _ip(request))) >= 8 or (login and len(_recent("u:" + login)) >= 8)


def note_fail(request, login: str = ""):
    _fails.setdefault("ip:" + _ip(request), []).append(time.time())
    if login:
        _fails.setdefault("u:" + login, []).append(time.time())


async def create_session(request, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    exp = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    await db.pool.execute(
        "INSERT INTO sessions(token, user_id, expires_at, ua) VALUES($1,$2,$3,$4)",
        token, user_id, exp, (request.headers.get("User-Agent") or "")[:200])
    await db.pool.execute("DELETE FROM sessions WHERE expires_at < now()")
    return token


def set_cookie(resp: web.Response, token: str, secure: bool):
    resp.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True,
                    samesite="Lax", secure=secure, path="/")


async def current_user(request):
    if "user" in request:
        return request["user"]
    token = request.cookies.get(COOKIE)
    user = None
    if token and db.pool:
        user = await db.pool.fetchrow(
            "SELECT u.id, u.login, u.name, u.role, u.phone, u.tg_id FROM sessions s "
            "JOIN users u ON u.id = s.user_id "
            "WHERE s.token=$1 AND s.expires_at > now() AND u.active", token)
        user = dict(user) if user else None
    request["user"] = user
    return user


def require(*roles):
    """Handler bezagi: kirgan bo'lishi va (berilgan bo'lsa) rol mos kelishi shart."""
    def deco(fn):
        async def wrapped(request):
            if not db.pool:
                raise web.HTTPServiceUnavailable(
                    text='{"error":"Baza ulanmagan (DATABASE_URL)"}', content_type="application/json")
            user = await current_user(request)
            if not user:
                raise web.HTTPUnauthorized(text='{"error":"Kirish kerak"}', content_type="application/json")
            if roles and user["role"] not in roles:
                raise web.HTTPForbidden(text='{"error":"Bu amal uchun huquq yo\'q"}',
                                        content_type="application/json")
            # O'zgartiruvchi so'rovlar faqat o'z sahifamizdan (CSRF himoyasi)
            if request.method not in ("GET", "HEAD") and request.headers.get("X-MC") != "1":
                raise web.HTTPForbidden(text='{"error":"Noto\'g\'ri so\'rov"}', content_type="application/json")
            return await fn(request, user)
        wrapped.__name__ = fn.__name__
        return wrapped
    return deco
