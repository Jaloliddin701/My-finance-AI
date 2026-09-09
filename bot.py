import asyncio
import json
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from openai import AsyncOpenAI

TELEGRAM_BOT_TOKEN = "ВАШ_TELEGRAM_TOKEN"
OPENAI_API_KEY = "ВАШ_OPENAI_API_KEY"

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("finance.db")
    cursor = conn.cursor()
    cursor.execute("""
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
    conn.commit()
    conn.close()

def add_transactions(user_id, transactions_list):
    conn = sqlite3.connect("finance.db")
    cursor = conn.cursor()
    for item in transactions_list:
        cursor.execute("""
            INSERT INTO transactions (user_id, type, amount, category, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id, 
            item.get("type"), 
            float(item.get("amount", 0)), 
            item.get("category", "Прочее"), 
            item.get("description", ""), 
            item.get("date", datetime.now().strftime("%Y-%m-%d %H:%M"))
        ))
    conn.commit()
    conn.close()

def get_stats(user_id):
    conn = sqlite3.connect("finance.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE user_id = ? AND type = 'income'", (user_id,))
    total_income = cursor.fetchone()[0] or 0.0

    cursor.execute("SELECT SUM(amount) FROM transactions WHERE user_id = ? AND type = 'expense'", (user_id,))
    total_expense = cursor.fetchone()[0] or 0.0

    cursor.execute("""
        SELECT category, SUM(amount) FROM transactions 
        WHERE user_id = ? AND type = 'expense' 
        GROUP BY category ORDER BY SUM(amount) DESC
    """, (user_id,))
    categories = cursor.fetchall()
    
    conn.close()
    return total_income, total_expense, categories

# --- ОБРАБОТЧИКИ КОМАНД ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer(
        "👋 Привет! Я твой автоматический финансовый учетчик.\n\n"
        "Отправляй мне любые SMS, чеки Click/Payme/TBC или уведомления HUMO/Uzcard.\n"
        "Я автоматически определю зарплаты, авансы, оплаты и переводы!\n\n"
        "📊 Команда /stats покажет баланс и аналитику.",
        parse_mode="Markdown"
    )

@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    income, expense, categories = get_stats(message.from_user.id)
    balance = income - expense
    
    msg = f"📊 *Ваша финансовая статистика (UZS):*\n\n"
    msg += f"📥 Всего доходов: *{income:,.0f} UZS*\n"
    msg += f"📤 Всего расходов: *{expense:,.0f} UZS*\n"
    msg += f"💰 Баланс: *{balance:,.0f} UZS*\n\n"
    
    if categories:
        msg += "📉 *Расходы по категориям:*\n"
        for cat, sum_amt in categories:
            msg += f"• {cat}: *{sum_amt:,.0f} UZS*\n"
            
    await message.answer(msg, parse_mode="Markdown")

@dp.message()
async def handle_bank_messages(message: types.Message):
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")

    prompt = f"""
    Ты — продвинутый парсер банковских уведомлений (Узбекистан: HUMO, Uzcard, Click, TBC, Payme).
    Проанализируй текст сообщения. В нем может быть одна или несколько финансовых операций.

    ПРАВИЛА ОПРЕДЕЛЕНИЯ:
    1. Уведомления типа "Счет по карте изменен" с приходом средств или банковские зачисления по зарплатным картам считай как ДОХОД ("income").
    2. Если в тексте упоминается аванс, зарплата или госслужба, устанавливай категорию "Зарплата".
    3. Оплаты, покупки, комиссии, снятия и переводы ➖ считай как РАСХОД ("expense").
    4. Преобразуй суммы вида "3.001.467,66" в чистое число "3001467.66".

    Верни JSON с единственным ключом "items", содержащим МАССИВ объектов:
    [
      {{
        "type": "income" или "expense",
        "amount": числовое значение суммы,
        "category": "Зарплата", "Такси", "Переводы", "Рестораны/Еда", "Продукты", "Связь", "Развлечения" или "Прочее",
        "description": краткое описание (например: "Аванс", "Расчет / Зарплата", "YandexGO Taxi", "TBC P2P"),
        "date": дата из чека в формате "YYYY-MM-DD HH:MM" (если год не указан, бери 2026)
      }}
    ]

    Текст чеков:
    "{message.text}"
    """

    try:
        response = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        items = result.get("items", [])
        
        if items:
            add_transactions(message.from_user.id, items)
            
            response_msg = f"✅ Обработано операций: *{len(items)}*\n\n"
            for item in items:
                icon = "🟢 Доход" if item["type"] == "income" else "🔴 Расход"
                response_msg += f"{icon}: *{item['amount']:,.0f} UZS*\n"
                response_msg += f"📍 {item['description']} ({item['category']})\n\n"
                
            await message.answer(response_msg, parse_mode="Markdown")
        else:
            await message.answer("Не удалось найти операции в сообщении.")
            
    except Exception as e:
        await message.answer("Произошла ошибка при обработке чека.")
        print(f"Ошибка: {e}")

async def main():
    init_db()
    print("Бот готов к приему зарплатных и банковских сообщений!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
