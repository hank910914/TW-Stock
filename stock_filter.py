import requests
import pandas as pd
import numpy as np
import io
import os

# 這是針對 GitHub 伺服器環境的簡潔版爬蟲
def run_filter():
    url = "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=csv&type=ALL"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        # 抓取並編碼
        response = requests.get(url, headers=headers, timeout=20)
        response.encoding = 'big5'
        
        # 篩選掉非資料行
        lines = [line for line in response.text.splitlines() if len(line.split('",')) > 1]
        csv_data = "\n".join(lines)
        
        # 讀取並轉存
        df = pd.read_csv(io.StringIO(csv_data))
        df.to_csv("result.csv", index=False, encoding="utf-8-sig")
        print("✅ result.csv 更新成功")
        
    except Exception as e:
        print(f"❌ 錯誤: {e}")

if __name__ == "__main__":
    run_filter()
