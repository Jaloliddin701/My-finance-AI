# My Finance AI — Telegram bot

Bank SMS/notification (HUMO, Uzcard, Click, Payme, TBC...) matnini yuborsangiz, bot OpenAI yordamida
daromad/xarajatlarni ajratib, bazaga saqlaydi va statistikani ko'rsatadi.

## Sozlash

Kerakli muhit o'zgaruvchilari (environment variables):

| O'zgaruvchi | Tavsif |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather bergan token |
| `OPENAI_API_KEY` | https://platform.openai.com/api-keys dan olingan kalit |
| `OPENAI_MODEL` | (ixtiyoriy) standart: `gpt-4o-mini` |
| `DB_PATH` | (ixtiyoriy) SQLite fayl yo'li, standart: `finance.db` |

## Lokal ishga tushirish

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="123456:ABC..."
export OPENAI_API_KEY="sk-..."
python bot.py
```

## Serverga joylash (Railway / Render / Heroku)

`Procfile` tayyor (`worker: python bot.py`). Platformada yuqoridagi o'zgaruvchilarni
"Variables / Config Vars" bo'limiga kiriting va worker jarayonini yoqing.
Ma'lumotlar o'chib ketmasligi uchun `DB_PATH` ni doimiy diskka (volume) yo'naltiring.

## Buyruqlar

- `/stats` — umumiy balans va kategoriyalar
- `/month` — joriy oy statistikasi
- `/last` — oxirgi 10 ta operatsiya
- `/undo` — oxirgi operatsiyani o'chirish
- `/delete ID` — operatsiyani raqami bo'yicha o'chirish
- `/reset да` — barcha ma'lumotlarni o'chirish
