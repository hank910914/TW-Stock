import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import time

def get_strong_stocks():
    # 不帶任何 date 參數，證交所會自動回傳最新一個交易日的盤後資料
    url = "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&type=ALL"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        print("正在自證交所抓取最新台股盤後資料...")
        # 設定 timeout=15 防止網頁無限卡死
        response = requests.get(url, headers=headers, timeout=15)
        data = response.json()
        
        if data.get('stat') != 'OK':
            print("證交所回傳狀態異常或非交易日")
            return None, None
            
        # 取得證交所這份資料實際的交易日期
        trade_date_raw = data.get('date', datetime.now().strftime('%Y%m%d'))
        print(f"🎉 成功取得交易日期為 {trade_date_raw} 的資料！開始篩選...")
        
        columns = data['fields9']
        rows = data['data9']
        
        df = pd.DataFrame(rows, columns=columns)
        
        # 清理千分位逗號並轉為數字
        for col in ['收盤價', '最高價', '最低價', '開盤價', '成交金額']:
            df[col] = df[col].astype(str).str.replace(',', '')
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 終極精準數學篩選：
        # 1. 成交金額 >= 8000 萬
        # 2. 收盤價 == 最高價 (鎖死漲停)
        # 3. 收盤價 > 開盤價 (紅K)
        # 4. 收盤 / 最低價 >= 1.09 (當天拉幅夠大)
        df_filtered = df[
            (df['成交金額'] >= 80000000) & 
            (df['收盤價'] == df['最高價']) &
            (df['收盤價'] > df['開盤價']) &
            ((df['收盤價'] / df['最低價']) >= 1.09)
        ].copy()
        
        show_cols = ['證券代號', '證券名稱', '開盤價', '最高價', '最低價', '收盤價', '成交金額']
        df_out = df_filtered[show_cols]
        df_out.columns = ['股票代號', '股票名稱', '開盤價', '最高價', '最低價', '收盤價', '成交金額(元)']
        
        return df_out, trade_date_raw
        
    except Exception as e:
        print(f"抓取資料發生錯誤: {e}")
        return None, None

def send_telegram_notification(df, trade_date):
    bot_token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("錯誤：未完整設定 TELEGRAM_TOKEN 或 TELEGRAM_CHAT_ID")
        return
        
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    # 格式化日期顯示
    if trade_date and len(trade_date) == 8:
        formatted_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    else:
        formatted_date = datetime.now().strftime('%Y-%m-%d')
    
    if df is None or df.empty:
        message = f"📊 *【台股強勢股監控】*\n📅 交易日期：`{formatted_date}`\n\n本日未篩選出符合「成交值破八千萬 + 鎖漲停」的個股。"
    else:
        message = f"📊 *【台股強勢股監控】*\n📅 交易日期：`{formatted_date}`\n\n🔥 *今日符合條件個股如下：*\n"
        for idx, row in df.iterrows():
            amount_in_yi = row['成交金額(元)'] / 100000000
            message += f"────────────────\n"
            message += f"📈 *{row['股票代號']} {row['股票名稱']}*\n"
            message += f"💰 收盤價：`{row['收盤價']}`\n"
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
        print(f"發送失敗，錯誤代碼: {response.text}")

if __name__ == "__main__":
    result_df, trade_date = get_strong_stocks()
    
    if result_df is not None:
        result_df.to_csv("result.csv", index=False, encoding="utf-8-sig")
        
    send_telegram_notification(result_df, trade_date)
