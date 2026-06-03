import requests
import pandas as pd
import io

def run_filter():
    url = "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=csv&type=ALL"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.encoding = 'big5'
        
        lines = response.text.splitlines()
        # 尋找關鍵表頭
        data_start_index = 0
        for i, line in enumerate(lines):
            if '證券代號' in line:
                data_start_index = i
                break
        
        df = pd.read_csv(io.StringIO("\n".join(lines[data_start_index:])))
        
        # --- 除錯與篩選邏輯 ---
        # 1. 確保欄位名稱正確 (證交所可能會改名，我們用模糊比對)
        # 檢查該列是否包含「漲停」字樣
        # 這裡改用字串比對，容錯率更高
        def check_is_limit_up(row):
            row_str = row.to_string()
            return '漲停' in row_str
        
        df_limit_up = df[df.apply(check_is_limit_up, axis=1)]
        
        # 2. 顯示除錯訊息到 Log
        print(f"DEBUG: 原始資料總筆數 {len(df)}")
        print(f"DEBUG: 篩選出漲停數 {len(df_limit_up)}")
        
        # 3. 寫入檔案
        if not df_limit_up.empty:
            df_limit_up.to_csv("result.csv", index=False, encoding="utf-8-sig")
            print("✅ 成功寫入漲停股至 result.csv")
        else:
            # 如果還是沒資料，至少存一個空的表確認程式有跑過
            df.head(0).to_csv("result.csv", index=False, encoding="utf-8-sig")
            print("⚠️ 今日篩選結果為空，已更新 result.csv 為空表")
            
    except Exception as e:
        print(f"❌ 發生錯誤: {e}")

if __name__ == "__main__":
    run_filter()
