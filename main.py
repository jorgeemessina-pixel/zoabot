from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hola! Zoabot esta vivo!")

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
    app.run_polling()

if __name__ == "__main__":
    main()
