# Magic City bot: vazifa (Claude uchun)

Bu papkada tayyor loyiha bor: Telegram bot (`bot.py`, aiogram 3) va Mini App (`webapp/index.html`). Bitta server ikkalasini ham ishlatadi.

Qilish kerak:
1. Shu fayllarni GitHub repo `farruxcg1/magic-city-bot` ga yuklash (repo bo'sh, `main` branch).
2. Foydalanuvchiga Render'da deploy qilishda yordam berish: render.com → GitHub bilan kirish → New → Blueprint → shu repo. `render.yaml` hammasini sozlaydi.
3. `BOT_TOKEN` ni foydalanuvchi O'ZI Render formasiga kiritadi. Tokenni so'rama, chatga yozdirma.
4. Deploy tugagach: `https://...onrender.com/health` "ok" qaytarishi kerak, botga /start yozilganda Mini App tugmasi chiqadi.
5. Menejerlar guruhi: guruh ochish, botni qo'shish, guruhda `/id` yozish, chiqqan raqamni Render → Environment → `MANAGER_CHAT_ID` ga qo'yish.

Batafsil: README.md. Foydalanuvchi bilan o'zbek tilida gaplash.
