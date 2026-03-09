import asyncio
import random
import time
import psycopg2
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID") 
# URI из настроек Supabase (Database -> Connection String -> URI)
DB_URL = os.getenv("DB_URL")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
def get_db():
    return psycopg2.connect(DB_URL)

def get_user(user_id, username="Unknown"):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT balance, last_farm FROM users WHERE user_id = %s", (user_id,))
    res = cur.fetchone()
    if not res:
        cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s)", (user_id, username))
        conn.commit(); res = (1000, 0)
    cur.close(); conn.close()
    return res

def update_bal(user_id, amount):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, user_id))
    conn.commit(); cur.close(); conn.close()

# --- ЛОГИКА ---

@dp.message(F.chat.type == 'private')
async def private_handler(msg: Message):
    await msg.answer("❌ **Mirvosit Coin** только для групп! Добавь меня в чат.")

# АДМИНКА: выдать [число]
@dp.message(lambda msg: msg.text and msg.text.lower().startswith("выдать") and msg.from_user.id == ADMIN_ID)
async def admin_give(msg: Message):
    parts = msg.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await msg.reply("Пиши: `выдать 500`")
        return
    
    amount = int(parts[1])
    
    # Если это ответ на сообщение — выдаем тому юзеру
    if msg.reply_to_message:
        target_id = msg.reply_to_message.from_user.id
        target_name = msg.reply_to_message.from_user.first_name
        update_bal(target_id, amount)
        await msg.answer(f"✅ Выдано **{amount} MVC** пользователю {target_name}!")
    # Если просто команда — выдаем себе
    else:
        update_bal(msg.from_user.id, amount)
        await msg.answer(f"👑 Ты выдал себе **{amount} MVC**!")

# Баланс
@dp.message(F.text.casefold() == "баланс")
async def balance(msg: Message):
    bal, _ = get_user(msg.from_user.id, msg.from_user.first_name)
    await msg.reply(f"💰 Баланс: **{bal}** MVC")

# Фарма
@dp.message(F.text.casefold() == "фарма")
async def farm(msg: Message):
    bal, last_f = get_user(msg.from_user.id, msg.from_user.first_name)
    now = int(time.time())
    if now - last_f < 14400:
        await msg.reply(f"⏳ Жди еще {(14400-(now-last_f))//60} мин.")
        return
    reward = random.randint(100, 300)
    update_bal(msg.from_user.id, reward)
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE users SET last_farm = %s WHERE user_id = %s", (now, msg.from_user.id))
    conn.commit(); cur.close(); conn.close()
    await msg.reply(f"💎 +{reward} MVC!")

# РУЛЕТКА
@dp.message(F.text.lower().startswith("рулетка"))
async def roulette_cmd(msg: Message):
    parts = msg.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await msg.reply("Пиши: `рулетка [ставка]`")
        return
    
    bet = int(parts[1])
    bal, _ = get_user(msg.from_user.id)
    if bet > bal or bet <= 0:
        await msg.reply("❌ Недостаточно MVC!")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 x2", callback_data=f"r_red_{bet}"),
         InlineKeyboardButton(text="⚫️ x2", callback_data=f"r_black_{bet}"),
         InlineKeyboardButton(text="🟢 x14", callback_data=f"r_green_{bet}")]
    ])
    await msg.reply(f"🎰 Ставка {bet} MVC. Выбирай цвет:", reply_markup=kb)

@dp.callback_query(F.data.startswith("r_"))
async def r_callback(call: CallbackQuery):
    _, color, bet = call.data.split("_")
    bet = int(bet)
    bal, _ = get_user(call.from_user.id)
    
    if bal < bet:
        await call.answer("Недостаточно денег!", show_alert=True)
        return

    res = random.choices(['red', 'black', 'green'], weights=[48, 48, 4])[0]
    
    if color == res:
        mult = 14 if res == 'green' else 2
        win = bet * (mult - 1)
        update_bal(call.from_user.id, win)
        res_text = "🔴 КРАСНОЕ" if res == 'red' else "⚫️ ЧЕРНОЕ" if res == 'black' else "🟢 ЗЕЛЕНОЕ"
        await call.message.edit_text(f"🎰 Выпало {res_text}!\n✅ Выигрыш: **{win+bet}** MVC")
    else:
        update_bal(call.from_user.id, -bet)
        res_text = "🔴 КРАСНОЕ" if res == 'red' else "⚫️ ЧЕРНОЕ" if res == 'black' else "🟢 ЗЕЛЕНОЕ"
        await call.message.edit_text(f"🎰 Выпало {res_text}!\n❌ Ты проиграл **{bet}** MVC")

# ПЕРЕДАТЬ
@dp.message(lambda msg: msg.text and msg.text.lower().startswith("передать"))
async def transfer(msg: Message):
    if not msg.reply_to_message: return
    try:
        amount = int(msg.text.split()[1])
        bal, _ = get_user(msg.from_user.id)
        if bal < amount or amount <= 0: raise Exception()
        update_bal(msg.from_user.id, -amount)
        update_bal(msg.reply_to_message.from_user.id, amount)
        await msg.reply(f"💸 Ты передал **{amount}** MVC пользователю {msg.reply_to_message.from_user.first_name}")
    except: await msg.reply("❌ Ошибка (мало денег или неверная сумма)")

# --- ИГРА МИНЫ (УЛУЧШЕННАЯ) ---
game_states = {}

@dp.message(F.text.lower().startswith("мины"))
async def mines_start(msg: Message):
    parts = msg.text.split()
    if len(parts) < 3: return
    bet, bombs = int(parts[1]), int(parts[2])
    bal, _ = get_user(msg.from_user.id)
    if bet > bal or not (1 <= bombs <= 24): return

    mine_pos = random.sample(range(25), bombs)
    game_id = f"{msg.from_user.id}_{int(time.time())}"
    game_states[game_id] = {"mines": mine_pos, "bet": bet, "opened": 0, "bombs": bombs}
    
    await msg.reply(f"💣 Поле готово! Ставка: {bet} | Мин: {bombs}", 
                    reply_markup=gen_mines_kb(game_id, []))

def gen_mines_kb(game_id, opened_idx, over=False):
    buttons = []
    state = game_states[game_id]
    for i in range(25):
        if i in opened_idx:
            text = "💎"
        elif over and i in state['mines']:
            text = "💣"
        else:
            text = "❓"
        buttons.append(InlineKeyboardButton(text=text, callback_data=f"m_{game_id}_{i}"))
    
    rows = [buttons[i:i+5] for i in range(0, 25, 5)]
    if not over:
        # Считаем множитель: примерно 1.2x за каждый ход (упрощенно)
        mult = round(1 + (state['opened'] * 0.2), 2)
        rows.append([InlineKeyboardButton(text=f"💰 ЗАБРАТЬ ({round(state['bet']*mult)})", callback_data=f"m_{game_id}_stop")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(F.data.startswith("m_"))
async def mines_logic(call: CallbackQuery):
    _, g_id, idx = call.data.split("_")
    if g_id not in game_states: return
    
    state = game_states[g_id]
    if idx == "stop":
        mult = round(1 + (state['opened'] * 0.2), 2)
        win = int(state['bet'] * mult)
        update_bal(call.from_user.id, win - state['bet'])
        await call.message.edit_text(f"💰 Ты вовремя ушел! Выигрыш: **{win}** MVC")
        del game_states[g_id]
        return

    idx = int(idx)
    if idx in state['mines']:
        update_bal(call.from_user.id, -state['bet'])
        await call.message.edit_text("💥 БАБАХ! Ставка сгорела.", reply_markup=gen_mines_kb(g_id, [], True))
        del game_states[g_id]
    else:
        state['opened'] += 1
        await call.message.edit_reply_markup(reply_markup=gen_mines_kb(g_id, [idx]))
      
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
