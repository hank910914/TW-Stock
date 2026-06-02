import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import time

def get_strong_stocks():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    current_tw_time = datetime.utcnow() + timedelta(hours=8)
    
    for i in range(10):
        target_date = (current_tw_time - timedelta(days=i)).strftime('%Y%m%d')
        url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={target_date}&type=ALL"
        
        try:
            print(f"正在嘗試抓取 {target_date} 的台股盤後資料...")
            response = requests.get(url, headers=headers)
            data = response.json()
            
            if data.get('stat') != 'OK':
                time.sleep(2)
                continue
                
            print(f"🎉 成功取得 {target_date} 的交易資料！開始篩選...")
            columns = data['fields9']
            rows = data['data9']
            
            df = pd.DataFrame(rows, columns=columns)
            
            for col in ['收盤價', '最高價', '最低價', '開盤價', '成交金額']:
                df[col] = df[col].astype(str).str.replace(',', '')
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 【測試專用放寬條件】：成交額大於 1000 萬 且 收盤價 > 開盤價 (只要是紅K就抓)
            # 另外限制只抓前 10 檔，避免 Telegram 訊息太長爆炸
            df_filtered = df[
                (df['成交金額'] >= 10000000) & 
                (df['收盤價'] > df['開盤價'])
            ].head(10).copy()
            
            show_cols = ['證券代號', '證券名稱', '開盤價', '最高價', '最低價', '收盤價', '漲跌價差', '成交金額']
            df_out = df_filtered[show_cols]
            df_out.columns = ['股票代號', '股票名稱', '開盤價', '最高價', '最低價', '收盤價', '漲跌價差', '成交金額(元)']
            
            return df_out, target_date
            
        except Exception as e:
            print(f"抓取 {target_date} 資料發生錯誤: {e}")
            time.sleep(2)
            
    return None, None

def send_telegram_notification(df, trade_date):
    bot_token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("未完整設定 TELEGRAM_TOKEN 或 TELEGRAM_CHAT_ID，跳過傳送通知")
        return
        
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    formatted_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}" if trade_date else datetime.now().strftime('%Y-%m-%d')
    
    if df is None or df.empty:
        message = f"📊 *【台股強勢股監控】*\n📅 交易日期：`{formatted_date}`\n\n本日未篩選出符合「成交值破億 + 鎖漲停」的個股。"
    else:
        message = f"📊 *【台股強勢股監控】*\n📅 交易日期：`{formatted_date}`\n\n🔥 *今日【紅K棒】測試清單如下：*\n"
        for idx, row in df.iterrows():
            amount_in_yi = row['成交金額(元)'] / 100000000
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
    result_df, trade_date = get_strong_stocks()
    
    if result_df is not None:
        result_df.to_csv("result.csv", index=False, encoding="utf-8-sig")
        
    send_telegram_notification(result_df, trade_date)
