import json
import random
import asyncio
from pathlib import Path
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

BOT_TOKEN = "8595359472:AAHPkezZDyCRDHaOs-sHGhh8YzpSuuYsMEE"
ADMIN_IDS = {123456789}

DATA_FILE = Path("casino_data.json")
ROUND_TIME = 30

COLORS = {
    "red": 2,
    "green": 2,
    "blue": 5
}

# ---------------- DATA ---------------- #

if DATA_FILE.exists():
    data = json.loads(DATA_FILE.read_text())
else:
    data = {"users": {}, "referrals": {}}


def save():
    DATA_FILE.write_text(json.dumps(data, indent=2))


def get_user(uid):
    uid = str(uid)
    if uid not in data["users"]:
        data["users"][uid] = {
            "balance": 1000,
            "history": [],
            "vip": False
        }
        save()
    return data["users"][uid]


# ---------------- GAME STATE ---------------- #

current_round = {
    "open": True,
    "bets": [],
    "forced_result": None
}

round_messages = {}


def keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Red (2x)", callback_data="bet_red"),
         InlineKeyboardButton("🟢 Green (2x)", callback_data="bet_green")],
        [InlineKeyboardButton("🔵 Blue (5x)", callback_data="bet_blue")]
    ])


# ---------------- COMMANDS ---------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)

    if context.args:
        ref = context.args[0]
        if ref != str(uid) and ref not in data["referrals"]:
            data["referrals"][ref] = True
            get_user(ref)["balance"] += 200
            save()

    await update.message.reply_text(
        f"🎰 *Color Prediction Casino*\n\n"
        f"💰 Balance: {user['balance']}\n"
        f"⏱ New round every 30 seconds\n\n"
        f"Tap a color to bet 100 coins",
        reply_markup=keyboard(),
        parse_mode="Markdown"
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    await update.message.reply_text(f"💳 Balance: {user['balance']}")


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user["history"]:
        await update.message.reply_text("📜 No history yet")
        return
    await update.message.reply_text(
        "📜 Last bets:\n" + "\n".join(user["history"][-5:])
    )


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = sorted(
        data["users"].items(),
        key=lambda x: x[1]["balance"],
        reverse=True
    )[:5]

    text = "🏆 *Leaderboard*\n\n"
    for i, (uid, u) in enumerate(users, 1):
        text += f"{i}. {u['balance']} coins\n"

    await update.message.reply_text(text, parse_mode="Markdown")


# ---------------- BET HANDLER ---------------- #

async def bet_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not current_round["open"]:
        await q.message.reply_text("❌ Betting closed")
        return

    color = q.data.replace("bet_", "")
    user = get_user(q.from_user.id)

    bet_amount = 100 if not user["vip"] else 150

    if user["balance"] < bet_amount:
        await q.message.reply_text("❌ Not enough balance")
        return

    user["balance"] -= bet_amount
    current_round["bets"].append({
        "uid": q.from_user.id,
        "color": color,
        "amount": bet_amount
    })
    save()

    await q.message.reply_text(
        f"✅ Bet placed\n🎨 {color.upper()} | 💰 {bet_amount}"
    )
    
# ---------------- ROUND ENGINE ---------------- #

async def send_countdown(app, seconds):
    for remaining in range(seconds, 0, -5):
        text = (
            "🎰 *Color Prediction Casino*\n\n"
            f"⏳ Time left: *{remaining}s*\n\n"
            "Tap a color to bet 👇"
        )

        for uid, msg_id in round_messages.items():
            try:
                await app.bot.edit_message_text(
                    chat_id=int(uid),
                    message_id=msg_id,
                    text=text,
                    reply_markup=keyboard(),
                    parse_mode="Markdown"
                )
            except:
                pass

        await asyncio.sleep(5)

async def round_engine(app):
    while True:
        current_round["open"] = True
        current_round["bets"] = []
        round_messages.clear()

        if not data["users"]:
            await asyncio.sleep(5)
            continue

        # Send round message to every user
        for uid in data["users"]:
            try:
                msg = await app.bot.send_message(
                    chat_id=int(uid),
                    text="🎰 *New Round Started*\n\n⏳ Time left: 30s",
                    reply_markup=keyboard(),
                    parse_mode="Markdown"
                )
                round_messages[uid] = msg.message_id
            except:
                pass

        # Countdown
        await send_countdown(app, ROUND_TIME)

        # Close betting
        current_round["open"] = False

        # Disable buttons
        for uid, msg_id in round_messages.items():
            try:
                await app.bot.edit_message_reply_markup(
                    chat_id=int(uid),
                    message_id=msg_id,
                    reply_markup=None
                )
            except:
                pass

        # Result
        result = current_round["forced_result"] or random.choice(list(COLORS))
        current_round["forced_result"] = None

        for bet in current_round["bets"]:
            user = get_user(bet["uid"])

            if bet["color"] == result:
                win = bet["amount"] * COLORS[result]
                user["balance"] += win
                user["history"].append(f"✅ {result.upper()} +{win}")
                msg = f"🎉 WIN!\n🎨 {result.upper()}\n💰 +{win}"
            else:
                user["history"].append(
                    f"❌ {bet['color'].upper()} -{bet['amount']}"
                )
                msg = f"😢 LOST!\n🎨 {result.upper()}"

            save()
            await app.bot.send_message(bet["uid"], msg)

        await asyncio.sleep(5)


# ---------------- ADMIN ---------------- #

async def set_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    if not context.args or context.args[0] not in COLORS:
        await update.message.reply_text("Usage: /force red|green|blue")
        return

    current_round["forced_result"] = context.args[0]
    await update.message.reply_text("✅ Forced result set")


async def set_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    uid = context.args[0]
    get_user(uid)["vip"] = True
    save()
    await update.message.reply_text("💎 VIP activated")


# ---------------- START ---------------- #

async def on_startup(app):
    asyncio.create_task(round_engine(app))


app = ApplicationBuilder().token(BOT_TOKEN).post_init(on_startup).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("balance", balance))
app.add_handler(CommandHandler("history", history))
app.add_handler(CommandHandler("leaderboard", leaderboard))
app.add_handler(CommandHandler("force", set_result))
app.add_handler(CommandHandler("vip", set_vip))
app.add_handler(CallbackQueryHandler(bet_handler))

print("🎰 Ultimate Casino Bot Running...")
app.run_polling()
