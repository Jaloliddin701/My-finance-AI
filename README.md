# My Finance AI — Telegram bot

Bank SMS/notification (HUMO, Uzcard, Click, Payme, TBC...) matnini yuborsangiz, bot Google Gemini yordamida
daromad/xarajatlarni ajratib, bazaga saqlaydi va statistikani ko'rsatadi.

## Sozlash

Kerakli muhit o'zgaruvchilari (environment variables):

| O'zgaruvchi | Tavsif |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather bergan token |
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey dan olingan bepul kalit |
| `AI_MODEL` | (ixtiyoriy) standart: `gemini-2.5-flash` |
| `OPENAI_API_KEY` | (ixtiyoriy) Gemini o'rniga OpenAI ishlatish uchun — `GEMINI_API_KEY` bo'lmasa ishlatiladi |
| `DB_PATH` | (ixtiyoriy) SQLite fayl yo'li, standart: `finance.db` |

## Gemini kalitini olish (bepul)

1. https://aistudio.google.com/apikey ga Google hisobingiz bilan kiring.
2. **Create API key** tugmasini bosing.
3. Kalitni serverdagi `GEMINI_API_KEY` o'zgaruvchisiga qo'ying. Kalitni hech qachon kodga yoki GitHub'ga yozmang.

## Lokal ishga tushirish

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="123456:ABC..."
export GEMINI_API_KEY="AIza..."
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
