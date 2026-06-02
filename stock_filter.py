import requests
import os

def get_raw_data():
    url = "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&type=ALL"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        # 直接抓取所有鍵值的第一個元素，看看裡面長怎樣
        for key in data:
            if isinstance(data[key], list) and len(data[key]) > 0:
                return f"Key: {key}, 第一筆資料: {str(data[key][0])[:100]}"
        return "找不到任何資料列"
    except Exception as e:
        return f"連線錯誤: {str(e)}"

def send_telegram(msg):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                  data={"chat_id": chat_id, "text": f"DEBUG: {msg}"})

if __name__ == "__main__":
    msg = get_raw_data()
    send_telegram(msg)
