# Magic City: Claude uchun eslatma

Foydalanuvchi bilan oʻzbek tilida gaplash.

- Deploy: Railway (`main` ga push → avtomatik deploy). Render ishlatilmaydi (`render.yaml` eski).
- Bitta servis: bot (webhook), Mini App (`/`), admin panel (`/admin`), rahbar PWA (`/rahbar`), API (`/api/...`).
- Baza: Railway PostgreSQL, `DATABASE_URL`. Jadvallar `mc/db.py` da, ishga tushganda oʻzi yaratiladi (`CREATE ... IF NOT EXISTS`, ustun qoʻshish `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`).
- Maxfiy qiymatlarni (`BOT_TOKEN`, `ADMIN_PASSWORD`, `DATABASE_URL`) foydalanuvchi Railway Variables'ga OʻZI kiritadi. Ularni chatda soʻrama.
- Baza ulanmasa ham bot va Mini App ishlashi shart (`safe()` va `db.pool is None` tekshiruvlari).
- Pul hamma joyda butun soʻm (int). Toʻlovlar grafikdagi eng eski qarzdan boshlab yopiladi (`mc/finance.py: allocate`).
- Sinov: `scripts/dev_server.py` (Telegram'siz). Batafsil: README.md.
