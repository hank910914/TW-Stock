import requests
import pandas as pd
import os

def debug_stocks():
    # 這是原始的 API 網址，不更動
    url = "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&type=ALL"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        data = response.json()
        
        # 抓取表格的欄位名稱，這非常重要，我們要確認欄位名稱是否正確
        columns = data['fields9']
        rows = data['data9']
        df = pd.DataFrame(rows, columns=columns)
        
        # 我們只取前 3 檔股票的資訊丟出來看
        debug_msg = f"欄位名稱: {columns[:5]}...\n\n前3檔數據:\n{df.head(3).to_string()}"
        return debug_msg
        
    except Exception as e:
        return f"發生錯誤: {str(e)}"

def send_debug_message(message):
    bot_token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    # 用 code 區塊格式化訊息，避免排版跑掉
    msg = f"🔍 *【除錯資訊】*\n```\n{message}\n```"
    requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})

if __name__ == "__main__":
    msg = debug_stocks()
    send_debug_message(msg)
