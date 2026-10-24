# Magic City: Telegram bot + Mini App (demo)

## Fayllar
- `webapp/index.html` – Mini App (bitta fayl, kutubxonasiz). Telegram ichida ochilganda faqat ilova koʻrinadi; brauzerda taklif matni bilan birga chiqadi.
- `bot.py` – aiogram 3 asosidagi bot: `/start`, Mini App tugmasi, arizani menejerlar guruhiga yuborish, kontakt, manzil, referal havola.

## Ishga tushirish (Railway)
Bitta servis ham botni, ham Mini App sahifasini ishlatadi. `railway.json` start buyrugʻini, `.python-version` Python versiyasini belgilaydi.
1. railway.com ga GitHub orqali kiring → **New Project → Deploy from GitHub repo** → `magic-city-bot`.
2. Servis → **Variables** → `BOT_TOKEN` (@BotFather bergan token). `MANAGER_CHAT_ID` hozircha shart emas.
3. Servis → **Settings → Networking → Generate Domain** (port soʻralsa: `8080`). Railway `RAILWAY_PUBLIC_DOMAIN` ni oʻzi beradi, bot shu manzilga webhook oʻrnatadi.
4. **Deploy** (yoki Deployments → Redeploy). `https://<domen>/health` "ok" qaytarishi kerak, botga `/start` yozing.
5. Menejerlar guruhi: guruh oching, botni qoʻshing, `/id` yozing → chiqqan raqamni **Variables → `MANAGER_CHAT_ID`** ga qoʻying.

Domen yaratilmasa, bot ishga tushmaydi va logda "Server manzili topilmadi" deb yozadi.

## Ishga tushirish (Render, bepul, 15–20 daqiqa)
Bitta server ham botni, ham Mini App sahifasini ishlatadi.
1. GitHub'da yangi repo oching va shu papkadagi hamma faylni yuklang (`bot.py`, `requirements.txt`, `render.yaml`, `webapp/index.html`).
2. render.com ga GitHub orqali kiring → **New → Blueprint** → shu repo'ni tanlang.
3. Render `BOT_TOKEN` soʻraydi: @BotFather bergan tokenni shu yerga qoʻying. `MANAGER_CHAT_ID` ni hozircha boʻsh qoldiring. **Apply** bosing.
4. Bir necha daqiqada `https://magic-city-bot-xxxx.onrender.com` manzil chiqadi. Botga `/start` yozing, ilova ochilishi kerak.
5. Menejerlar uchun Telegram guruh oching, botni qoʻshing va guruhga `/id` yozing. Bot guruh ID sini yuboradi (masalan `-1001234567890`).
6. Render → Environment → `MANAGER_CHAT_ID` ga shu raqamni yozing → Save (servis qayta ishga tushadi).
7. (Ixtiyoriy) @BotFather → `/setmenubutton` → Render manzili.

Bepul tarifda server 15 daqiqa ishlatilmasa uxlaydi va birinchi xabarga 30–50 soniyada javob beradi. Doimiy ishlatish uchun Render Starter ($7/oy) yoki arzon VPS.

Lokal sinov: `pip install -r requirements.txt`, `BOT_TOKEN=... WEBAPP_URL=https://... python bot.py` (polling rejimi).

## Haqiqiy maʼlumotga oʻtkazish
`index.html` ichidagi `CFG` (m² narxi, minimal boshlangʻich toʻlov, muddatlar va ustama, ipoteka foizi, telefon), `TYPES` (xonadon turlari, maydonlar) va `UNITS` generatori namuna maʼlumot. Kompaniyadan Excel roʻyxat olingach, ular haqiqiy roʻyxat bilan almashtiriladi. 2-bosqichda bu maʼlumot admin panel/Google Sheets orqali boshqariladi.

## Eslatma
`tg.sendData()` faqat Mini App bot klaviaturasidagi tugma orqali ochilganda ishlaydi. Menyu tugmasi yoki havola orqali ochilganda arizalar uchun kichik backend (POST /lead) kerak boʻladi – 2-bosqich.
