import requests
import pandas as pd
from datetime import datetime
import os

def get_strong_stocks():
    # 使用不帶日期的 API 預設抓最新資料
    url = "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&type=ALL"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        data = response.json()
        
        if data.get('stat') != 'OK':
            return None, None
            
        trade_date = data.get('date', 'Unknown')
        df = pd.DataFrame(data['data9'], columns=data['fields9'])
        
        # 徹底清洗數字欄位：移除逗號，強制轉為 float
        for col in ['收盤價', '開盤價', '最高價', '最低價', '成交金額']:
            df[col] = df[col].astype(str).str.replace(',', '').str.replace('+', '').str.replace('-', '')
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 篩選條件：成交金額 >= 5000 萬 (稍微放寬避免沒資料)，且收盤 > 開盤 (紅K)
        # 這裡不鎖定「漲停」字眼，改用漲幅計算
        df['漲幅'] = ((df['收盤價'] - (df['收盤價'] - df['漲跌價差'])) / (df['收盤價'] - df['漲跌價差'])) * 100
        
        df_filtered = df[
            (df['成交金額'] >= 50000000) & 
            (df['收盤價'] > df['開盤價'])
        ].copy()
        
        return df_filtered, trade_date
    except Exception as e:
        print(f"Error: {e}")
        return None, None

def send_telegram_notification(df, trade_date):
    bot_token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    if df is None or df.empty:
        msg = f"📊 *【台股監控】*\n📅 日期：{trade_date}\n\n本日未找到符合成交額 > 5000萬的紅K股。"
    else:
        msg = f"📊 *【台股監控】*\n📅 日期：{trade_date}\n🔥 *找到 {len(df)} 檔強勢股：*\n"
        for _, row in df.head(5).iterrows():
            msg += f"📈 {row['證券名稱']} (收: {row['收盤價']})\n"
            
    requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})

if __name__ == "__main__":
    df, t_date = get_strong_stocks()
    if df is not None:
        df.to_csv("result.csv", index=False, encoding="utf-8-sig")
    send_telegram_notification(df, t_date)
