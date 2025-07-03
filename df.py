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

# Временное хранилище корзины
user_carts = {}

# Определение состояний для FSM
class OrderStates(StatesGroup):
    selecting_products = State()
    entering_quantity = State()
    selecting_payment = State()
    entering_address = State()
    confirming_order = State()

# Функция для обработки UTF-8 BOM в ответах
def decode_response(response):
    try:
        response.encoding = 'utf-8-sig'
        return response.json()
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка декодирования JSON: {e}")
        raise

# Команды
@dp.message(Command("start", "help"))
async def cmd_start(message: types.Message):
    await message.answer(
        "<b>🤖 Бот доставки продуктов</b>\n\n"
        "Команды:\n"
        "/orders - Список заказов\n"
        "/neworder - Создать заказ\n"
        "/newclient [имя] [телефон] [адрес] - Создать клиента\n"
        "/couriers - Список курьеров\n"
        "/products - Список товаров\n"
        "/cart - Просмотреть корзину\n"
        "/status [номер_заказа] - Статус доставки"
    )

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
        text = "<b>🛍️ Товары (первые 20):</b>\n\n"
        for product in products:
            text += (
                f"<b>{product.get('Description', '')}</b>\n"
                f"💰 <i>Цена:</i> {product.get('Цена', 'N/A')} руб.\n"
                f"#️⃣ <i>Код:</i> {product.get('Code', '')}\n\n"
            )
        await message.answer(text)
    except Exception as e:
        logger.error(f"Ошибка получения товаров: {e}")
        await message.answer("⚠️ Ошибка при получении списка товаров")

@dp.message(Command("neworder"))
async def cmd_new_order(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_carts[user_id] = []  # Инициализация корзины
    try:
        response = requests.get(
            f"{ODATA_URL}Catalog_Товары?$filter=DeletionMark eq false &$top=10 &$format=json",
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
        user_carts[user_id].append({
            'Ref_Key': product_id,
            'Description': product['Description'],
            'Цена': float(product.get('Цена', 0)),
            'Quantity': quantity
        })
        await message.answer(f"✅ Добавлено: {product['Description']} x{quantity}")
        await cmd_new_order(message, state)  # Возвращаемся к выбору товаров
    except ValueError:
        await message.answer("❌ Введите число")
    except Exception as e:
        logger.error(f"Ошибка добавления товара: {e}")
        await message.answer("⚠️ Ошибка при добавлении товара")

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
    await callback.message.edit_text("📍 Введите адрес доставки:")
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
        order_text += f"{item['Description']} x{item['Quantity']} = {item['Цена'] * item['Quantity']} руб.\n"
    order_text += f"\n💰 <b>Итого:</b> {total} руб.\n"
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
    headers
    try:
        # Найти клиента по Telegram ID
        telegram_id = callback.from_user.id
        response = requests.get(
            f"{ODATA_URL}Catalog_Клиенты?$filter=Комментарии eq '{telegram_id}'&$format=json",
            timeout=10
        )
        response.raise_for_status()
        clients = decode_response(response).get('value', [])
        client_key = clients[0]['Ref_Key'] if clients else None
        if not client_key:
            await callback.message.edit_text("⚠️ Клиент не найден. Создайте профиль с помощью /newclient")
            await state.clear()
            return

        # Создание заказа
        order = {
            "Ref_Key": str(uuid.uuid4()),
            "Date": datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S'),
            "Клиенты_Key": client_key,
            "СуммаЗаказов": str(total),
            "МетодОплаты": "Наличные" if data["payment_method"] == "cash" else "Карта",
            "СтатусЗаказа": "Новый",
            "АдресДоставки": data["address"],
            "Товары": [
                {
                    "Продукты_Key": item["Ref_Key"],
                    "Количество": item["Quantity"],
                    "Цена": str(item["Цена"]),
                    "Сумма": str(item["Цена"] * item["Quantity"]),
                    "LineNumber": idx + 1
                } for idx, item in enumerate(cart)
            ]
        }

        headers = {
            'Content-Type': 'application/json; charset=utf-8',
            'Accept': 'application/json'
        }

        try:
            response = requests.post(
                f"{ODATA_URL}Document_ЗаказКлиента",
                json=order,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            order_data = decode_response(response)
            order_key = order_data.get('Ref_Key')

            # Назначение курьера
            await assign_courier(order_key, user_id, data["address"])

            await callback.message.edit_text(
                f"✅ Заказ №{order_data.get('Number', order_key)} создан!\n"
                f"📍 Доставка по адресу: {data['address']}"
            )
            user_carts.pop(user_id, None)
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP ошибка при создании заказа: {http_err} — {response.text}")
            await callback.message.edit_text("⚠️ Ошибка при создании заказа")
        except Exception as e:
            logger.error(f"Ошибка создания заказа: {e}")
            await callback.message.edit_text("⚠️ Ошибка при создании заказа")
    except Exception as e:
        logger.error(f"Ошибка поиска клиента: {e}")
        await callback.message.edit_text("⚠️ Ошибка при создании заказа")
    finally:
        await state.clear()

async def assign_courier(order_key, user_id, address):
    try:
        # Найти доступного курьера
        response = requests.get(
            f"{ODATA_URL}Catalog_Курьеры?$filter=DeletionMark eq false and Статус eq 'Свободен'&$top=1&$format=json",
            timeout=10
        )
        response.raise_for_status()
        couriers = decode_response(response).get('value', [])
        if not couriers:
            logger.warning("Нет свободных курьеров")
            await bot.send_message(user_id, "⚠️ Нет свободных курьеров, доставка будет назначена позже")
            return
        courier_key = couriers[0]['Ref_Key']
        courier_name = couriers[0].get('Description', 'Неизвестный курьер')

        # Создание назначения курьера
        assignment = {
            'Ref_Key': str(uuid.uuid4()),
            'Date': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S'),
            'Заказ_Key': order_key,
            'Курьер_Key': courier_key,
            'СтатусДоставки': 'Назначен',
            'АдресДоставки': address
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
        response.raise_for_status()

        # Обновить статус курьера
        response = requests.patch(
            f"{ODATA_URL}Catalog_Курьеры(guid'{courier_key}')",
            json={'Статус': 'Занят'},
            headers=headers,
            timeout=10
        )
        response.raise_for_status()

        # Уведомление пользователя
        await bot.send_message(
            user_id,
            f"🚴 Курьер {courier_name} назначен на ваш заказ!\n"
            f"📍 Адрес доставки: {address}"
        )
    except Exception as e:
        logger.error(f"Ошибка назначения курьера: {e}")
        await bot.send_message(user_id, "⚠️ Ошибка при назначении курьера")

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
    cart = user_carts.get(user_id, [])
    if not cart:
        await message.answer("🛒 Корзина пуста")
        return
    text = "<b>🛒 Ваша корзина:</b>\n\n"
    total = 0
    for item in cart:
        subtotal = item['Цена'] * item['Quantity']
        text += f"{item['Description']} x{item['Quantity']} = {subtotal} руб.\n"
        total += subtotal
    text += f"\n💰 <b>Итого:</b> {total} руб."
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
    try:
        response = requests.get(
            f"{ODATA_URL}Document_ЗаказКлиента?$orderby=Date desc&$top=5&$format=json",
            timeout=10
        )
        response.raise_for_status()
        orders = decode_response(response).get('value', [])
        if not orders:
            await message.answer("🛒 Заказов не найдено")
            return
        builder = InlineKeyboardBuilder()
        for order in orders:
            order_date = datetime.strptime(order['Date'], '%Y-%m-%dT%H:%M:%S').strftime('%d.%m.%Y')
            builder.add(types.InlineKeyboardButton(
                text=f"№{order['Number']} от {order_date}",
                callback_data=f"order_{order['Ref_Key']}"
            ))
        builder.adjust(1)
        await message.answer("📋 Последние 5 заказов:", reply_markup=builder.as_markup())
    except Exception as e:
        logger.error(f"Ошибка получения заказов: {e}")
        await message.answer("⚠️ Ошибка при получении заказов")

@dp.callback_query(lambda c: c.data.startswith("order_"))
async def show_order_details(callback: types.CallbackQuery):
    order_id = callback.data.split("_")[1]
    try:
        response = requests.get(
            f"{ODATA_URL}Document_ЗаказКлиента(guid'{order_id}')?$expand=Товары($expand=Продукты)&$format=json",
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
    new_client = {
        "Description": name,
        "Code": phone[-6:],
        "НомерТелефона": phone,
        "АдрессДоставки": address,
        "Комментарии": str(message.from_user.id)
    }
    try:
        response = requests.post(
            f"{ODATA_URL}Catalog_Клиенты",
            json=new_client,
            headers={'Content-Type': 'application/json; charset=utf-8', 'Accept': 'application/json'},
            timeout=10
        )
        response.raise_for_status()
        decode_response(response)
        await message.answer(f"✅ Клиент <b>{name}</b> создан!")
    except Exception as e:
        logger.error(f"Ошибка создания клиента: {e}")
        await message.answer("⚠️ Ошибка при создании клиента")

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

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Формат: /status [номер_заказа]")
        return
    order_number = args[1].strip()
    try:
        response = requests.get(
            f"{ODATA_URL}Document_ЗаказКлиента?$filter=Number eq '{order_number}'&$expand=Курьер&$format=json",
            timeout=10
        )
        response.raise_for_status()
        orders = decode_response(response).get('value', [])
        if not orders:
            await message.answer("📋 Заказ не найден")
            return
        order = orders[0]
        courier = order.get('Курьер', {})
        delivery_response = requests.get(
            f"{ODATA_URL}Document_НазначениеКурьера?$filter=Заказ_Key eq guid'{order['Ref_Key']}'&$format=json",
            timeout=10
        )
        delivery_response.raise_for_status()
        delivery = decode_response(delivery_response).get('value', [{}])[0]
        text = (
            f"<b>📄 Заказ №{order['Number']}</b>\n"
            f"🛒 <i>Статус заказа:</i> {order.get('СтатусЗаказа', 'N/A')}\n"
            f"🚴 <i>Курьер:</i> {courier.get('Description', 'Не назначен')}\n"
            f"📦 <i>Статус доставки:</i> {delivery.get('СтатусДоставки', 'Не назначен')}\n"
            f"📍 <i>Адрес:</i> {order.get('АдресДоставки', 'N/A')}"
        )
        await message.answer(text)
    except Exception as e:
        logger.error(f"Ошибка проверки статуса: {e}")
        await message.answer("⚠️ Ошибка при проверке статуса")

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())