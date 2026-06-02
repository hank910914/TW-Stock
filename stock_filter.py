# ============================================================
# 台股盤後篩選爬蟲：成交值1億以上 + 漲停股
# GitHub Actions 自動化版
# ============================================================

import requests
import pandas as pd
import numpy as np
from datetime import datetime
import time
import os
import warnings
warnings.filterwarnings('ignore')

HEADERS = {'User-Agent': 'Mozilla/5.0'}

# ============================================================
# 工具函式
# ============================================================

def safe_get(url, params=None, retries=3):
   for i in range(retries):
       try:
           r = requests.get(url, params=params, headers=HEADERS, timeout=20)
           r.raise_for_status()
           return r.json()
       except Exception as e:
           if i < retries - 1:
               time.sleep(2)
   return None

def clean_num(s):
   try:
       return float(str(s).replace(',', '').replace('+', '').strip())
   except:
       return np.nan

def get_today_str():
   return datetime.today().strftime('%Y%m%d')

# ============================================================
# 1. 抓今日全市場成交資料（含漲跌停判斷）
# ============================================================

def fetch_daily_quotes(date_str):
   print(f"📡 抓取個股日成交資料：{date_str}")
   url    = "https://www.twse.com.tw/exchangeReport/MI_INDEX"
   params = {"response": "json", "date": date_str, "type": "ALLBUT0999"}
   data   = safe_get(url, params)

   if not data or data.get('stat') != 'OK':
       print("  ⚠️  無資料（可能為假日或盤後尚未更新）")
       return pd.DataFrame()

   target = None
   for tbl in data.get('tables', []):
       if len(tbl.get('fields', [])) >= 16:
           target = tbl
           break

   if target:
       fields = target['fields']
       rows   = target['data']
   else:
       fields = data.get('fields9', [])
       rows   = data.get('data9', [])

   if not rows:
       print("  ⚠️  data 為空")
       return pd.DataFrame()

   df = pd.DataFrame(rows, columns=fields)

   col_map = {}
   for c in df.columns:
       cl = c.replace(' ', '')
       if   '證券代號' in cl or '股票代號' in cl: col_map[c] = 'code'
       elif '證券名稱' in cl or '股票名稱' in cl: col_map[c] = 'name'
       elif '開盤' in cl:                          col_map[c] = 'open'
       elif '最高' in cl:                          col_map[c] = 'high'
       elif '最低' in cl:                          col_map[c] = 'low'
       elif '收盤' in cl:                          col_map[c] = 'close'
       elif '漲跌價差' in cl:                      col_map[c] = 'change'
       elif '成交金額' in cl:                      col_map[c] = 'turnover'
       elif '成交股數' in cl:                      col_map[c] = 'volume'
       elif '成交筆數' in cl:                      col_map[c] = 'transactions'
   df = df.rename(columns=col_map)

   for col in ['open','high','low','close','change','turnover','volume']:
       if col in df.columns:
           df[col] = df[col].apply(clean_num)

   df = df.dropna(subset=['code', 'close']).copy()
   df['code'] = df['code'].astype(str).str.strip()
   df['name'] = df.get('name', pd.Series([''] * len(df))).astype(str).str.strip()

   df = df[df['code'].str.match(r'^\d{4}$')].reset_index(drop=True)

   print(f"  ✅ 取得 {len(df)} 筆個股資料")
   return df

# ============================================================
# 2. 抓漲跌停參考價（證交所公告）
# ============================================================

def fetch_limit_prices(date_str):
   print(f"📡 抓取漲跌停參考價：{date_str}")
   url  = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
   try:
       r = requests.get(url, headers=HEADERS, timeout=20)
       r.raise_for_status()
       data = r.json()
       df = pd.DataFrame(data)

       col_map = {}
       for c in df.columns:
           cl = c.replace(' ', '')
           if   '代號' in cl or 'Code' in c:       col_map[c] = 'code'
           elif '漲停' in cl or 'UpperLimit' in c: col_map[c] = 'limit_up'
           elif '跌停' in cl or 'LowerLimit' in c: col_map[c] = 'limit_down'
           elif '收盤' in cl or 'ClosingPrice' in c: col_map[c] = 'close_ref'
       df = df.rename(columns=col_map)

       for col in ['limit_up', 'limit_down', 'close_ref']:
           if col in df.columns:
               df[col] = df[col].apply(clean_num)

       df['code'] = df['code'].astype(str).str.strip()
       print(f"  ✅ 取得 {len(df)} 筆漲跌停資料")
       return df[['code'] + [c for c in ['limit_up','limit_down','close_ref'] if c in df.columns]]
   except Exception as e:
       print(f"  ⚠️  漲跌停資料取得失敗：{e}，改用漲幅10%推算")
       return pd.DataFrame()

# ============================================================
# 3. 判斷漲停
# ============================================================

def is_limit_up(row):
   close = row.get('close', np.nan)
   if pd.isna(close):
       return False

   lim = row.get('limit_up', np.nan)
   if not pd.isna(lim) and lim > 0:
       return abs(close - lim) < 0.02

   open_p  = row.get('open',  np.nan)
   high_p  = row.get('high',  np.nan)
   change  = row.get('change', np.nan)

   if not pd.isna(change) and not pd.isna(close) and close > 0:
       prev_close = close - change
       if prev_close > 0:
           chg_pct = change / prev_close
           if not pd.isna(high_p) and abs(close - high_p) < 0.01 and chg_pct >= 0.095:
               return True

   return False

# ============================================================
# 4. 三大法人
# ============================================================

def fetch_institutional(date_str):
   print(f"🏦 抓取三大法人買賣超：{date_str}")
   url    = "https://www.twse.com.tw/fund/T86"
   params = {"response": "json", "date": date_str, "selectType": "ALLBUT0999"}
   data   = safe_get(url, params)

   if not data or data.get('stat') != 'OK':
       print("  ⚠️  法人資料暫無")
       return pd.DataFrame()

   fields = data.get('fields', [])
   rows   = data.get('data', [])
   df     = pd.DataFrame(rows, columns=fields)

   col_map = {}
   for c in df.columns:
       cl = c.replace(' ','')
       if   '代號' in cl:                              col_map[c] = 'code'
       elif '名稱' in cl:                              col_map[c] = 'inst_name'
       elif '外資' in cl and '買賣超' in cl and '陸資' not in cl: col_map[c] = 'foreign_net'
       elif '投信' in cl and '買賣超' in cl:          col_map[c] = 'trust_net'
       elif '自營商' in cl and '買賣超' in cl and '避險' not in cl: col_map[c] = 'dealer_net'
   df = df.rename(columns=col_map)

   for col in ['foreign_net','trust_net','dealer_net']:
       if col in df.columns:
           df[col] = df[col].apply(clean_num).fillna(0)

   df['code'] = df['code'].astype(str).str.strip()
   keep = [c for c in ['code','foreign_net','trust_net','dealer_net'] if c in df.columns]
   print(f"  ✅ 取得 {len(df)} 筆法人資料")
   return df[keep]

# ============================================================
# 主程式
# ============================================================

def main():
   print("=" * 60)
   print("  台股盤後篩選：成交值1億以上 + 漲停股")
   print("=" * 60)

   date_str = get_today_str()
   print(f"📅 查詢日期：{date_str}\n")

   df = fetch_daily_quotes(date_str)
   if df.empty:
       print("❌ 無法取得日成交資料，請確認今日為交易日且盤後已更新（15:00後）")
       return

   df_lim = fetch_limit_prices(date_str)
   if not df_lim.empty:
       df = df.merge(df_lim, on='code', how='left')
   else:
       df['limit_up']   = np.nan
       df['limit_down'] = np.nan

   print(f"\n💰 篩選成交值 ≥ 1億...")
   df = df[df['turnover'] >= 1e8].copy()
   print(f"  ✅ 剩餘 {len(df)} 筆")

   print(f"🚀 篩選漲停股...")
   df['is_limit_up'] = df.apply(is_limit_up, axis=1)
   df = df[df['is_limit_up']].copy()
   print(f"  ✅ 漲停且成交值達標：{len(df)} 筆")

   if df.empty:
       print("\n⚠️  今日無符合條件的股票（若剛收盤請稍等資料更新）")
       # 即使空資料也建立一個空的 result.csv 避免自動化流程報錯
       pd.DataFrame(columns=['股票代號','股票名稱','收盤價','漲幅(%)']).to_csv('result.csv', index=False, encoding='utf-8-sig')
       return

   df_inst = fetch_institutional(date_str)
   if not df_inst.empty:
       df = df.merge(df_inst, on='code', how='left')
       for col in ['foreign_net','trust_net','dealer_net']:
           df[col] = df.get(col, pd.Series([0]*len(df))).fillna(0)
   else:
       df['foreign_net'] = 0
       df['trust_net']   = 0
       df['dealer_net']  = 0

   df['change_pct'] = np.where(
       (df['close'] - df['change']) > 0,
       (df['change'] / (df['close'] - df['change']) * 100).round(2),
       np.nan
   )

   df = df.sort_values('turnover', ascending=False).reset_index(drop=True)

   out_cols = {
       'code':         '股票代號',
       'name':         '股票名稱',
       'open':         '開盤價',
       'high':         '最高價',
       'low':          '最低價',
       'close':        '收盤價',
       'change':       '漲跌價差',
       'change_pct':   '漲幅(%)',
       'limit_up':     '漲停價',
       'turnover':     '成交金額(元)',
       'volume':       '成交股數',
       'foreign_net':  '外資買賣超(張)',
       'trust_net':    '投信買賣超(張)',
       'dealer_net':   '自營商買賣超(張)',
   }
   exist_cols = {k: v for k, v in out_cols.items() if k in df.columns}
   df_out = df[list(exist_cols.keys())].rename(columns=exist_cols)

   # ── 存檔至專案根目錄 (檔名固定為 result.csv 方便 GitHub Actions 讀取) ──
   df_out.to_csv('result.csv', index=False, encoding='utf-8-sig')

   print(f"\n{'='*60}")
   print(f"🎉 篩選完成！共 {len(df_out)} 支漲停股（成交值≥1億）")
   print(f"💾 已儲存至：result.csv")
   print(f"{'='*60}")

   show_cols = ['股票代號','股票名稱','收盤價','漲幅(%)','漲停價','成交金額(元)']
   show_cols = [c for c in show_cols if c in df_out.columns]
   print(df_out[show_cols].to_string(index=False))

   return df_out

# ── 標準執行入口 ──
if __name__ == '__main__':
    main()
