"""PostgreSQL ulanishi, jadvallar va boshlang'ich ma'lumot.

DATABASE_URL bo'lmasa baza ishlamaydi, lekin bot va Mini App avvalgidek ishlayveradi.
"""
import json
import logging
import math
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import asyncpg

TZ = ZoneInfo("Asia/Tashkent")
pool: asyncpg.Pool | None = None


def today() -> date:
    return datetime.now(TZ).date()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id SERIAL PRIMARY KEY,
  login TEXT UNIQUE NOT NULL,
  pass_hash TEXT NOT NULL,
  name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin','director','manager')),
  phone TEXT,
  tg_id BIGINT,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY,
  user_id INT NOT NULL REFERENCES users ON DELETE CASCADE,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ua TEXT
);
CREATE TABLE IF NOT EXISTS units(
  id TEXT PRIMARY KEY,
  block TEXT NOT NULL,
  floor INT NOT NULL,
  n INT NOT NULL,
  rooms INT NOT NULL,
  area NUMERIC(8,2) NOT NULL,
  price BIGINT NOT NULL,
  status TEXT NOT NULL DEFAULT 'free' CHECK (status IN ('free','held','sold')),
  note TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS clients(
  id SERIAL PRIMARY KEY,
  full_name TEXT NOT NULL,
  phone TEXT,
  phone2 TEXT,
  tg_id BIGINT UNIQUE,
  tg_username TEXT,
  passport TEXT,
  passport_issued TEXT,
  pinfl TEXT,
  birth_date DATE,
  address TEXT,
  source TEXT NOT NULL DEFAULT 'office',
  stage TEXT NOT NULL DEFAULT 'new',
  interest TEXT,
  ref_by BIGINT,
  manager_id INT REFERENCES users,
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS contracts(
  id SERIAL PRIMARY KEY,
  number TEXT UNIQUE NOT NULL,
  client_id INT NOT NULL REFERENCES clients,
  unit_id TEXT NOT NULL REFERENCES units,
  contract_date DATE NOT NULL,
  price BIGINT NOT NULL,
  down_payment BIGINT NOT NULL,
  months INT NOT NULL,
  markup_pct NUMERIC(6,2) NOT NULL DEFAULT 0,
  total BIGINT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','cancelled')),
  manager_id INT REFERENCES users,
  note TEXT,
  created_by INT REFERENCES users,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  cancelled_at TIMESTAMPTZ,
  cancel_reason TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS contracts_unit_active ON contracts(unit_id) WHERE status <> 'cancelled';
CREATE TABLE IF NOT EXISTS installments(
  id SERIAL PRIMARY KEY,
  contract_id INT NOT NULL REFERENCES contracts ON DELETE CASCADE,
  n INT NOT NULL,
  due_date DATE NOT NULL,
  amount BIGINT NOT NULL,
  UNIQUE(contract_id, n)
);
CREATE INDEX IF NOT EXISTS installments_due ON installments(due_date);
CREATE TABLE IF NOT EXISTS payments(
  id SERIAL PRIMARY KEY,
  contract_id INT NOT NULL REFERENCES contracts,
  amount BIGINT NOT NULL CHECK (amount > 0),
  paid_at DATE NOT NULL,
  method TEXT NOT NULL DEFAULT 'cash',
  note TEXT,
  created_by INT REFERENCES users,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ,
  deleted_by INT REFERENCES users,
  delete_reason TEXT
);
CREATE INDEX IF NOT EXISTS payments_contract ON payments(contract_id);
CREATE INDEX IF NOT EXISTS payments_paid_at ON payments(paid_at);
CREATE TABLE IF NOT EXISTS audit(
  id BIGSERIAL PRIMARY KEY,
  user_id INT REFERENCES users,
  action TEXT NOT NULL,
  entity TEXT,
  entity_id TEXT,
  details JSONB,
  at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY,
  value JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS tg_links(
  token TEXT PRIMARY KEY,
  user_id INT NOT NULL REFERENCES users ON DELETE CASCADE,
  expires_at TIMESTAMPTZ NOT NULL
);
ALTER TABLE clients ADD COLUMN IF NOT EXISTS link_code TEXT UNIQUE;
CREATE TABLE IF NOT EXISTS sent_reports(
  key TEXT PRIMARY KEY,
  at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# Sozlamalar (admin paneldan o'zgartiriladi). Kompaniya ma'lumotlari shartnomaga tushadi.
DEFAULT_SETTINGS = {
    "company": {
        "name": "“MAGIC CITY” MChJ",
        "director": "",
        "inn": "",
        "address": "Samarqand viloyati, Kattaqo‘rg‘on",
        "bank": "",
        "account": "",
        "mfo": "",
        "phone": "+998 90 000 00 00",
        "city": "Kattaqo‘rg‘on",
        "object": "Magic City turar-joy majmuasi",
    },
    "contract_prefix": "MC",
    "min_down_pct": 20,
    "max_months": 120,
    # Tayyor muddatlar va qolgan summaga ustama (%). Jadvalda yo'q muddat chiziqli hisoblanadi.
    "terms": [{"m": 6, "markup": 0}, {"m": 12, "markup": 0}, {"m": 18, "markup": 5},
              {"m": 24, "markup": 8}, {"m": 36, "markup": 14}],
    "report_hour": 9,
    "client_reminders": True,   # mijozlarga to'lov eslatmasi (3 kun oldin, to'lov kuni, kechikkanda)
}


async def init():
    """Ulanish havzasini ochadi va jadvallarni yaratadi. Baza yo'q bo'lsa False."""
    global pool
    url = os.environ.get("DATABASE_URL")
    if not url:
        logging.warning("DATABASE_URL yo'q: admin panel va baza o'chiq, bot ishlayveradi")
        return False
    pool = await asyncpg.create_pool(url, min_size=1, max_size=8, init=_init_conn, timeout=15)
    async with pool.acquire() as c:
        await c.execute(SCHEMA)
        await _seed(c)
    if os.environ.get("DEMO_DATA") == "1":
        from . import demo
        if await demo.seed():
            logging.info("Namuna (demo) ma'lumot yozildi")
    return True


async def _init_conn(conn):
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def close():
    if pool:
        await pool.close()


async def get_settings(c=None) -> dict:
    conn = c or pool
    rows = await conn.fetch("SELECT key, value FROM settings")
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    for r in rows:
        if isinstance(out.get(r["key"]), dict) and isinstance(r["value"], dict):
            out[r["key"]].update(r["value"])
        else:
            out[r["key"]] = r["value"]
    return out


async def audit(conn, user_id, action, entity=None, entity_id=None, **details):
    await conn.execute(
        "INSERT INTO audit(user_id, action, entity, entity_id, details) VALUES($1,$2,$3,$4,$5)",
        user_id, action, entity, None if entity_id is None else str(entity_id), details or None)


# ---------- Boshlang'ich ma'lumot ----------

# Mini App'dagi namuna bilan bir xil (webapp/index.html: CFG, TYPES, LAYOUT, UNITS generatori).
_TYPES_AREA = {1: 42.5, 2: 63.8, 3: 86.4, 4: 112.6}
_LAYOUT = [2, 1, 3, 4]
_BLOCKS = ["A", "B", "C"]
_FLOORS = 9
_PRICE_M2 = 6_500_000


def _floor_k(f):
    return 0.93 if f == 1 else 0.96 if f == _FLOORS else 1.03 if 3 <= f <= 6 else 1


def sample_units():
    seed = 7

    def rnd():
        nonlocal seed
        seed = (seed * 16807) % 2147483647
        return seed / 2147483647

    out = []
    for bi, b in enumerate(_BLOCKS):
        for f in range(1, _FLOORS + 1):
            for i, r in enumerate(_LAYOUT):
                x = rnd()
                sold_bias = 0.62 if bi == 0 else 0.38 if bi == 1 else 0.12
                status = "sold" if x < sold_bias else "held" if x < sold_bias + 0.1 else "free"
                area = _TYPES_AREA[r]
                price = math.floor(area * _PRICE_M2 * _floor_k(f) / 100000 + 0.5) * 100000
                out.append((f"{b}-{f}0{i + 1}", b, f, i + 1, r, area, price, status))
    return out


async def _seed(c):
    if not await c.fetchval("SELECT count(*) FROM units"):
        await c.executemany(
            "INSERT INTO units(id, block, floor, n, rooms, area, price, status) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8)", sample_units())
        logging.info("Namuna uylar bazaga yozildi")
    # Birinchi admin: Railway Variables'dagi ADMIN_PASSWORD bilan (login: ADMIN_LOGIN yoki "admin")
    if not await c.fetchval("SELECT count(*) FROM users"):
        pw = os.environ.get("ADMIN_PASSWORD")
        if pw:
            from .auth import hash_password
            await c.execute(
                "INSERT INTO users(login, pass_hash, name, role) VALUES($1,$2,$3,'admin')",
                os.environ.get("ADMIN_LOGIN", "admin").strip().lower(), hash_password(pw), "Administrator")
            logging.info("Birinchi admin yaratildi")
        else:
            logging.warning("Foydalanuvchi yo'q: Railway Variables'ga ADMIN_PASSWORD qo'ying")
