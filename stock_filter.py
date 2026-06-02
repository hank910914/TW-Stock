import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import time
import re

def get_strong_stocks():
    url = "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date=&type=ALL"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        
        if data.get('stat') != 'OK':
            print("今日非交易日或未取得資料")
            return None
            
        columns = data['fields9']
        rows = data['data9']
        
        df = pd.DataFrame(rows, columns=columns)
        
        # 1. 關鍵欄位強力清理：只留下數字、小數點和負號，徹底拔除證交所的特殊箭頭或 HTML 標籤
        for col in ['收盤價', '開盤價', '最高價', '最低價', '漲跌價差', '成交金額']:
            df[col] = df[col].astype(str).apply(lambda x: re.sub(r'[^0-9.-]', '', x))
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 2. 安全辨識漲停：使用你原本的最後一欄含「漲停」字眼辨識
        # 為了防呆，同時結合數學檢查 (收盤等於最高價且漲幅大於9.5%)
        # 昨收反推
        df['昨收'] = df['收盤價'] - df['漲跌價差']
        df['漲幅'] = (df['漲跌價差'] / df['昨收']) * 100
        
        df_filtered = df[
            (df['成交金額'] >= 100000000) & 
            ((df[df.columns[-1]].astype(str).str.contains('漲停', na=False)) | 
             ((df['收盤價'] == df['最高價']) & (df['漲幅'] >= 9.5)))
        ].copy()
        
        show_cols = ['證券代號', '證券名稱', '開盤價', '最高價', '最低價', '收盤價', '漲跌價差', '成交金額']
        df_out = df_filtered[show_cols]
        df_out.columns = ['股票代號', '股票名稱', '開盤價', '最高價', '最低價', '收盤價', '漲跌價差', '成交金額(元)']
        
        return df_out
        
    except Exception as e:
        print(f"抓取資料失敗: {e}")
        return None

def send_telegram_notification(df):
    bot_token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("未完整設定 TELEGRAM_TOKEN 或 TELEGRAM_CHAT_ID，跳過傳送通知")
        return
        
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    today = datetime.now().strftime('%Y-%m-%d')
    
    if df is None or df.empty:
        message = f"📊 *【台股強勢股監控】*\n📅 日期：`{today}`\n\n本日未篩選出符合「成交值破億 + 鎖漲停」的個股。"
    else:
        message = f"📊 *【台股強勢股監控】*\n📅 日期：`{today}`\n\n🔥 *今日符合條件個股如下：*\n"
        for idx, row in df.iterrows():
            amount_in_yi = float(row['成交金額(元)']) / 100000000
            message += f"────────────────\n"
            message += f"📈 *{row['股票代號']} {row['股票名稱']}*\n"
            message += f"💰 收盤價：`{row['收盤價']}` (價差: {row['漲跌價差']})\n"
            message += f"📊 成交量：`{amount_in_yi:.2f}` 億元\n"
            
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        print("Telegram 通知傳送成功！")
    else:
        print(f"傳送失敗，錯誤代碼: {response.text}")

if __name__ == "__main__":
    result_df = get_strong_stocks()
    
    if result_df is not None:
        result_df.to_csv("result.csv", index=False, encoding="utf-8-sig")
        
    send_telegram_notification(result_df)
