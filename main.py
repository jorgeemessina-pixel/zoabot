from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hola Jorge! Zoabot está vivo 🐯")

app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
app.add_handler(CommandHandler("start", start))

if __name__ == "__main__":
    app.run_polling()
