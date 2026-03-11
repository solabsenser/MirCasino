import asyncio
import os
import random
import time

import psycopg2
from aiogram import Bot, Dispatcher, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
DB_URL = os.getenv("DB_URL")

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
def get_db():
    return psycopg2.connect(DB_URL)


def get_user(user_id, username="Unknown"):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT balance, last_farm FROM users WHERE user_id = %s", (user_id,))
    res = cur.fetchone()
    if not res:
        cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s)", (user_id, username))
        conn.commit()
        res = (1000, 0)
    else:
        cur.execute("UPDATE users SET username = %s WHERE user_id = %s", (username, user_id))
        conn.commit()
    cur.close()
    conn.close()
    return res


def update_bal(user_id, amount):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, user_id))
    conn.commit()
    cur.close()
    conn.close()


# --- ПАМЯТЬ СЕССИЙ ---
roulette_games = {}
roulette_sessions = {}
mines_sessions = {}
roulette_history = {}

# --- ЛОГИКА ---
@dp.message(F.chat.type == "private")
async def private_handler(msg: Message):
    await msg.answer("❌ **Mirvosit Coin** только для групп! Добавь меня в чат.")


@dp.message(lambda msg: msg.text and msg.text.lower().startswith("выдать") and msg.from_user.id == ADMIN_ID)
async def admin_give(msg: Message):
    parts = msg.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await msg.reply("Пиши: `выдать 500`")
        return

    amount = int(parts[1])

    if msg.reply_to_message:
        target_id = msg.reply_to_message.from_user.id
        target_name = msg.reply_to_message.from_user.first_name
        update_bal(target_id, amount)
        await msg.answer(f"✅ Выдано **{amount} MVC** пользователю {target_name}!")
    else:
        update_bal(msg.from_user.id, amount)
        await msg.answer(f"👑 Ты выдал себе **{amount} MVC**!")


@dp.message(F.text.casefold() == "баланс")
async def balance(msg: Message):
    bal, _ = get_user(msg.from_user.id, msg.from_user.first_name)
    await msg.reply(f"💰 Баланс: **{bal}** MVC")


@dp.message(F.text.casefold() == "бонус")
async def daily_bonus(msg: Message):
    bal, last_bonus = get_user(msg.from_user.id, msg.from_user.first_name)
    now = int(time.time())
    cooldown = 86400
    if now - last_bonus < cooldown:
        left_h = (cooldown - (now - last_bonus)) // 3600
        await msg.reply(f"⏳ Ежедневный бонус уже забран. До следующего: ~{left_h} ч.")
        return

    reward = random.randint(250, 750)
    update_bal(msg.from_user.id, reward)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET last_farm = %s WHERE user_id = %s", (now, msg.from_user.id))
    conn.commit()
    cur.close()
    conn.close()
    await msg.reply(f"🎁 Ежедневный бонус: +**{reward} MVC**")


@dp.message(F.text.casefold() == "фарма")
async def farm_removed(msg: Message):
    await msg.reply("❌ Команда `фарма` удалена. Используй `бонус` 1 раз в день 🎁")


@dp.message(F.text.casefold() == "профиль")
async def profile(msg: Message):
    bal, last_bonus = get_user(msg.from_user.id, msg.from_user.first_name)
    now = int(time.time())
    left = max(0, 86400 - (now - last_bonus))
    bonus_text = "доступен ✅" if left == 0 else f"через ~{left // 3600} ч."
    text = (
        "💎 **ПРОФИЛЬ ИГРОКА** 💎\n"
        f"👤 Ник: {msg.from_user.full_name}\n"
        f"🆔 ID: `{msg.from_user.id}`\n"
        f"💰 Баланс: **{bal} MVC**\n"
        f"🎁 Бонус: {bonus_text}\n"
        "━━━━━━━━━━━━━━\n"
        "Удачи за столами, хайроллер 🏆"
    )
    await msg.reply(text)


@dp.message(F.text.casefold() == "топ")
async def top_players(msg: Message):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        await msg.reply("Пока нет игроков в рейтинге.")
        return

    lines = ["🏆 **ТОП ИГРОКОВ**"]
    medals = ["🥇", "🥈", "🥉"]
    for i, (username, bal) in enumerate(rows, start=1):
        prefix = medals[i - 1] if i <= 3 else f"{i}."
        lines.append(f"{prefix} {username}: **{bal} MVC**")
    await msg.reply("\n".join(lines))
    

@dp.message(F.text.casefold() == "лог")
async def roulette_log(msg: Message):

    chat_id = msg.chat.id

    if chat_id not in roulette_history or not roulette_history[chat_id]:
        await msg.reply("История рулетки пуста.")
        return

    nums = roulette_history[chat_id]

    text = "📊 Последние 10 чисел:\n\n"

    for n in reversed(nums):

        if n == 0:
            color = "🟢"

        elif n in red_numbers:
            color = "🔴"

        else:
            color = "⚫"

        text += f"{n}{color}\n"

    await msg.reply(text)
    
# --- РУЛЕТКА С ПОДТВЕРЖДЕНИЕМ "ГО" И ОТМЕНОЙ ---

red_numbers = {
1,3,5,7,9,12,14,16,18,
19,21,23,25,27,30,32,34,36
}

black_numbers = {
2,4,6,8,10,11,13,15,17,
20,22,24,26,28,29,31,33,35
}


@dp.message(lambda msg: bool(msg.text and len(msg.text.lower().split()) == 2 and msg.text.lower().split()[0].isdigit()))
async def roulette_cmd(msg: Message):

    if msg.chat.type == "private":
        return

    parts = msg.text.lower().split()

    if len(parts) != 2:
        return

    if not parts[0].isdigit():
        return

    bet = int(parts[0])
    bet_type = parts[1]
    value = None

    colors = {
        "к": "red",
        "ч": "black"
    }

    if bet_type in colors:
        bet_type = colors[bet_type]

    elif bet_type in ["чет","чёт","четное","чётное"]:
        bet_type = "even"

    elif bet_type == ["нечет","нечетное","нечёт","нечётное"]:
        bet_type = "odd"

    elif bet_type in ["1-12","13-24","25-36"]:
        value = bet_type
        bet_type = "range"

    elif bet_type.isdigit():

        num = int(bet_type)

        if 0 <= num <= 36:
            value = num
            bet_type = "number"
        else:
            return

    else:
        return


    bal,_ = get_user(msg.from_user.id, msg.from_user.first_name)

    if bet > bal or bet <= 0:
        await msg.reply("❌ Недостаточно MVC")
        return


    chat_id = msg.chat.id

    if chat_id not in roulette_games:
        roulette_games[chat_id] = []


    roulette_games[chat_id].append({
        "user": msg.from_user.id,
        "name": msg.from_user.first_name,
        "bet": bet,
        "type": bet_type,
        "value": value
    })


    await msg.reply(
        f"🎰 {msg.from_user.first_name} поставил {bet} MVC\n"
        f"Напишите **го** чтобы крутить рулетку"
    )


@dp.callback_query(F.data.startswith("rpick:"))
async def roulette_pick(call: CallbackQuery):

    _, color, bet_str = call.data.split(":")
    bet = int(bet_str)

    bal,_ = get_user(call.from_user.id, call.from_user.first_name)

    if bal < bet:
        await call.answer("Недостаточно денег!", show_alert=True)
        return

    roulette_sessions[call.from_user.id] = {"bet": bet, "color": color}

    color_txt = {"red": "красное", "black": "черное", "green": "зеленое"}[color]

    await call.message.edit_text(
        f"✅ Принято: ставка **{bet} MVC** на **{color_txt}**.\n"
        "Напиши `го`, чтобы начать крутить, или `отмена`."
    )


@dp.callback_query(F.data == "rcancel")
async def roulette_cancel_button(call: CallbackQuery):

    roulette_sessions.pop(call.from_user.id, None)

    await call.message.edit_text("↩️ Ставка отменена.")


@dp.message(F.text.casefold() == "отмена")
async def cancel_bet(msg: Message):

    chat_id = msg.chat.id

    if chat_id in roulette_games:

        roulette_games[chat_id] = [
            x for x in roulette_games[chat_id]
            if x["user"] != msg.from_user.id
        ]

        await msg.reply("↩️ Ставка отменена.")

    else:
        await msg.reply("Нет активной ставки.")


@dp.message(F.text.casefold() == "го")
async def roulette_go(msg: Message):

    if msg.chat.type == "private":
        return

    chat_id = msg.chat.id

    if chat_id not in roulette_games or not roulette_games[chat_id]:
        return


    result = random.randint(0,36)

    if chat_id not in roulette_history:
        roulette_history[chat_id] = []

    roulette_history[chat_id].append(result)

    if len(roulette_history[chat_id]) > 10:
        roulette_history[chat_id].pop(0)


    if result == 0:
        color = "green"

    elif result in red_numbers:
        color = "red"

    else:
        color = "black"
        
    color_text = {
        "red": "🔴 КРАСНОЕ",
        "black": "⚫ ЧЕРНОЕ",
        "green": "🟢 ЗЕЛЕНОЕ"
    }


    text = f"🎡 РУЛЕТКА\nВыпало {result} {color_text[color]}\n\n"


    for bet in roulette_games[chat_id]:

        user = bet["user"]
        name = bet["name"]
        bet_type = bet["type"]
        value = bet["value"]
        amount = bet["bet"]

        bal,_ = get_user(user,name)

        if bal < amount:
            text += f"{name} — ставка отменена (нет денег)\n"
            continue


        update_bal(user,-amount)

        win = 0


        if bet_type == "red" and result in red_numbers:
            win = amount * 2

        elif bet_type == "black" and result in black_numbers:
            win = amount * 2

        elif bet_type == "green" and result == 0:
            win = amount * 14

        elif bet_type == "even" and result != 0 and result % 2 == 0:
            win = amount * 2

        elif bet_type == "odd" and result % 2 == 1:
            win = amount * 2

        elif bet_type == "number":

            if result == value:
                win = amount * 36


        elif bet_type == "range":

            if value == "1-12" and 1 <= result <= 12:
                win = amount * 3

            elif value == "13-24" and 13 <= result <= 24:
                win = amount * 3

            elif value == "25-36" and 25 <= result <= 36:
                win = amount * 3


        if win > 0:

            update_bal(user,win)

            text += f"✅ {name} выиграл {win} MVC\n"

        else:

            text += f"❌ {name} проиграл {amount} MVC\n"


    roulette_games[chat_id] = []

    await msg.reply(text)
    
# --- ПЕРЕДАТЬ ---
@dp.message(lambda msg: msg.text and msg.text.lower().startswith("передать"))
async def transfer(msg: Message):
    if not msg.reply_to_message:
        return
    try:
        amount = int(msg.text.split()[1])
        bal, _ = get_user(msg.from_user.id, msg.from_user.first_name)
        if bal < amount or amount <= 0:
            raise ValueError("bad amount")
        update_bal(msg.from_user.id, -amount)
        update_bal(msg.reply_to_message.from_user.id, amount)
        await msg.reply(f"💸 Ты передал **{amount}** MVC пользователю {msg.reply_to_message.from_user.first_name}")
    except Exception:
        await msg.reply("❌ Ошибка (мало денег или неверная сумма)")


# --- ИГРА МИНЫ (ПОД STAKE СТИЛЬ) ---
def mines_multiplier(opened, bombs):
    base = 1 + bombs * 0.06
    return round(base ** opened, 2)


@dp.message(F.text.lower().startswith("мины"))
async def mines_start(msg: Message):
    parts = msg.text.split()
    if len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await msg.reply("Пиши: `мины [ставка] [кол-во_мин]`")
        return

    bet, bombs = int(parts[1]), int(parts[2])
    bal, _ = get_user(msg.from_user.id, msg.from_user.first_name)
    if bet > bal or bet <= 0:
        await msg.reply("❌ Недостаточно MVC для этой ставки.")
        return
    if not (1 <= bombs <= 24):
        await msg.reply("❌ Мин должно быть от 1 до 24.")
        return

    game_id = str(random.randint(100000,999999))
    mines_sessions[game_id] = {
        "user_id": msg.from_user.id,
        "mines": set(random.sample(range(25), bombs)),
        "bet": bet,
        "bombs": bombs,
        "opened": set(),
    }
    update_bal(msg.from_user.id, -bet)

    await msg.reply(
        f"💣 Поле готово! Ставка: **{bet}** | Мин: **{bombs}**",
        reply_markup=gen_mines_kb(game_id),
    )


def gen_mines_kb(game_id, reveal_all=False):
    state = mines_sessions[game_id]
    buttons = []
    for i in range(25):
        if i in state["opened"]:
            text = "💎"
        elif reveal_all and i in state["mines"]:
            text = "💣"
        else:
            text = "🟦"
        buttons.append(InlineKeyboardButton(text=text, callback_data=f"m:{game_id}:{i}"))

    rows = [buttons[i : i + 5] for i in range(0, 25, 5)]
    if not reveal_all:
        mult = mines_multiplier(len(state["opened"]), state["bombs"])
        cashout = int(state["bet"] * mult)
        rows.append([InlineKeyboardButton(text=f"💰 Забрать {cashout}", callback_data=f"m:{game_id}:stop")])
        rows.append([InlineKeyboardButton(text="↩️ Отмена", callback_data=f"m:{game_id}:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data.startswith("m:"))
async def mines_logic(call: CallbackQuery):

    await call.answer()  # обязательно отвечаем Telegram

    _, g_id, idx = call.data.split(":", 2)

    if g_id not in mines_sessions:
        return

    state = mines_sessions[g_id]

    if state["user_id"] != call.from_user.id:
        await call.answer("Это не твоя игра", show_alert=True)
        return

    if idx == "cancel":
        refund = state["bet"]
        update_bal(call.from_user.id, refund)

        await call.message.edit_text(
            f"↩️ Ставка отменена. Возврат: {refund} MVC"
        )

        del mines_sessions[g_id]
        return

    if idx == "stop":
        mult = mines_multiplier(len(state["opened"]), state["bombs"])
        win = int(state["bet"] * mult)

        update_bal(call.from_user.id, win)

        await call.message.edit_text(
            f"💰 Забрано: {win} MVC (x{mult})"
        )

        del mines_sessions[g_id]
        return

    cell = int(idx)

    if cell in state["opened"]:
        await call.answer("Клетка уже открыта")
        return

    if cell in state["mines"]:

        await call.message.edit_text(
            "💥 БУМ! Ты попал на мину.",
            reply_markup=gen_mines_kb(g_id, True)
        )

        del mines_sessions[g_id]

    else:
        state["opened"].add(cell)

        mult = mines_multiplier(len(state["opened"]), state["bombs"])

        await call.message.edit_text(
            f"✅ Безопасно\nОткрыто клеток: {len(state['opened'])}\nМножитель: x{mult}",
            reply_markup=gen_mines_kb(g_id)
        )


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
