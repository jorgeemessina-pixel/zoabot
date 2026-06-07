from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os
import asyncio

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hola! Zoabot está vivo 🐯")

async def main():
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
Fijate que las líneas con await adentro de las funciones tienen 4 espacios al principio. ¿Podés borrar todo y pegarlo de nuevo?Sonnet 4.6 Bajo
