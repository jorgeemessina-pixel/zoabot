import telebot
import os
from flask import Flask

TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Hola Jorge! Soy Zoa, tu bot 24/7 🤖")

@bot.message_handler(func=lambda m: True)
def echo_all(message):
    bot.reply_to(message, f"Vos dijiste: {message.text}")

@app.route('/')
def home():
    return "Zoa está online!"

if __name__ == '__main__':
    bot.polling()
