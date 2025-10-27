# bot.py
# Optional polling bot (if you want polling instead of webhook).
import os, json, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
CONFIG = "settings.json"  # uses same settings file structure

def load_settings():
    if os.path.exists(CONFIG):
        return json.load(open(CONFIG))
    return {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = load_settings()
    kb = [[InlineKeyboardButton("📸 Swap Faces", callback_data="swap"), InlineKeyboardButton("💰 Deposit", callback_data="deposit")]]
    await update.message.reply_text(f"👋 Welcome to {s.get('bot_name','FaceSwap')}", reply_markup=InlineKeyboardMarkup(kb))

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send 'Swap' to start the face-swap flow (polling mode limited).")

async def button_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "swap":
        await q.message.reply_text("Use the web panel for full-featured swapping (webhook mode).")

def main():
    # token read from bot_token.txt
    tok = ""
    if os.path.exists("bot_token.txt"):
        tok = open("bot_token.txt").read().strip()
    if not tok:
        print("No token — connect bot through admin panel (web).")
        return
    app = ApplicationBuilder().token(tok).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    print("Bot polling started...")
    app.run_polling()

if __name__ == "__main__":
    main()
