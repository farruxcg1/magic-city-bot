# Magic City: Telegram bot, Mini App, admin panel va rahbar ilovasi

Bitta Railway servisi hammasini ishlatadi:

| Manzil | Kim uchun | Nima |
|---|---|---|
| Telegram bot + `/` | Mijozlar | Mini App: 3D bino, uylar, kalkulyator, ariza. Botda «Mening toʻlovlarim» |
| `/admin` | Admin, menejerlar | Web CRM: mijozlar, uylar, shartnomalar, toʻlovlar, kalendar, hisobot |
| `/rahbar` | Rahbar (iPhone) | Bosh ekranga oʻrnatiladigan ilova (PWA): tushum, qarzdorlar, sotuv |

## Fayllar
- `bot.py` – aiogram 3 bot va server (webhook). Arizalar mijozlar bazasiga ham yoziladi.
- `webapp/index.html` – Mini App. Uylar holati va narxi bazadan olinadi (`/api/public/units`), baza boʻlmasa namuna qoladi.
- `mc/` – backend: `db.py` (PostgreSQL sxema), `api.py` (JSON API), `finance.py` (grafik va qarz hisobi),
  `docs.py` (shartnoma va kvitansiya), `report.py` (rahbarga kunlik hisobot), `reminders.py` (mijozlarga eslatma).
- `admin/index.html` – admin panel. `rahbar/` – rahbar ilovasi (PWA).
- `templates/shartnoma.docx` – shartnoma shabloni (hozircha namuna).
- `scripts/` – `dev_server.py` (lokal sinov), `demo_data.py` (taqdimot uchun namuna), `make_template.py`, `make_icons.py`.

## Railway sozlash (bir marta)
1. Loyiha ichida **+ New → Database → PostgreSQL**.
2. Bot servisi → **Variables**:
   - **New Variable → Add Reference → Postgres → `DATABASE_URL`**
   - `ADMIN_PASSWORD` – birinchi admin paroli (kamida 8 belgi). Login: `admin` (`ADMIN_LOGIN` bilan oʻzgartirish mumkin).
3. Servis oʻzi qayta ishga tushadi. `https://<domen>/admin` ga kirib, **Sozlamalar** (kompaniya rekvizitlari, muddatlar va ustamalar) va **Xodimlar** ni toʻldiring.
   Admin oʻzi kirgandan keyin parolini **Profil** dan oʻzgartiradi; `ADMIN_PASSWORD` faqat birinchi ishga tushishda ishlatiladi.

`DATABASE_URL` boʻlmasa ham bot va Mini App avvalgidek ishlayveradi, faqat admin panel «baza ulanmagan» deb turadi.

## Rollar
- **Admin** – hammasi, xodimlar va sozlamalar.
- **Rahbar** – hammasini koʻradi, toʻlovni oʻchira va shartnomani bekor qila oladi (sababi bilan, jurnalga yoziladi).
- **Menejer** – mijoz, shartnoma va toʻlov kiritadi, oʻchira olmaydi, narxni oʻzgartira olmaydi.

Har bir amal (toʻlov kiritish/oʻchirish, narx oʻzgarishi, shartnoma bekor qilish) **Amallar jurnali** ga yoziladi va oʻchirilmaydi.

## Rahbar ilovasi (iPhone)
App Store kerak emas. iPhone'da **Safari** bilan `https://<domen>/rahbar` ni oching → pastdagi **Ulashish** → **«Bosh ekranga qoʻshish»**.
Belgi ekranda paydo boʻladi va oddiy ilova kabi toʻliq ekranda ochiladi. Login bir marta kiritiladi (60 kun eslab qoladi).

Ilovadagi **Profil → Telegram'ni ulash**: shundan keyin har kuni ertalab (soat Sozlamalarda, standart 9:00) botdan qisqa hisobot keladi, botga `/hisobot` yozib istalgan vaqtda olish mumkin.

## Mijoz bilan Telegram
- Botdan ariza qoldirgan mijoz bazaga oʻzi tushadi (manba: bot yoki tavsiya).
- Ofisda kelgan mijoz uchun: shartnoma sahifasi → **Telegram'ga ulash** → QR kod yoki havola. Mijoz ochib Start bossa, shartnomasi ulanadi.
- Ulangan mijozga: toʻlov kiritilganda kvitansiya, toʻlovdan 3 kun oldin va toʻlov kuni eslatma, kechikkanda 1, 7, 15-kun va keyin har 30 kunda xabar. Botda «💳 Mening toʻlovlarim».

## Shartnoma shabloni
`templates/shartnoma.docx` – Word fayl, ichida `{{ ... }}` oʻrinbosarlar. Magic City'ning haqiqiy shartnomasi kelganda, uning matniga shu oʻrinbosarlar qoʻyiladi:

| Oʻrinbosar | Qiymat |
|---|---|
| `{{ number }}`, `{{ date }}`, `{{ date_long }}`, `{{ city }}` | Shartnoma raqami, sanasi (01.02.2026 / «2026-yil 1-fevral»), shahar |
| `{{ company.name }}`, `.director`, `.inn`, `.address`, `.bank`, `.account`, `.mfo`, `.phone` | Kompaniya (Sozlamalar) |
| `{{ client.name }}`, `.passport`, `.passport_issued`, `.pinfl`, `.address`, `.phone`, `.birth_date` | Mijoz |
| `{{ unit.id }}`, `.block`, `.floor`, `.n`, `.rooms`, `.area` | Uy |
| `{{ price }}` / `{{ price_words }}` | Narx raqamda / soʻz bilan |
| `{{ down }}`, `{{ down_words }}`, `{{ rest }}`, `{{ months }}`, `{{ markup }}` | Boshlangʻich, qolgan, muddat, ustama % |
| `{{ total }}`, `{{ total_words }}`, `{{ installment_total }}`, `{{ monthly }}` | Jami, boʻlib toʻlanadigan, oylik |
| `{{ first_due }}`, `{{ last_due }}` | Birinchi va oxirgi toʻlov sanasi |
| `{%tr for r in schedule %}` … `{{ r.n }}` `{{ r.date }}` `{{ r.amount }}` … `{%tr endfor %}` | Toʻlov grafigi jadvali |

## Taqdimot uchun namuna maʼlumot
Magic City'ga koʻrsatish uchun: Railway Variables → `DEMO_DATA` = `1`. Bazada shartnoma boʻlmasa, ishga tushganda
18 ta namuna mijoz, 12 ta shartnoma va ularning toʻlovlari yoziladi (bir marta).
Haqiqiy ish boshlanishidan oldin: admin panel → **Sozlamalar → Namuna maʼlumotni oʻchirish**, keyin `DEMO_DATA` ni oʻchiring.

## Lokal sinov
```
pip install -r requirements.txt
DATABASE_URL=postgresql://... ADMIN_PASSWORD=... python scripts/dev_server.py   # Telegram'siz: /, /admin, /rahbar
BOT_TOKEN=... WEBAPP_URL=https://... python bot.py                                # faqat bot (polling)
```

## Eslatma
`tg.sendData()` faqat Mini App bot klaviaturasidagi tugma orqali ochilganda ishlaydi.
