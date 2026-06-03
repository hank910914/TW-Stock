import requests
import pandas as pd
import io

def run_filter():
    # 使用證交所 CSV 網址
    url = "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=csv&type=ALL"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.encoding = 'big5'
        
        # 尋找「證券代號」作為資料起始點
        lines = response.text.splitlines()
        start_idx = 0
        for i, line in enumerate(lines):
            if '證券代號' in line:
                start_idx = i
                break
        
        # 讀取 CSV
        df = pd.read_csv(io.StringIO("\n".join(lines[start_idx:])))
        
        # --- 診斷與篩選 ---
        # 1. 將所有欄位名稱印出來，看看你的 CSV 裡欄位到底叫什麼
        print(f"DEBUG: 抓到的欄位名稱: {list(df.columns)}")
        
        # 2. 為了確保我們能抓到資料，先不篩選，直接把「前 50 筆」資料存起來
        # 這樣你就能看到 CSV 裡面到底存了什麼數字
        df_debug = df.head(50)
        df_debug.to_csv("result.csv", index=False, encoding="utf-8-sig")
        print("✅ 已更新 result.csv 為前 50 筆原始資料")
            
    except Exception as e:
        print(f"❌ 發生錯誤: {e}")

if __name__ == "__main__":
    run_filter()
