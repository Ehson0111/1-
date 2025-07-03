import os
import logging
import json
import re
import uuid
import asyncio
import urllib.parse
import io
import requests
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BotCommand

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
ODATA_URL = os.getenv('ODATA_URL', 'http://localhost/proekt/odata/standard.odata/')
ADMIN_PHONE = os.getenv('ADMIN_PHONE', '+79139849805')

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не указан в .env файле!")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

user_carts = {}
user_sessions = {}

class OrderStates(StatesGroup):
    selecting_products = State()
    entering_quantity = State()
    selecting_payment = State()
    entering_address = State()
    confirming_order = State()

class AuthStates(StatesGroup):
    entering_phone = State()

def decode_response(response):
    response.encoding = 'utf-8-sig'
    return response.json()

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
        BotCommand(command="reports", description="Отчеты (для администраторов)")
    ]
    await bot.set_my_commands(commands)

async def is_user_authenticated(user_id):
    return user_id in user_sessions and user_sessions[user_id].get('client_key')

@dp.message(Command("start", "help"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    is_admin = user_sessions.get(user_id, {}).get('is_admin', False)
    admin_commands = "\n/reports - Просмотр отчетов (только для администраторов)" if is_admin else ""
    await message.answer(
        "<b>🤖 Бот доставки продуктов</b>\n\n"
        "Добро пожаловать! Я помогу вам заказать продукты с доставкой.\n\n"
        "<b>Команды:</b>\n"
        "/login - Авторизация по номеру телефона\n"
        "/newclient [имя телефон адрес] - Регистрация\n"
        "/products - Список товаров\n"
        "/neworder - Создать заказ\n"
        "/cart - Посмотреть корзину\n"
        "/orders - Список заказов\n"
        "/status [номер_заказа] - Статус доставки\n"
        "/couriers - Список курьеров\n"
        "/logout - Выход\n"
        f"{admin_commands}\n\n"
        "<b>Как использовать:</b>\n"
        "1. Зарегистрируйтесь или авторизуйтесь\n"
        "2. Просмотрите товары (/products)\n"
        "3. Создайте заказ (/neworder)\n"
        "4. Отслеживайте статус (/status)"
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
            'address': client.get('АдрессДоставки', ''),
            'is_admin': phone == ADMIN_PHONE
        }
        await message.answer(
            f"✅ Успешная авторизация, {client['Description']}!"
            + (" Вы вошли как администратор. для отчета введите команду /reports" if user_sessions[user_id]['is_admin'] else "")
        )
        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка авторизации: {e}")
        await message.answer("⚠️ Ошибка при авторизации")
        await state.clear()

@dp.message(Command("products"))
async def cmd_products(message: types.Message):
    try:
        response = requests.get(f"{ODATA_URL}Catalog_Товары?$filter=DeletionMark eq false&$top=20&$format=json", timeout=10)
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
                    await message.answer_photo(photo=image_url, caption=text)
                except Exception:
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
        await message.answer("🔐 Пожалуйста, авторизуйтесь с помощью /login\nИли зарегистрируйтесь с помощью /newclient")
        return
    user_carts[user_id] = []
    try:
        response = requests.get(f"{ODATA_URL}Catalog_Товары?$filter=DeletionMark eq false&$format=json", timeout=10)
        response.raise_for_status()
        products = decode_response(response).get('value', [])
        if not products:
            await message.answer("🛍️ Товары отсутствуют")
            return
        builder = InlineKeyboardBuilder()
        for product in products:
            builder.add(types.InlineKeyboardButton(
                text=f"{product.get('Description', '')} ({product.get('Цена', 'N/A')} руб.)",
                callback_data=f"product_{product['Ref_Key']}"
            ))
        builder.add(types.InlineKeyboardButton(text="🛒 Завершить выбор", callback_data="finish_selection"))
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
        response = requests.get(f"{ODATA_URL}Catalog_Товары(guid'{product_id}')?$format=json", timeout=10)
        response.raise_for_status()
        product = decode_response(response)
        if user_id not in user_carts:
            user_carts[user_id] = []
        user_carts[user_id].append({
            'Ref_Key': product_id,
            'Description': product['Description'],
            'Цена': float(product.get('Цена', 0) or 0),
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
        response = requests.get(f"{ODATA_URL}Catalog_Товары?$filter=DeletionMark eq false&$format=json", timeout=10)
        response.raise_for_status()
        products = decode_response(response).get('value', [])
        if not products:
            await message.answer("🛍️ Товары отсутствуют")
            return
        builder = InlineKeyboardBuilder()
        for product in products:
            builder.add(types.InlineKeyboardButton(
                text=f"{product.get('Description', '')} ({product.get('Цена', 'N/A')} руб.)",
                callback_data=f"product_{product['Ref_Key']}"
            ))
        builder.add(types.InlineKeyboardButton(text="🛒 Завершить выбор", callback_data="finish_selection"))
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
    await callback.message.edit_text(f"📍 Введите адрес доставки\n(Текущий адрес: {default_address}):")
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
                await message.answer_photo(photo=item['Изображение'], caption=f"{item['Description']}")
            except Exception:
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
        headers = {'Content-Type': 'application/json; charset=utf-8', 'Accept': 'application/json', 'Prefer': 'return=representation'}
        response = requests.post(f"{ODATA_URL}Document_ЗаказКлиента", json=order_data, headers=headers, timeout=15)
        if response.status_code != 201:
            raise Exception(f"Ошибка создания заказа: {response.text}")
        order_info = decode_response(response)
        order_key = order_info['Ref_Key']
        order_number = order_info.get('Number', 'N/A')
        courier_assigned = await assign_courier(order_key, user_id, data["address"])
        if courier_assigned:
            update_data = {"Курьер_Key": courier_assigned['courier_key'], "СтатусЗаказа": "В обработке"}
            update_response = requests.patch(f"{ODATA_URL}Document_ЗаказКлиента(guid'{order_key}')", json=update_data, headers=headers, timeout=10)
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
        logger.error(f"Ошибка создания заказа: {e}")
        await callback.message.edit_text(f"⚠️ Ошибка при создании заказа: {str(e)}")
    finally:
        await state.clear()

async def assign_courier(order_key, user_id, address):
    try:
        response = requests.get(f"{ODATA_URL}Catalog_Курьеры?$filter=DeletionMark eq false and Статус eq 'Свободен'&$top=1&$format=json", timeout=10)
        response.raise_for_status()
        couriers = decode_response(response).get('value', [])
        if not couriers:
            await bot.send_message(user_id, "⚠️ Нет свободных курьеров, доставка будет назначена позже")
            return None
        courier = couriers[0]
        courier_key = courier['Ref_Key']
        courier_name = courier.get('Description', 'Неизвестный курьер')
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
        headers = {'Content-Type': 'application/json; charset=utf-8', 'Accept': 'application/json'}
        response = requests.post(f"{ODATA_URL}Document_НазначениеКурьера", json=assignment, headers=headers, timeout=10)
        if response.status_code != 201:
            raise Exception(f"Ошибка создания назначения курьера: {response.text}")
        response = requests.patch(f"{ODATA_URL}Catalog_Курьеры(guid'{courier_key}')", json={"Статус": "Занят"}, headers=headers, timeout=10)
        if response.status_code != 200:
            raise Exception(f"Ошибка обновления статуса курьера: {response.text}")
        await bot.send_message(user_id, f"🚴 Курьер {courier_name} назначен на ваш заказ!")
        return {'courier_key': courier_key, 'courier_name': courier_name}
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
        await message.answer("🔐 Пожалуйста, авторизуйтесь с помощью /login\nИли зарегистрируйтесь с помощью /newclient")
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
                await message.answer_photo(photo=item['Изображение'], caption=f"{item['Description']}")
            except Exception:
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

@dp.message(Command("orders"))
async def cmd_orders(message: types.Message):
    user_id = message.from_user.id
    if not await is_user_authenticated(user_id):
        await message.answer("🔐 Пожалуйста, авторизуйтесь с помощью /login\nИли зарегистрируйтесь с помощью /newclient")
        return
    try:
        client_key = user_sessions[user_id]['client_key']
        url = f"{ODATA_URL}Document_ЗаказКлиента?$filter=Клиенты_Key eq guid'{client_key}'&$orderby=Date desc&$top=10&$format=json"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        orders = decode_response(response).get('value', [])
        if not orders:
            await message.answer("🛒 У вас пока нет заказов")
            return
        builder = InlineKeyboardBuilder()
        for order in orders:
            order_date = datetime.strptime(order['Date'], '%Y-%m-%dT%H:%M:%S').strftime('%d.%m.%Y')
            btn_text = f"№{order.get('Number', 'N/A')} от {order_date} - {order.get('СтатусЗаказа', '')}"
            builder.add(types.InlineKeyboardButton(text=btn_text, callback_data=f"order_{order['Ref_Key']}"))
        builder.adjust(1)
        await message.answer("📋 Ваши заказы:", reply_markup=builder.as_markup())
    except Exception as e:
        logger.error(f"Ошибка получения заказов: {e}")
        await message.answer("⚠️ Ошибка при получении заказов")

@dp.callback_query(lambda c: c.data.startswith("order_"))
async def show_order_details(callback: types.CallbackQuery):
    order_id = callback.data.split("_")[1]
    try:
        order_id_encoded = urllib.parse.quote(order_id)
        response = requests.get(f"{ODATA_URL}Document_ЗаказКлиента(guid'{order_id_encoded}')?$expand=Товары($expand=Продукты)&$format=json", timeout=10)
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
    headers = {'Content-Type': 'application/json; charset=utf-8', 'Accept': 'application/json'}
    try:
        response = requests.post(f"{ODATA_URL}Catalog_Клиенты", json=new_client, headers=headers, timeout=10)
        if response.status_code == 201:
            client = decode_response(response)
            user_sessions[user_id] = {
                'client_key': client['Ref_Key'],
                'phone': phone,
                'name': name,
                'address': address,
                'is_admin': phone == ADMIN_PHONE
            }
            await message.answer(f"✅ Клиент <b>{name}</b> успешно зарегистрирован(а)! Вы автоматически авторизованы.")
        else:
            logger.error(f"Ошибка создания клиента: {response.text}")
            await message.answer("⚠️ Ошибка при создании клиента")
    except Exception as e:
        logger.error(f"Ошибка создания клиента: {e}")
        await message.answer(f"⚠️ Ошибка при создании клиента: {str(e)}")

@dp.message(Command("couriers"))
async def cmd_couriers(message: types.Message):
    try:
        response = requests.get(f"{ODATA_URL}Catalog_Курьеры?$filter=DeletionMark eq false&$format=json", timeout=10)
        response.raise_for_status()
        couriers = decode_response(response).get('value', [])
        if not couriers:
            await message.answer("🚴 Курьеров не найдено")
            return
        result = "<b>🚴 Доступные курьеры:</b>\n\n"
        for c in couriers[:10]:
            result += f"<b>{c.get('Description', 'Без имени')}</b>\n📞 <i>{c.get('НомерТелефона', 'не указан')}</i>\n🛵 <i>{c.get('Статус', 'не указан')}</i>\n\n"
        await message.answer(result)
    except Exception as e:
        logger.error(f"Ошибка получения курьеров: {e}")
        await message.answer("⚠️ Ошибка при получении списка курьеров")

@dp.message(Command("logout"))
async def cmd_logout(message: types.Message):
    user_id = message.from_user.id
    if user_id in user_sessions:
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
        response = requests.get(f"{ODATA_URL}Document_ЗаказКлиента?$filter=Number eq '{order_number_encoded}'&$format=json", timeout=10)
        response.raise_for_status()
        orders = decode_response(response).get('value', [])
        if not orders:
            await message.answer("📋 Заказ не найден")
            return
        order = orders[0]
        order_key_encoded = urllib.parse.quote(order['Ref_Key'])
        delivery_response = requests.get(f"{ODATA_URL}Document_НазначениеКурьера?$filter=Заказ_Key eq guid'{order_key_encoded}'&$expand=Курьер&$format=json", timeout=10)
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
        logger.error(f"Ошибка проверки статуса: {e}")
        await message.answer("⚠️ Ошибка при проверке статуса заказа")

@dp.message(Command("reports"))
async def cmd_reports(message: types.Message):
    user_id = message.from_user.id
    if not await is_user_authenticated(user_id):
        await message.answer("🔐 Пожалуйста, авторизуйтесь с помощью /login")
        return
    if not user_sessions[user_id].get('is_admin', False):
        await message.answer("❌ Доступ запрещен. Эта команда только для администраторов.")
        return
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(text="Заказы по клиентам", callback_data="report_orders_by_customer"),
        # types.InlineKeyboa rdButton(text="Статусы заказов", callback_data="report_order_statuses"),
        types.InlineKeyboardButton(text="Методы оплаты", callback_data="report_payment_methods"),
        types.InlineKeyboardButton(text="Средний чек", callback_data="report_average_order_value"),
        types.InlineKeyboardButton(text="Нагрузка на курьеров", callback_data="report_courier_load"),
        types.InlineKeyboardButton(text="Статусы доставок", callback_data="report_delivery_statuses"),
        types.InlineKeyboardButton(text="Активные клиенты", callback_data="report_active_customers")
    )
    builder.adjust(1)
    await message.answer("📊 Выберите отчет:", reply_markup=builder.as_markup())

@dp.callback_query(lambda c: c.data.startswith("report_"))
async def process_report_selection(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not user_sessions[user_id].get('is_admin', False):
        await callback.message.edit_text("❌ Доступ запрещен. Эта команда только для администраторов.")
        await callback.answer()
        return
    report_type = callback.data
    await callback.message.edit_text("🔄 Генерируем отчет...")
    try:
        buffer = io.BytesIO()
        plt.figure(figsize=(12, 6))
        if report_type == "report_orders_by_customer":
            orders_by_customer()
            plt.savefig(buffer, format='png')
            plt.close()
            buffer.seek(0)
            await callback.message.answer_photo(photo=types.BufferedInputFile(buffer.read(), filename="orders_by_customer.png"))
        elif report_type == "report_order_statuses":
            order_statuses()
            plt.savefig(buffer, format='png')
            plt.close()
            buffer.seek(0)
            await callback.message.answer_photo(photo=types.BufferedInputFile(buffer.read(), filename="order_statuses.png"))
        elif report_type == "report_payment_methods":
            payment_methods()
            plt.savefig(buffer, format='png')
            plt.close()
            buffer.seek(0)
            await callback.message.answer_photo(photo=types.BufferedInputFile(buffer.read(), filename="payment_methods.png"))
        elif report_type == "report_average_order_value":
            avg_value = average_order_value()
            buffer.close()
            plt.close()
            await callback.message.answer(f"📊 Средний чек: {avg_value:.2f} руб")
            return
        elif report_type == "report_courier_load":
            courier_load()
            plt.savefig(buffer, format='png')
            plt.close()
            buffer.seek(0)
            await callback.message.answer_photo(photo=types.BufferedInputFile(buffer.read(), filename="courier_load.png"))
        elif report_type == "report_delivery_statuses":
            delivery_statuses()
            plt.savefig(buffer, format='png')
            plt.close()
            buffer.seek(0)
            await callback.message.answer_photo(photo=types.BufferedInputFile(buffer.read(), filename="delivery_statuses.png"))
        elif report_type == "report_active_customers":
            active_customers()
            plt.savefig(buffer, format='png')
            plt.close()
            buffer.seek(0)
            await callback.message.answer_photo(photo=types.BufferedInputFile(buffer.read(), filename="active_customers.png"))
        buffer.close()
        await callback.message.answer("✅ Отчет успешно сгенерирован!")
    except Exception as e:
        logger.error(f"Ошибка генерации отчета {report_type}: {e}")
        await callback.message.edit_text(f"⚠️ Ошибка при генерации отчета: {str(e)}")
    await callback.answer()

def get_odata_data(endpoint, params=None):
    url = urllib.parse.urljoin(ODATA_URL, endpoint)
    try:
        response = requests.get(url, params=params, headers={'Accept': 'application/json'})
        response.raise_for_status()
        return decode_response(response).get('value', [])
    except Exception as e:
        logger.error(f"Ошибка запроса {url}: {e}")
        return []

def orders_by_customer():
    params = {"$expand": "Клиенты", "$select": "Клиенты/Description,Number,Date,СуммаЗаказов"}
    orders = get_odata_data("Document_ЗаказКлиента", params)
    if not orders:
        return
    df_data = []
    for order in orders:
        client = order.get('Клиенты', {})
        try:
            amount = float(order.get('СуммаЗаказов', 0) or 0)
        except (ValueError, TypeError):
            amount = 0.0
        df_data.append({
            'Клиент': client.get('Description', 'Без имени'),
            'Номер заказа': order.get('Number', ''),
            'Дата': pd.to_datetime(order.get('Date', None), errors='coerce'),
            'Сумма': amount
        })
    df = pd.DataFrame(df_data)
    customer_orders = df.groupby('Клиент').agg({'Номер заказа': 'count', 'Сумма': 'sum'}).rename(columns={'Номер заказа': 'Количество заказов'})
    customer_orders['Количество заказов'].plot(kind='bar', color='lightblue')
    plt.title('Количество заказов по клиентам')
    plt.xlabel('Клиент')
    plt.ylabel('Количество заказов')
    plt.xticks(rotation=45)
    plt.tight_layout()

def order_statuses():
    params = {"$select": "СтатусЗаказа"}
    orders = get_odata_data("Document_ЗаказКлиента", params)
    if not orders:
        return
    df = pd.DataFrame([order.get('СтатусЗаказа', 'Не указан') for order in orders], columns=['Статус'])
    status_counts = df['Статус'].value_counts()
    status_counts.plot(kind='pie', autopct='%1.1f%%', startangle=90)
    plt.title('Распределение статусов заказов')
    plt.ylabel('')
    plt.tight_layout()

def payment_methods():
    params = {"$select": "МетодОплаты"}
    orders = get_odata_data("Document_ЗаказКлиента", params)
    if not orders:
        return
    df = pd.DataFrame([order.get('МетодОплаты', 'Не указан') for order in orders], columns=['Метод'])
    method_counts = df['Метод'].value_counts()
    method_counts.plot(kind='bar', color='coral')
    plt.title('Распределение методов оплаты')
    plt.xlabel('Метод оплаты')
    plt.ylabel('Количество заказов')
    plt.xticks(rotation=45)
    plt.tight_layout()

def average_order_value():
    params = {"$select": "СуммаЗаказов"}
    orders = get_odata_data("Document_ЗаказКлиента", params)
    if not orders:
        return 0.0
    df = pd.DataFrame([float(order.get('СуммаЗаказов', 0) or 0) for order in orders], columns=['Сумма'])
    return df['Сумма'].mean()

def courier_load():
    params = {"$expand": "Курьер", "$select": "Курьер/Description,Date"}
    assignments = get_odata_data("Document_НазначениеКурьера", params)
    if not assignments:
        return
    df = pd.DataFrame([{
        'Курьер': assignment.get('Курьер', {}).get('Description', 'Без имени'),
        'Дата': pd.to_datetime(assignment.get('Date', None))
    } for assignment in assignments])
    courier_counts = df.groupby('Курьер').size()
    courier_counts.plot(kind='bar', color='lightgreen')
    plt.title('Нагрузка на курьеров (количество назначений)')
    plt.xlabel('Курьер')
    plt.ylabel('Количество назначений')
    plt.xticks(rotation=45)
    plt.tight_layout()

def delivery_statuses():
    params = {"$select": "СтатусДоставки"}
    assignments = get_odata_data("Document_НазначениеКурьера", params)
    if not assignments:
        return
    df = pd.DataFrame([assignment.get('СтатусДоставки', 'Не указан') for assignment in assignments], columns=['Статус'])
    status_counts = df['Статус'].value_counts()
    status_counts.plot(kind='pie', autopct='%1.1f%%', startangle=90)
    plt.title('Распределение статусов доставок')
    plt.ylabel('')
    plt.tight_layout()

def active_customers():
    params = {"$expand": "Клиенты", "$select": "Клиенты/Description,Number"}
    orders = get_odata_data("Document_ЗаказКлиента", params)
    if not orders:
        return
    df = pd.DataFrame([{
        'Клиент': order.get('Клиенты', {}).get('Description', 'Без имени'),
        'Заказ': order.get('Number', '')
    } for order in orders])
    active_counts = df.groupby('Клиент').size().nlargest(10)
    active_counts.plot(kind='bar', color='teal')
    plt.title('Топ-10 активных клиентов')
    plt.xlabel('Клиент')
    plt.ylabel('Количество заказов')
    plt.xticks(rotation=45)
    plt.tight_layout()

async def main():
    await dp.start_polling(bot)
    await set_bot_commands(bot)

if __name__ == '__main__':
    asyncio.run(main())