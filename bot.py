import asyncio
import html
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("finance-bot")

# --- НАСТРОЙКИ (берутся из переменных окружения) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
DB_PATH = os.getenv("DB_PATH", "finance.db")

CATEGORIES = [
    "Зарплата", "Такси", "Переводы", "Рестораны/Еда", "Продукты",
    "Связь", "Развлечения", "Коммунальные", "Здоровье", "Одежда", "Прочее",
]
DATE_FORMAT = "%Y-%m-%d %H:%M"

dp = Dispatcher()
ai_client: AsyncOpenAI | None = None


# --- БАЗА ДАННЫХ ---
def db():
    return sqlite3.connect(DB_PATH)


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,        -- 'expense' или 'income'
                amount REAL,      -- сумма в UZS
                category TEXT,    -- категория
                description TEXT, -- описание/место
                created_at TEXT   -- дата
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id, created_at)")


def add_transactions(user_id, items):
    with db() as conn:
        conn.executemany(
            """
            INSERT INTO transactions (user_id, type, amount, category, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [(user_id, i["type"], i["amount"], i["category"], i["description"], i["date"]) for i in items],
        )


def get_stats(user_id, since=None):
    where = "user_id = ?"
    params = [user_id]
    if since:
        where += " AND created_at >= ?"
        params.append(since)

    with db() as conn:
        rows = conn.execute(
            f"SELECT type, COALESCE(SUM(amount), 0) FROM transactions WHERE {where} GROUP BY type",
            params,
        ).fetchall()
        totals = dict(rows)
        categories = conn.execute(
            f"""
            SELECT category, SUM(amount) FROM transactions
            WHERE {where} AND type = 'expense'
            GROUP BY category ORDER BY SUM(amount) DESC
            """,
            params,
        ).fetchall()
    return totals.get("income", 0.0), totals.get("expense", 0.0), categories


def get_last(user_id, limit=10):
    with db() as conn:
        return conn.execute(
            """
            SELECT id, type, amount, category, description, created_at FROM transactions
            WHERE user_id = ? ORDER BY id DESC LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()


def delete_transaction(user_id, tx_id=None):
    """Удаляет операцию по id (или последнюю). Возвращает удалённую строку или None."""
    with db() as conn:
        if tx_id is None:
            row = conn.execute(
                "SELECT id, type, amount, description FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id, type, amount, description FROM transactions WHERE user_id = ? AND id = ?",
                (user_id, tx_id),
            ).fetchone()
        if row:
            conn.execute("DELETE FROM transactions WHERE id = ?", (row[0],))
        return row


def reset_user(user_id):
    with db() as conn:
        return conn.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,)).rowcount


# --- ВСПОМОГАТЕЛЬНЫЕ ---
def fmt(amount):
    return f"{amount:,.0f}".replace(",", " ")


def parse_amount(value):
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace(" ", "").replace(" ", "")
    # "3.001.467,66" -> "3001467.66"; "3,001,467.66" -> "3001467.66"
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        sep = "," if "," in s else "." if "." in s else None
        if sep:
            parts = s.split(sep)
            # "12,500" / "1.250.000" — разделители тысяч; "12,50" — дробная часть
            if len(parts) > 2 or len(parts[-1]) == 3:
                s = "".join(parts)
            else:
                s = s.replace(",", ".")
    return float(s)


def normalize_item(raw):
    """Проверяет и приводит ответ модели к нужному виду. Возвращает None для мусора."""
    if not isinstance(raw, dict):
        return None
    tx_type = str(raw.get("type", "")).lower()
    if tx_type not in ("income", "expense"):
        return None
    try:
        amount = abs(parse_amount(raw.get("amount", 0)))
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None

    category = raw.get("category") or "Прочее"
    if category not in CATEGORIES:
        category = "Прочее"

    date = str(raw.get("date") or "")
    try:
        date = datetime.strptime(date, DATE_FORMAT).strftime(DATE_FORMAT)
    except ValueError:
        date = datetime.now().strftime(DATE_FORMAT)

    return {
        "type": tx_type,
        "amount": amount,
        "category": category,
        "description": str(raw.get("description") or "")[:200],
        "date": date,
    }


def system_prompt():
    now = datetime.now()
    return f"""
Ты — продвинутый парсер банковских уведомлений (Узбекистан: HUMO, Uzcard, Click, TBC, Payme, Uzum, Kapitalbank и др.).
Пользователь присылает текст. В нём может быть одна или несколько финансовых операций.
Сегодня: {now.strftime(DATE_FORMAT)}.

ПРАВИЛА:
1. Уведомления "Счет по карте изменен" с приходом средств, зачисления, пополнения, входящие переводы — ДОХОД ("income").
2. Если упоминается аванс, зарплата или госслужба — категория "Зарплата".
3. Оплаты, покупки, комиссии, снятия наличных и исходящие переводы — РАСХОД ("expense").
4. Суммы вида "3.001.467,66" преобразуй в число 3001467.66. Сумма всегда положительная.
5. Если в тексте нет финансовых операций — верни пустой массив.

Верни JSON с единственным ключом "items" — МАССИВ объектов:
{{
  "type": "income" или "expense",
  "amount": число,
  "category": одно из {json.dumps(CATEGORIES, ensure_ascii=False)},
  "description": краткое описание (например: "Аванс", "YandexGO Taxi", "TBC P2P"),
  "date": дата операции в формате "YYYY-MM-DD HH:MM" (если год не указан — {now.year}; если даты нет — текущая)
}}
"""


async def parse_with_ai(text):
    response = await ai_client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    result = json.loads(response.choices[0].message.content or "{}")
    items = result.get("items", []) if isinstance(result, dict) else []
    return [n for n in (normalize_item(i) for i in items) if n]


def stats_text(title, income, expense, categories):
    msg = f"📊 <b>{title}</b>\n\n"
    msg += f"📥 Доходы: <b>{fmt(income)} UZS</b>\n"
    msg += f"📤 Расходы: <b>{fmt(expense)} UZS</b>\n"
    msg += f"💰 Баланс: <b>{fmt(income - expense)} UZS</b>\n"
    if categories:
        msg += "\n📉 <b>Расходы по категориям:</b>\n"
        for cat, total in categories:
            share = total / expense * 100 if expense else 0
            msg += f"• {html.escape(cat)}: <b>{fmt(total)} UZS</b> ({share:.0f}%)\n"
    return msg


# --- ОБРАБОТЧИКИ КОМАНД ---
HELP_TEXT = (
    "👋 Привет! Я твой автоматический финансовый учётчик.\n\n"
    "Отправляй мне любые SMS, чеки Click/Payme/TBC или уведомления HUMO/Uzcard "
    "(можно сразу несколько). Я сам определю зарплаты, авансы, оплаты и переводы!\n\n"
    "<b>Команды:</b>\n"
    "/stats — баланс и аналитика за всё время\n"
    "/month — статистика за текущий месяц\n"
    "/last — последние 10 операций\n"
    "/undo — удалить последнюю операцию\n"
    "/delete <code>ID</code> — удалить операцию по номеру\n"
    "/reset — удалить все мои данные"
)


@dp.message(Command("start", "help"))
async def start_cmd(message: types.Message):
    await message.answer(HELP_TEXT)


@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    income, expense, categories = get_stats(message.from_user.id)
    await message.answer(stats_text("Статистика за всё время (UZS)", income, expense, categories))


@dp.message(Command("month"))
async def month_cmd(message: types.Message):
    now = datetime.now()
    since = now.strftime("%Y-%m-01 00:00")
    income, expense, categories = get_stats(message.from_user.id, since=since)
    await message.answer(stats_text(f"Статистика за {now.strftime('%m.%Y')} (UZS)", income, expense, categories))


@dp.message(Command("last"))
async def last_cmd(message: types.Message):
    rows = get_last(message.from_user.id)
    if not rows:
        await message.answer("Операций пока нет.")
        return
    msg = "🧾 <b>Последние операции:</b>\n\n"
    for tx_id, tx_type, amount, category, description, created_at in rows:
        sign = "🟢 +" if tx_type == "income" else "🔴 −"
        msg += (
            f"<code>#{tx_id}</code> {html.escape(created_at or '')}\n"
            f"{sign}{fmt(amount)} UZS — {html.escape(description or '')} ({html.escape(category or '')})\n\n"
        )
    msg += "Удалить: /delete <code>ID</code>"
    await message.answer(msg)


@dp.message(Command("undo"))
async def undo_cmd(message: types.Message):
    row = delete_transaction(message.from_user.id)
    if row:
        await message.answer(f"🗑 Удалена операция <code>#{row[0]}</code>: {fmt(row[2])} UZS — {html.escape(row[3] or '')}")
    else:
        await message.answer("Нечего удалять.")


@dp.message(Command("delete"))
async def delete_cmd(message: types.Message, command: CommandObject):
    arg = (command.args or "").strip().lstrip("#")
    if not arg.isdigit():
        await message.answer("Укажите номер операции, например: /delete 12\nНомера видно в /last")
        return
    row = delete_transaction(message.from_user.id, int(arg))
    if row:
        await message.answer(f"🗑 Удалена операция <code>#{row[0]}</code>: {fmt(row[2])} UZS — {html.escape(row[3] or '')}")
    else:
        await message.answer("Операция с таким номером не найдена.")


@dp.message(Command("reset"))
async def reset_cmd(message: types.Message, command: CommandObject):
    if (command.args or "").strip().lower() != "да":
        await message.answer("⚠️ Это удалит ВСЕ ваши операции. Для подтверждения отправьте: /reset да")
        return
    count = reset_user(message.from_user.id)
    await message.answer(f"🗑 Удалено операций: {count}")


@dp.message(F.text | F.caption)
async def handle_bank_messages(message: types.Message):
    text = (message.text or message.caption or "").strip()
    if text.startswith("/"):
        await message.answer("Неизвестная команда. Список команд: /help")
        return

    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")

    try:
        items = await parse_with_ai(text[:8000])
    except Exception:
        log.exception("Ошибка при обращении к OpenAI")
        await message.answer("⚠️ Произошла ошибка при обработке чека. Попробуйте ещё раз позже.")
        return

    if not items:
        await message.answer("Не удалось найти операции в сообщении.")
        return

    add_transactions(message.from_user.id, items)

    response_msg = f"✅ Обработано операций: <b>{len(items)}</b>\n\n"
    for item in items:
        icon = "🟢 Доход" if item["type"] == "income" else "🔴 Расход"
        response_msg += f"{icon}: <b>{fmt(item['amount'])} UZS</b>\n"
        response_msg += f"📍 {html.escape(item['description'])} ({html.escape(item['category'])})\n"
        response_msg += f"🕒 {item['date']}\n\n"
    response_msg += "Ошиблись? /undo удалит последнюю операцию."
    await message.answer(response_msg)


@dp.message()
async def unsupported(message: types.Message):
    await message.answer("Пока я понимаю только текст. Перешлите или вставьте текст SMS/уведомления.")


async def main():
    global ai_client
    missing = [name for name, value in (("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN), ("OPENAI_API_KEY", OPENAI_API_KEY)) if not value]
    if missing:
        sys.exit(f"Не заданы переменные окружения: {', '.join(missing)}. См. README.md")

    init_db()
    ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.set_my_commands([
        types.BotCommand(command="stats", description="Баланс за всё время"),
        types.BotCommand(command="month", description="Статистика за месяц"),
        types.BotCommand(command="last", description="Последние операции"),
        types.BotCommand(command="undo", description="Удалить последнюю операцию"),
        types.BotCommand(command="help", description="Помощь"),
    ])
    log.info("Бот готов к приему зарплатных и банковских сообщений!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
