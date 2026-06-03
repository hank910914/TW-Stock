import pandas as pd
import requests
from datetime import datetime

# 建議使用 TWSE 官方 API 較為穩定，若堅持玩股網，需依其網頁結構更新 URL
# 此處提供核心邏輯架構，將結果覆蓋寫入 result.csv
def run_filter():
    try:
        # 這裡示範取得台股全市場個股資料
        url = "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=csv&type=ALL"
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        
        # 簡單處理 CSV 開頭雜訊
        lines = r.text.split('\n')
        lines = [l for l in lines if len(l.split('",')) > 2]
        df = pd.read_csv("\n".join(lines))
        
        # --- 篩選邏輯 ---
        # 1. 成交值超過 1 億
        df['成交金額'] = df['成交金額'].str.replace(',', '').astype(float)
        df = df[df['成交金額'] > 100000000]
        
        # 2. 前一個月漲幅超過 15% (需結合歷史 API 數據)
        # 3. 外資連續 3-5 天買超
        # 4. 近兩個交易日收漲
        
        # --- 覆蓋儲存 ---
        df.to_csv("result.csv", index=False, encoding="utf-8-sig")
        print("✅ 篩選成功，result.csv 已更新")
        
    except Exception as e:
        print(f"❌ 錯誤: {e}")

if __name__ == "__main__":
    run_filter()
