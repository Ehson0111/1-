import os
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import requests
from datetime import datetime
import asyncio
import uuid
import json
import re
import urllib.parse
import отчет
# Загрузка переменных из .env
load_dotenv()

# Получение переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
ODATA_URL = os.getenv('ODATA_URL', 'http://localhost/proekt/odata/standard.odata/')

# Проверка переменных
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не указан в .env файле!")

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# Временное хранилище корзины и авторизации
user_carts = {}
user_sessions = {}

# Определение состояний для FSM
class OrderStates(StatesGroup):
    selecting_products = State()
    entering_quantity = State()
    selecting_payment = State()
    entering_address = State()
    confirming_order = State()

class AuthStates(StatesGroup):
    entering_phone = State()

# Функция для обработки UTF-8 BOM
def decode_response(response):
    try:
        response.encoding = 'utf-8-sig'
        return response.json()
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка декодирования JSON: {e}")
        raise

from aiogram.types import BotCommand

async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Запуск бота"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="login", description="Авторизация"),
        BotCommand(command="newclient", description="Регистрация"),
        BotCommand(command="products", description="Список товаров"),
        BotCommand(command="neworder", description="Создать заказ"),
        BotCommand(command="cart", description="Корзина"),
        BotCommand(command="orders", description="Мои заказы"),
        BotCommand(command="status", description="Статус заказа"),
        BotCommand(command="couriers", description="Курьеры"),
    ]
    await bot.set_my_commands(commands)
# Проверка авторизации
async def is_user_authenticated(user_id):
    return user_id in user_sessions and user_sessions[user_id].get('client_key')

# Команды
@dp.message(Command("start", "help"))
async def cmd_start(message: types.Message):
    await message.answer(
        "<b>🤖 Бот доставки продуктов</b>\n\n"
        "Добро пожаловать! Я помогу вам заказать продукты с доставкой.\n\n"
        "<b>Команды:</b>\n"
        "/login - Авторизация по номеру телефона\n"
        "/newclient [имя] [телефон] [адрес] - Регистрация\n"
        "/products - Список товаров\n"
        "/neworder - Создать заказ\n"
        "/cart - Просмотреть корзину\n"
        "/orders - Список заказов\n"
        "/status [номер_заказа] - Статус доставки\n"
        "/couriers - Список курьеров\n\n"
        "<b>Как использовать:</b>\n"
        "1. Зарегистрируйтесь или авторизуйтесь\n"
        "2. Просмотрите товары (/products)\n"
        "3. Создайте заказ (/neworder)\n"
        "4. Отслеживайте статус (/status)\n"
        "5. Выход (/logout)"
    )

@dp.message(Command("login"))
async def cmd_login(message: types.Message, state: FSMContext):
    await message.answer("📱 Введите номер телефона:")
    await state.set_state(AuthStates.entering_phone)

@dp.message(AuthStates.entering_phone)
async def process_phone(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    phone = message.text.strip()
    if not re.match(r'^\+?\d{10,12}$', phone):
        await message.answer("❌ Неверный формат номера телефона. Попробуйте снова:")
        return
    
    try:
        phone_encoded = urllib.parse.quote(phone)
        user_id_encoded = urllib.parse.quote(str(user_id))
        url = f"{ODATA_URL}Catalog_Клиенты?$filter=НомерТелефона eq '{phone_encoded}' and telegram_id eq '{user_id_encoded}'&$format=json"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        clients = decode_response(response).get('value', [])
        
        if not clients:
            await message.answer("❌ Клиент с таким номером телефона не найден. Зарегистрируйтесь с помощью /newclient")
            await state.clear()
            return
        
        client = clients[0]
        user_sessions[user_id] = {
            'client_key': client['Ref_Key'],
            'phone': phone,
            'name': client['Description'],
            'address': client.get('АдрессДоставки', '')
        }
        
        await message.answer(f"✅ Успешная авторизация, {client['Description']}!")
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка авторизации: {e}")
        await message.answer("⚠️ Ошибка при авторизации")
        await state.clear()

@dp.message(Command("products"))
async def cmd_products(message: types.Message):
    try:
        response = requests.get(
            f"{ODATA_URL}Catalog_Товары?$filter=DeletionMark eq false&$top=20&$format=json",
            timeout=10
        )
        response.raise_for_status()
        products = decode_response(response).get('value', [])
        if not products:
            await message.answer("🛍️ Товаров не найдено")
            return
        
        for product in products:
            text = (
                f"<b>{product.get('Description', '')}</b>\n"
                f"💰 <i>Цена:</i> {product.get('Цена', 'N/A')} руб.\n"
                f"📝 <i>Описание:</i> {product.get('Описание', 'Нет')}\n"
                f"⚖️ <i>Масса:</i> {product.get('Масса', 'Не указана')}\n"
                f"🏭 <i>Производитель:</i> {product.get('Производитель', 'Не указан')}\n"
                f"📅 <i>Срок годности:</i> {product.get('СрокГодности', 'Не указан')}\n"
                f"#️⃣ <i>Код:</i> {product.get('Code', '')}\n"
            )
            image_url = product.get('Изображение')
            if image_url:
                try:
                    await message.answer_photo(
                        photo=image_url,
                        caption=text
                    )
                except Exception as e:
                    logger.warning(f"Ошибка отправки изображения {image_url}: {e}")
                    await message.answer(text)
            else:
                await message.answer(text)
                
    except Exception as e:
        logger.error(f"Ошибка получения товаров: {e}")
        await message.answer("⚠️ Ошибка получения списка товаров")

@dp.message(Command("neworder"))
async def cmd_new_order(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if not await is_user_authenticated(user_id):
        await message.answer(
            "🔐 Пожалуйста, авторизуйтесь с помощью команды /login\n"
            "Или зарегистрируйтесь с помощью /newclient"
        )
        return
    
    user_carts[user_id] = []  # Инициализация корзины
    try:
        response = requests.get(
            f"{ODATA_URL}Catalog_Товары?$filter=DeletionMark eq false&$format=json",
            timeout=10
        )
        response.raise_for_status()
        products = decode_response(response).get('value', [])
        if not products:
            await message.answer("🛍️ Товары отсутствуют")
            return
        builder = InlineKeyboardBuilder()
        for product in products:
            builder.add(
                types.InlineKeyboardButton(
                    text=f"{product.get('Description', '')} ({product.get('Цена', 'N/A')} руб.)",
                    callback_data=f"product_{product['Ref_Key']}"
                )
            )
        builder.add(
            types.InlineKeyboardButton(
                text="🛒 Завершить выбор",
                callback_data="finish_selection"
            )
        )
        builder.adjust(1)
        await message.answer("📦 Выберите товары:", reply_markup=builder.as_markup())
        await state.set_state(OrderStates.selecting_products)
    except Exception as e:
        logger.error(f"Ошибка начала заказа: {e}")
        await message.answer("⚠️ Ошибка при создании заказа")

@dp.callback_query(lambda c: c.data.startswith("product_"), OrderStates.selecting_products)
async def select_product(callback: types.CallbackQuery, state: FSMContext):
    product_id = callback.data.split("_")[1]
    await state.update_data(current_product=product_id)
    await callback.message.answer("📏 Введите количество (например, 2):")
    await state.set_state(OrderStates.entering_quantity)
    await callback.answer()

@dp.message(OrderStates.entering_quantity)
async def enter_quantity(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        quantity = int(message.text)
        if quantity <= 0:
            await message.answer("❌ Количество должно быть больше 0")
            return
            
        data = await state.get_data()
        product_id = data['current_product']
        response = requests.get(
            f"{ODATA_URL}Catalog_Товары(guid'{product_id}')?$format=json",
            timeout=10
        )
        response.raise_for_status()
        product = decode_response(response)
        
        if user_id not in user_carts:
            user_carts[user_id] = []
            
        user_carts[user_id].append({
            'Ref_Key': product_id,
            'Description': product['Description'],
            'Цена': float(product.get('Цена', 0)),
            'Quantity': quantity,
            'Изображение': product.get('Изображение', '')
        })
        
        await message.answer(f"✅ Добавлено: {product['Description']} x{quantity}")
        
        cart_message = "<b>🛒 Текущая корзина:</b>\n\n"
        total = 0
        for item in user_carts[user_id]:
            item_total = item['Цена'] * item['Quantity']
            cart_message += f"▪ {item['Description']} x{item['Quantity']} = {item_total:.2f} руб.\n"
            total += item_total
            
        cart_message += f"\n<b>💰 Итого: {total:.2f} руб.</b>"
        await message.answer(cart_message)
        
        await show_product_selection(message, state)
        
    except ValueError:
        await message.answer("❌ Введите число")
    except Exception as e:
        logger.error(f"Ошибка добавления товара: {e}")
        await message.answer("⚠️ Ошибка при добавлении товара")

async def show_product_selection(message: types.Message, state: FSMContext):
    try:
        response = requests.get(
            f"{ODATA_URL}Catalog_Товары?$filter=DeletionMark eq false&$format=json",
            timeout=10
        )
        response.raise_for_status()
        products = decode_response(response).get('value', [])
        
        if not products:
            await message.answer("🛍️ Товары отсутствуют")
            return
            
        builder = InlineKeyboardBuilder()
        for product in products:
            builder.add(
                types.InlineKeyboardButton(
                    text=f"{product.get('Description', '')} ({product.get('Цена', 'N/A')} руб.)",
                    callback_data=f"product_{product['Ref_Key']}"
                )
            )
        builder.add(
            types.InlineKeyboardButton(
                text="🛒 Завершить выбор",
                callback_data="finish_selection"
            )
        )
        builder.adjust(1)
        await message.answer("📦 Выберите товары:", reply_markup=builder.as_markup())
        await state.set_state(OrderStates.selecting_products)
    except Exception as e:
        logger.error(f"Ошибка показа товаров: {e}")
        await message.answer("⚠️ Ошибка при отображении товаров")

@dp.callback_query(lambda c: c.data == "finish_selection", OrderStates.selecting_products)
async def finish_selection(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if not user_carts.get(user_id):
        await callback.message.edit_text("🛒 Корзина пуста")
        await state.clear()
        return
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(text="💳 Наличные", callback_data="payment_cash"),
        types.InlineKeyboardButton(text="💸 Карта", callback_data="payment_card")
    )
    await callback.message.edit_text("💰 Выберите метод оплаты:", reply_markup=builder.as_markup())
    await state.set_state(OrderStates.selecting_payment)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("payment_"), OrderStates.selecting_payment)
async def select_payment(callback: types.CallbackQuery, state: FSMContext):
    payment_method = callback.data.split("_")[1]
    await state.update_data(payment_method=payment_method)
    user_id = callback.from_user.id
    default_address = user_sessions[user_id].get('address', '')
    await callback.message.edit_text(
        f"📍 Введите адрес доставки\n(Текущий адрес: {default_address}):"
    )
    await state.set_state(OrderStates.entering_address)
    await callback.answer()

@dp.message(OrderStates.entering_address)
async def enter_address(message: types.Message, state: FSMContext):
    address = message.text.strip()
    if not address:
        await message.answer("❌ Адрес не может быть пустым")
        return
    user_id = message.from_user.id
    await state.update_data(address=address)
    data = await state.get_data()
    cart = user_carts.get(user_id, [])
    total = sum(item['Цена'] * item['Quantity'] for item in cart)
    order_text = "<b>🛒 Подтверждение заказа:</b>\n\n"
    
    for item in cart:
        order_text += f"{item['Description']} x{item['Quantity']} = {item['Цена'] * item['Quantity']:.2f} руб.\n"
        if item.get('Изображение'):
            try:
                await message.answer_photo(
                    photo=item['Изображение'],
                    caption=f"{item['Description']}"
                )
            except Exception as e:
                logger.warning(f"Ошибка отправки изображения: {e}")
                pass
                
    order_text += f"\n💰 <b>Итого:</b> {total:.2f} руб.\n"
    order_text += f"💳 <b>Оплата:</b> {'Наличные' if data['payment_method'] == 'cash' else 'Карта'}\n"
    order_text += f"📍 <b>Адрес:</b> {address}"
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_order"),
        types.InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_order")
    )
    await message.answer(order_text, reply_markup=builder.as_markup())
    await state.set_state(OrderStates.confirming_order)

@dp.callback_query(lambda c: c.data == "confirm_order", OrderStates.confirming_order)
async def confirm_order(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    cart = user_carts.get(user_id, [])
    total = sum(item['Цена'] * item['Quantity'] for item in cart)
    
    try:
        client_key = user_sessions[user_id]['client_key']
        
        # Формируем данные заказа с табличной частью
        order_data = {
            "Date": datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S'),
            "Клиенты_Key": client_key,
            "СуммаЗаказов": str(total),
            "МетодОплаты": "Наличные" if data["payment_method"] == "cash" else "Карта",
            "СтатусЗаказа": "Новый",
            "АдресДоставки": data["address"],
            "товар": [
                {
                    "Ref_Key": str(uuid.uuid4()),
                    "LineNumber": idx + 1,
                    "Продукты_Key": item["Ref_Key"],
                    "Количество": item["Quantity"]
                } for idx, item in enumerate(cart)
            ]
        }

        headers = {
            'Content-Type': 'application/json; charset=utf-8',
            'Accept': 'application/json',
            'Prefer': 'return=representation'
        }

        # Создаем заказ
        response = requests.post(
            f"{ODATA_URL}Document_ЗаказКлиента",
            json=order_data,
            headers=headers,
            timeout=15
        )
        
        if response.status_code != 201:
            raise Exception(f"Ошибка создания заказа: {response.text}")

        order_info = decode_response(response)
        order_key = order_info['Ref_Key']
        order_number = order_info.get('Number', 'N/A')
        
        # Назначаем курьера и обновляем заказ
        courier_assigned = await assign_courier(order_key, user_id, data["address"])
        
        if courier_assigned:
            # Обновляем заказ, добавляя ссылку на курьера
            update_data = {
                "Курьер_Key": courier_assigned['courier_key'],
                "СтатусЗаказа": "В обработке"
            }
            
            update_response = requests.patch(
                f"{ODATA_URL}Document_ЗаказКлиента(guid'{order_key}')",
                json=update_data,
                headers=headers,
                timeout=10
            )
            
            if update_response.status_code != 200:
                logger.error(f"Ошибка обновления заказа: {update_response.text}")

        await callback.message.edit_text(
            f"✅ Заказ №{order_number} создан!\n"
            f"📍 Адрес доставки: {data['address']}\n"
            f"💰 Сумма: {total:.2f} руб.\n"
            f"🚴 Курьер: {courier_assigned.get('courier_name', 'будет назначен')}"
        )
        user_carts.pop(user_id, None)
        
    except Exception as e:
        logger.error(f"Ошибка создания заказа: {str(e)}")
        await callback.message.edit_text(f"⚠️ Ошибка при создании заказа: {str(e)}")
    finally:
        await state.clear()

async def assign_courier(order_key, user_id, address):
    try:
        # Получаем свободного курьера
        response = requests.get(
            f"{ODATA_URL}Catalog_Курьеры?$filter=DeletionMark eq false and Статус eq 'Свободен'&$top=1&$format=json",
            timeout=10
        )
        response.raise_for_status()
        couriers = decode_response(response).get('value', [])
        
        if not couriers:
            logger.warning("Нет свободных курьеров")
            await bot.send_message(user_id, "⚠️ Нет свободных курьеров, доставка будет назначена позже")
            return None
            
        courier = couriers[0]
        courier_key = courier['Ref_Key']
        courier_name = courier.get('Description', 'Неизвестный курьер')

        # Создаем документ назначения курьера
        assignment = {
            "Ref_Key": str(uuid.uuid4()),
            "Date": datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S'),
            "DeletionMark": False,
            "Posted": True,
            "Заказ_Key": order_key,
            "Курьер_Key": courier_key,
            "СтатусДоставки": "Назначен",
            "АдресДоставки": address
        }

        headers = {
            'Content-Type': 'application/json; charset=utf-8',
            'Accept': 'application/json'
        }

        response = requests.post(
            f"{ODATA_URL}Document_НазначениеКурьера",
            json=assignment,
            headers=headers,
            timeout=10
        )
        
        if response.status_code != 201:
            raise Exception(f"Ошибка создания назначения курьера: {response.text}")

        # Обновляем статус курьера
        response = requests.patch(
            f"{ODATA_URL}Catalog_Курьеры(guid'{courier_key}')",
            json={"Статус": "Занят"},
            headers=headers,
            timeout=10
        )
        
        if response.status_code != 200:
            raise Exception(f"Ошибка обновления статуса курьера: {response.text}")

        await bot.send_message(
            user_id,
            f"🚴 Курьер {courier_name} назначен на ваш заказ!"
        )
        
        return {
            'courier_key': courier_key,
            'courier_name': courier_name
        }
        
    except Exception as e:
        logger.error(f"Ошибка назначения курьера: {e}")
        await bot.send_message(user_id, "⚠️ Ошибка при назначении курьера")
        return None

@dp.callback_query(lambda c: c.data == "cancel_order", OrderStates.confirming_order)
async def cancel_order(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_carts.pop(user_id, None)
    await callback.message.edit_text("❌ Заказ отменен")
    await state.clear()
    await callback.answer()

@dp.message(Command("cart"))
async def cmd_cart(message: types.Message):
    user_id = message.from_user.id
    if not await is_user_authenticated(user_id):
        await message.answer(
            "🔐 Пожалуйста, авторизуйтесь с помощью команды /login\n"
            "Или зарегистрируйтесь с помощью /newclient"
        )
        return
    
    cart = user_carts.get(user_id, [])
    if not cart:
        await message.answer("🛒 Корзина пуста")
        return
    text = "<b>🛒 Ваша корзина:</b>\n\n"
    total = 0
    for item in cart:
        subtotal = item['Цена'] * item['Quantity']
        text += f"{item['Description']} x{item['Quantity']} = {subtotal:.2f} руб.\n"
        if item.get('Изображение'):
            try:
                await message.answer_photo(
                    photo=item['Изображение'],
                    caption=f"{item['Description']}"
                )
            except Exception as e:
                logger.warning(f"Ошибка отправки изображения: {e}")
                pass
        total += subtotal
    text += f"\n💰 <b>Итого:</b> {total:.2f} руб."
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="🗑 Очистить", callback_data="clear_cart"))
    await message.answer(text, reply_markup=builder.as_markup())

@dp.callback_query(lambda c: c.data == "clear_cart")
async def clear_cart(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_carts.pop(user_id, None)
    await callback.message.edit_text("🛒 Корзина очищена")
    await callback.answer()

# @dp.message(Command("orders"))
# async def cmd_orders(message: types.Message):
#     user_id = message.from_user.id
#     if not await is_user_authenticated(user_id):
#         await message.answer(
#             "🔐 Пожалуйста, авторизуйтесь с помощью команды /login\n"
#             "Или зарегистрируйтесь с помощью /newclient"
#         )
#         return
    
#     client_key = user_sessions[user_id]['client_key']
#     try:
#         client_key_encoded = urllib.parse.quote(client_key)
        
#         response = requests.get(
#             f"{ODATA_URL}Document_ЗаказКлиента?$filter=Клиенты_Key eq guid'{client_key_encoded}'&$orderby=Date desc&$top=10&$format=json",
#             timeout=10
#         )

#         response.raise_for_status()
#         orders = decode_response(response).get('value', [])
#         if not orders:
#             await message.answer("🛒 Заказов не найдено")
#             return
#         builder = InlineKeyboardBuilder()
#         for order in orders:
#             order_date = datetime.strptime(order['Date'], '%Y-%m-%dT%H:%M:%S').strftime('%d.%m.%Y')
#             builder.add(types.InlineKeyboardButton(
#                 text=f"№{order['Number']} от {order_date}",
#                 callback_data=f"order_{order['Ref_Key']}"
#             ))
#         builder.adjust(1)
#         await message.answer("📋 Ваши заказы:", reply_markup=builder.as_markup())
#     except Exception as e:
#         logger.error(f"Ошибка получения заказов: {e}")
#         await message.answer("⚠️ Ошибка при получении заказов")
@dp.message(Command("orders"))
async def cmd_orders(message: types.Message):
    user_id = message.from_user.id
    if not await is_user_authenticated(user_id):
        await message.answer(
            "🔐 Пожалуйста, авторизуйтесь с помощью команды /login\n"
            "Или зарегистрируйтесь с помощью /newclient"
        )
        return
    
    try:
        client_key = user_sessions[user_id]['client_key']
        
        # Формируем URL для запроса заказов клиента
        url = f"{ODATA_URL}Document_ЗаказКлиента?$filter=Клиенты_Key eq guid'{client_key}'&$orderby=Date desc&$top=10&$format=json"
        
        logger.info(f"Запрос к OData: {url}")  # Логируем URL для отладки
        
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # Проверяем, есть ли данные в ответе
        if response.status_code == 200 and response.text.strip():
            try:
                orders = response.json().get('value', [])
            except ValueError:
                logger.error("Не удалось декодировать JSON ответ")
                orders = []
        else:
            orders = []
        
        if not orders:
            await message.answer("🛒 У вас пока нет заказов")
            return
            
        builder = InlineKeyboardBuilder()
        for order in orders:
            try:
                order_date = datetime.strptime(order['Date'], '%Y-%m-%dT%H:%M:%S').strftime('%d.%m.%Y')
                btn_text = f"№{order.get('Number', 'N/A')} от {order_date} - {order.get('СтатусЗаказа', '')}"
                builder.add(types.InlineKeyboardButton(
                    text=btn_text,
                    callback_data=f"order_{order['Ref_Key']}"  # Было: f"order_{order['Ref_Key']"
                ))
            except Exception as e:
                logger.error(f"Ошибка обработки заказа {order}: {e}")
                continue
                
        builder.adjust(1)
        await message.answer("📋 Ваши заказы:", reply_markup=builder.as_markup())
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка запроса к OData: {str(e)}")
        await message.answer("⚠️ Ошибка при получении заказов. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {str(e)}")
        await message.answer("⚠️ Произошла ошибка при обработке запроса")

@dp.callback_query(lambda c: c.data.startswith("order_"))
async def show_order_details(callback: types.CallbackQuery):
    order_id = callback.data.split("_")[1]
    try:
        order_id_encoded = urllib.parse.quote(order_id)
        response = requests.get(
            f"{ODATA_URL}Document_ЗаказКлиента(guid'{order_id_encoded}')?$expand=Товары($expand=Продукты)&$format=json",
            timeout=10
        )
        response.raise_for_status()
        order = decode_response(response)
        order_date = datetime.strptime(order['Date'], '%Y-%m-%dT%H:%M:%S').strftime('%d.%m.%Y %H:%M')
        products_text = ""
        for item in order.get('Товары', []):
            product = item.get('Продукты', {})
            products_text += f"- {product.get('Description', 'N/A')} x{item.get('Количество', 0)} = {item.get('Сумма', 0)} руб.\n"
        text = (
            f"<b>📄 Заказ №{order['Number']}</b>\n"
            f"📅 <i>Дата:</i> {order_date}\n"
            f"💰 <i>Сумма:</i> {order.get('СуммаЗаказов', 'N/A')} руб.\n"
            f"🛒 <i>Статус:</i> {order.get('СтатусЗаказа', 'N/A')}\n"
            f"📍 <i>Адрес:</i> {order.get('АдресДоставки', 'N/A')}\n"
            f"📦 <i>Товары:</i>\n{products_text}"
        )
        await callback.message.edit_text(text)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка получения деталей заказа: {e}")
        await callback.answer("⚠️ Ошибка при получении деталей заказа", show_alert=True)

@dp.message(Command("newclient"))
async def cmd_new_client(message: types.Message):
    args = message.text.split(maxsplit=3)
    if len(args) < 4:
        await message.answer("❌ Формат: /newclient [имя] [телефон] [адрес]")
        return
    
    name, phone, address = args[1], args[2], args[3]
    user_id = str(message.from_user.id)
    
    if not re.match(r'^\+?\d{10,12}$', phone):
        await message.answer("❌ Неверный формат номера телефона")
        return
    
    new_client = {
        "Description": name,
        "Code": phone[-6:],
        "НомерТелефона": phone,
        "АдрессДоставки": address,
        "telegram_id": user_id
    }
    
    headers = {
        'Content-Type': 'application/json; charset=utf-8',
        'Accept': 'application/json'
    }
    
    try:
        response = requests.post(
            f"{ODATA_URL}Catalog_Клиенты",
            json=new_client,
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 201:
            client = decode_response(response)
            user_sessions[user_id] = {
                'client_key': client['Ref_Key'],
                'phone': phone,
                'name': name,
                'address': address
            }
            await message.answer(f"✅ Клиент <b>{name}</b> успешно зарегистрирован(а)! Вы автоматически авторизованы.")
        else:
            error_msg = f"⚠️ Ошибка при создании клиента: {response.text}"
            logger.error(error_msg)
            await message.answer(error_msg)
            
    except Exception as e:
        error_msg = f"⚠️ Ошибка при создании клиента: {str(e)}"
        logger.error(error_msg)
        await message.answer(error_msg)

@dp.message(Command("couriers"))
async def cmd_couriers(message: types.Message):
    try:
        response = requests.get(
            f"{ODATA_URL}Catalog_Курьеры?$filter=DeletionMark eq false&$format=json",
            timeout=10
        )
        response.raise_for_status()
        couriers = decode_response(response).get('value', [])
        if not couriers:
            await message.answer("🚴 Курьеров не найдено")
            return
        result = "<b>🚴 Доступные курьеры:</b>\n\n"
        for c in couriers[:10]:
            result += (
                f"<b>{c.get('Description', 'Без имени')}</b>\n"
                f"📞 <i>{c.get('НомерТелефона', 'не указан')}</i>\n"
                f"🛵 <i>{c.get('Статус', 'не указан')}</i>\n\n"
            )
        await message.answer(result)
    except Exception as e:
        logger.error(f"Ошибка получения курьеров: {e}")
        await message.answer("⚠️ Ошибка при получении списка курьеров")

@dp.message(Command("logout"))
async def cmd_logout(message: types.Message):
    user_id = message.from_user.id
    if user_id in user_sessions:
        # Удаляем сессию пользователя
        user_name = user_sessions[user_id].get('name', 'Пользователь')
        del user_sessions[user_id]
        await message.answer(f"👋 {user_name}, вы успешно вышли из аккаунта!")
    else:
        await message.answer("ℹ️ Вы не авторизованы.")

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Формат: /status [номер_заказа]")
        return
        
    order_number = args[1].strip()
    order_number_encoded = urllib.parse.quote(order_number)
    
    try:
        response = requests.get(
            f"{ODATA_URL}Document_ЗаказКлиента?$filter=Number eq '{order_number_encoded}'&$format=json",
            timeout=10
        )
        response.raise_for_status()
        orders = decode_response(response).get('value', [])
        
        if not orders:
            await message.answer("📋 Заказ не найден")
            return
            
        order = orders[0]
        order_key_encoded = urllib.parse.quote(order['Ref_Key'])
        
        delivery_response = requests.get(
            f"{ODATA_URL}Document_НазначениеКурьера?$filter=Заказ_Key eq guid'{order_key_encoded}'&$expand=Курьер&$format=json",
            timeout=10
        )
        delivery_response.raise_for_status()
        deliveries = decode_response(delivery_response).get('value', [])
        
        delivery_status = "Не назначен"
        courier_name = "Не назначен"
        
        if deliveries:
            delivery = deliveries[0]
            delivery_status = delivery.get('СтатусДоставки', 'Не назначен')
            courier = delivery.get('Курьер', {})
            courier_name = courier.get('Description', 'Неизвестный курьер')

        text = (
            f"<b>📄 Заказ №{order['Number']}</b>\n"
            f"📅 Дата: {datetime.strptime(order['Date'], '%Y-%m-%dT%H:%M:%S').strftime('%d.%m.%Y %H:%M')}\n"
            f"🛒 Статус заказа: {order.get('СтатусЗаказа', 'Неизвестно')}\n"
            f"🚴 Курьер: {courier_name}\n"
            f"📦 Статус доставки: {delivery_status}\n"
            f"📍 Адрес: {order.get('АдресДоставки', 'Не указан')}\n"
            f"💰 Сумма: {order.get('СуммаЗаказов', '0')} руб."
        )
        
        await message.answer(text)
        
    except Exception as e:
        logger.error(f"Ошибка проверки статуса: {str(e)}")
        await message.answer("⚠️ Ошибка при проверке статуса заказа")

async def main():
    await dp.start_polling(bot)
    await set_bot_commands(bot)

if __name__ == '__main__':
    asyncio.run(main())