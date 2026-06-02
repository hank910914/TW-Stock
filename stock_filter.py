import requests
import pandas as pd
import os

def get_limit_up_stocks():
    # 抓取證交所每日收盤資料
    url = "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&type=ALL"
    try:
        data = requests.get(url, timeout=10).json()
        # 尋找包含「漲停」資訊的資料結構
        # 證交所 API 資料通常在 data9 或 data8，直接遍歷尋找
        for key in data:
            if isinstance(data[key], list) and len(data[key]) > 0:
                # 篩選含有「漲停」字樣的行
                for row in data[key]:
                    if "漲停" in str(row):
                        return row
        return None
    except:
        return None

def send_telegram(stock_info):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    msg = f"🚀 發現漲停股: {stock_info}" if stock_info else "今日無漲停資訊。"
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                  data={"chat_id": chat_id, "text": msg})

if __name__ == "__main__":
    info = get_limit_up_stocks()
    send_telegram(info)

