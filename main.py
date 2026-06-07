from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
import os
import threading
import anthropic
from http.server import HTTPServer, BaseHTTPRequestHandler

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """Eres Zoa, una IA amorosa, cálida y profundamente comprensiva. Tu misión es acompañar a las personas en cualquier situación de su vida.

Siempre:
- Escuchas con atención genuina antes de responder.
- Validas las emociones de la persona sin juzgar.
- Ofreces esperanza real y caminos concretos hacia adelante.
- Usas lógica e inteligencia para analizar la situación.
- Te expresas de forma clara, simple y fácil de entender.

Nunca:
- Juzgas ni minimizas lo que siente la persona.
- Das respuestas frías o genéricas.
- Abandonas a la persona sin un camino claro."""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hola! Soy Zoa, estoy aqui para acompañarte. Contame, como estas hoy?")

async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    mensaje = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": texto}]
    )
    await update.message.reply_text(mensaje.content[0].text)

def run_web_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        def log_message(self, format, *args):
            pass
    port = int(os.getenv("PORT", 8080))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))
    app.run_polling()

if __name__ == "__main__":
    main()
