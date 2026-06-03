import requests
import pandas as pd
import io
import os

def run_filter():
    url = "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=csv&type=ALL"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.encoding = 'big5'
        
        # 尋找「證券代號」所在的行，作為表格開始
        lines = response.text.splitlines()
        start_idx = 0
        for i, line in enumerate(lines):
            if '證券代號' in line:
                start_idx = i
                break
        
        # 讀取個股表格
        df = pd.read_csv(io.StringIO("\n".join(lines[start_idx:])))
        
        # 強制只保留「漲停」字樣的股票
        # 檢查該列是否有「漲停」二字
        mask = df.apply(lambda row: row.astype(str).str.contains('漲停').any(), axis=1)
        df_final = df[mask]
        
        # 強制寫入 result.csv (覆蓋模式)
        df_final.to_csv("result.csv", index=False, encoding="utf-8-sig")
        print(f"✅ 檔案寫入成功，共 {len(df_final)} 支股票")
        
    except Exception as e:
        print(f"❌ 發生錯誤: {e}")

if __name__ == "__main__":
    run_filter()
