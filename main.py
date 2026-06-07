from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
import os
import threading
import anthropic
import requests
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = "Eres Zoa, una IA amorosa, calida y comprensiva. Acompanas a las personas en cualquier situacion. Escuchas, validas emociones, ofreces esperanza y soluciones concretas. Jamas juzgas ni abandonas a la persona sin un camino claro."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hola! Soy Zoa. Contame, como estas hoy?")

async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    mensaje = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=1000, system=SYSTEM_PROMPT, messages=[{"role": "user", "content": texto}])
    await update.message.reply_text(mensaje.content[0].text)

def keep_alive():
    while True:
        try:
            requests.get("https://zoabot.onrender.com")
        except:
            pass
        time.sleep(600)

def run_web_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        def log_message(self, format, *args):
            pass
    HTTPServer(("0.0.0.0", int(os.getenv("PORT", 8080))), Handler).serve_forever()

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
    app.run_polling()

if __name__ == "__main__":
    main()
