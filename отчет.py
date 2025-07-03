import requests
import matplotlib.pyplot as plt
import pandas as pd
from urllib.parse import urljoin
from datetime import datetime
# Настройки
BASE_URL = "http://localhost/proekt/odata/standard.odata/"
HEADERS = {'Accept': 'application/json'}

def get_odata_data(endpoint, params=None):
    """Запрашивает данные из OData-сервиса"""
    url = urljoin(BASE_URL, endpoint)
    try:
        response = requests.get(url, params=params, headers=HEADERS)
        response.raise_for_status()
        return response.json().get('value', [])
    except Exception as e:
        print(f"🚨 Ошибка при запросе {url}: {str(e)}")
        return []

# 2. Отчеты по заказам 
def orders_by_customer():
    """Отчет по заказам клиентов"""
    params = {
        "$expand": "Клиенты",
        "$select": "Клиенты/Description,Number,Date,СуммаЗаказов"
    }
    
    orders = get_odata_data("Document_ЗаказКлиента", params)
    if not orders:
        print("❌ Нет данных о заказах клиентов")
        return

    # Создаем DataFrame с обработкой None и пустых значений
    df_data = []
    for order in orders:
        client = order.get('Клиенты', None)
        client_description = client.get('Description', 'Без имени') if client else 'Без имени'
        
        # Обработка СуммаЗаказов
        try:
            amount = float(order.get('СуммаЗаказов', 0)) if order.get('СуммаЗаказов', '') != '' else 0.0
        except (ValueError, TypeError):
            amount = 0.0
            print(f"⚠️ Заказ {order.get('Number', 'Unknown')} имеет некорректное значение СуммаЗаказов: {order.get('СуммаЗаказов', 'None')}")

        df_data.append({
            'Клиент': client_description,
            'Номер заказа': order.get('Number', ''),
            'Дата': pd.to_datetime(order.get('Date', None), errors='coerce'),
            'Сумма': amount
        })
    
    df = pd.DataFrame(df_data)
    
    customer_orders = df.groupby('Клиент').agg({
        'Номер заказа': 'count',
        'Сумма': 'sum'
    }).rename(columns={'Номер заказа': 'Количество заказов'})
    
    # График
    plt.figure(figsize=(12, 6))
    customer_orders['Количество заказов'].plot(kind='bar', color='lightblue')
    plt.title('Количество заказов по клиентам')
    plt.xlabel('Клиент')
    plt.ylabel('Количество заказов')
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()

def order_statuses():
    """Отчет по статусам заказов"""
    params = {
        "$select": "СтатусЗаказа"
    }
    
    orders = get_odata_data("Document_ЗаказКлиента", params)
    if not orders:
        print("❌ Нет данных о статусах заказов")
        return

    df = pd.DataFrame([order.get('СтатусЗаказа', 'Не указан') for order in orders], columns=['Статус'])
    status_counts = df['Статус'].value_counts()
    
    # График
    plt.figure(figsize=(8, 8))
    status_counts.plot(kind='pie', autopct='%1.1f%%', startangle=90)
    plt.title('Распределение статусов заказов')
    plt.ylabel('')
    plt.tight_layout()
    plt.show()

def payment_methods():
    """Отчет по методам оплаты"""
    params = {
        "$select": "МетодОплаты"
    }
    
    orders = get_odata_data("Document_ЗаказКлиента", params)
    if not orders:
        print("❌ Нет данных о методах оплаты")
        return

    df = pd.DataFrame([order.get('МетодОплаты', 'Не указан') for order in orders], columns=['Метод'])
    method_counts = df['Метод'].value_counts()
    
    # График
    plt.figure(figsize=(10, 6))
    method_counts.plot(kind='bar', color='coral')
    plt.title('Распределение методов оплаты')
    plt.xlabel('Метод оплаты')
    plt.ylabel('Количество заказов')
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()

def average_order_value():
    """Отчет по среднему чеку"""
    params = {
        "$select": "СуммаЗаказов"
    }
    
    orders = get_odata_data("Document_ЗаказКлиента", params)
    if not orders:
        print("❌ Нет данных о заказах")
        return

    df = pd.DataFrame([float(order.get('СуммаЗаказов', 0)) for order in orders], columns=['Сумма'])
    avg_value = df['Сумма'].mean()
    
    print(f"📊 Средний чек: {avg_value:.2f} руб")
    # Простой текстовый вывод, так как график для одного значения менее информативен

# 3. Отчеты по курьерам
def courier_load():
    """Отчет по нагрузке на курьеров"""
    params = {
        "$expand": "Курьер",
        "$select": "Курьер/Description,Date"
    }
    
    assignments = get_odata_data("Document_НазначениеКурьера", params)
    if not assignments:
        print("❌ Нет данных о назначениях курьеров")
        return

    df = pd.DataFrame([{
        'Курьер': assignment.get('Курьер', {}).get('Description', 'Без имени'),
        'Дата': pd.to_datetime(assignment.get('Date', None))
    } for assignment in assignments])
    
    courier_counts = df.groupby('Курьер').size()
    
    # График
    plt.figure(figsize=(12, 6))
    courier_counts.plot(kind='bar', color='lightgreen')
    plt.title('Нагрузка на курьеров (количество назначений)')
    plt.xlabel('Курьер')
    plt.ylabel('Количество назначений')
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()

def delivery_statuses():
    """Отчет по статусам доставок"""
    params = {
        "$select": "СтатусДоставки"
    }
    
    assignments = get_odata_data("Document_НазначениеКурьера", params)
    if not assignments:
        print("❌ Нет данных о статусах доставок")
        return

    df = pd.DataFrame([assignment.get('СтатусДоставки', 'Не указан') for assignment in assignments], columns=['Статус'])
    status_counts = df['Статус'].value_counts()
    
    # График
    plt.figure(figsize=(8, 8))
    status_counts.plot(kind='pie', autopct='%1.1f%%', startangle=90)
    plt.title('Распределение статусов доставок')
    plt.ylabel('')
    plt.tight_layout()
    plt.show()
 
# 6. Клиентские отчеты
def active_customers():
    """Отчет по активным клиентам"""
    params = {
        "$expand": "Клиенты",
        "$select": "Клиенты/Description,Number"
    }
    
    orders = get_odata_data("Document_ЗаказКлиента", params)
    if not orders:
        print("❌ Нет данных о клиентах")
        return

    df = pd.DataFrame([{
        'Клиент': order.get('Клиенты', {}).get('Description', 'Без имени'),
        'Заказ': order.get('Number', '')
    } for order in orders])
    
    active_counts = df.groupby('Клиент').size().nlargest(10)
    
    # График
    plt.figure(figsize=(12, 6))
    active_counts.plot(kind='bar', color='teal')
    plt.title('Топ-10 активных клиентов')
    plt.xlabel('Клиент')
    plt.ylabel('Количество заказов')
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()
 
if __name__ == "__main__":
    print("🔄 Загружаем данные...")
    
    # Вызов всех отчетов
    orders_by_customer()
    order_statuses()
    payment_methods()
    average_order_value()
    courier_load()
    delivery_statuses()
    # courier_efficiency()
    # warehouse_load()
    # goods_movement()
    # revenue_by_period()
    active_customers()
    # telegram_customers()
    # incomplete_orders()
    # low_stock_products()