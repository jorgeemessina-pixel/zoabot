from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os
import asyncio
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hola! Zoabot esta vivo!")
async def main():
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    await app.run_polling()
if __name__ == "__main__":
    asyncio.run(main())
