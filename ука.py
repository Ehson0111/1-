import requests
from bs4 import BeautifulSoup
import pandas as pd

def parse_avito(search_query="iPhone", city="moskva", max_pages=1):
    base_url = f"https://www.avito.ru/{city}?q={search_query}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    data = []
    
    for page in range(1, max_pages + 1):
        url = f"{base_url}&p={page}"
        response = requests.get(url, headers=headers)
        
        if response.status_code != 200:
            print(f"Ошибка: {response.status_code}")
            break
            
        soup = BeautifulSoup(response.text, "html.parser")
        items = soup.find_all("div", class_="iva-item-content-rejJg")
        
        for item in items:
            title = item.find("h3", class_="title-root-zZCwT").text.strip()
            price = item.find("span", class_="price-text-_YGDY").text.strip()
            link = "https://www.avito.ru" + item.find("a", class_="link-link-MbQDP")["href"]
            data.append({"Название": title, "Цена": price, "Ссылка": link})
    
    return pd.DataFrame(data)

# Пример использования
df = parse_avito(search_query="iPhone 13", city="moskva", max_pages=2)
print(df)
df.to_csv("avito_iphones.csv", index=False)  # Сохраняем в CSV