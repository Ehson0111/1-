import requests
from telegram import Update, Bot
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

TOKEN = "8115382167:AAFjynQagXCBNNwGFEHGQwOMPu13ir5CTMY"
URL_1C = "http://ваш-сервер-1С/ваша-база/hs/telegram/process"  # URL REST-сервиса 1С

def handle_message(update: Update, context: CallbackContext):
    # Отправляем запрос в 1С и получаем ответ
    response = requests.post(URL_1C, json={"text": update.message.text, "user_id": update.effective_user.id})
    update.message.reply_text(response.json()["answer"])

bot = Bot(token=TOKEN)
updater = Updater(token=TOKEN, use_context=True)
updater.dispatcher.add_handler(MessageHandler(Filters.text, handle_message))
updater.start_polling()