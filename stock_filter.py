import requests
import pandas as pd
import os

def get_real_stocks():
    url = "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&type=ALL"
    try:
        response = requests.get(url, timeout=15)
        data = response.json()
        
        # 搜尋包含個股資訊的表格 (尋找含有 '證券代號' 的 list)
        for key in data:
            if isinstance(data[key], list):
                for row in data[key]:
                    if "證券代號" in str(row):
                        # 找到包含股票資料的列表了
                        df = pd.DataFrame(data[key][1:], columns=data[key][0])
                        # 篩選「漲停」字樣 (通常在最後一欄)
                        limit_up = df[df.iloc[:, -1].astype(str).str.contains('漲停', na=False)]
                        return limit_up[['證券代號', '證券名稱', '收盤價']]
        return None
    except Exception as e:
        return f"錯誤: {e}"

def send_telegram(df):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if isinstance(df, str):
        msg = df
    elif df is None or df.empty:
        msg = "今日無漲停個股。"
    else:
        msg = "🚀 今日漲停股：\n" + df.to_string(index=False)
        
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                  data={"chat_id": chat_id, "text": msg})

if __name__ == "__main__":
    df = get_real_stocks()
    send_telegram(df)
