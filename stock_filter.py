"""
台股股票篩選器
條件：
1. 成交值 1 億以上
2. 上個月漲幅大於 15%
3. 連續收漲兩天以上
4. 外資連續 3-5 天買超
"""

import os
import json
import time
import requests
import gspread
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
import pandas as pd


# ── Google Sheets 設定 ──────────────────────────────────────────────────────
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")          # 從 GitHub Secret 讀取
SHEET_NAME = os.environ.get("SHEET_NAME", "股票篩選結果")

# ── TWSE / TPEX API ────────────────────────────────────────────────────────
TWSE_TRADING_URL   = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL"
TWSE_FOREIGN_URL   = "https://www.twse.com.tw/rwd/zh/fund/TWT38U"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StockScreener/1.0)"}


def fetch_twse_daily_all() -> pd.DataFrame:
    """取得上市股票當日所有個股行情（成交金額、漲跌）。"""
    resp = requests.get(TWSE_TRADING_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("stat") != "OK":
        raise RuntimeError(f"TWSE STOCK_DAY_ALL 回傳錯誤：{data.get('stat')}")

    cols = ["股票代號", "股票名稱", "成交股數", "成交筆數", "成交金額",
            "開盤價", "最高價", "最低價", "收盤價", "漲跌(+/-)", "漲跌價差", "最後揭示買價",
            "最後揭示買量", "最後揭示賣價", "最後揭示賣量", "本益比"]
    rows = data.get("data", [])
    df = pd.DataFrame(rows, columns=cols[:len(rows[0])] if rows else cols)

    # 數字清洗
    for col in ["成交金額", "收盤價", "漲跌價差", "開盤價", "最高價", "最低價"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", ""), errors="coerce")

    # 只保留 4 位數代號（排除 ETF、權證等）
    df = df[df["股票代號"].str.match(r"^\d{4}$", na=False)].copy()
    return df


def fetch_monthly_price(stock_id: str, year: int, month: int) -> dict | None:
    """
    取得指定月份個股月行情（TWSE STOCK_DAY），
    回傳 {'open': 第一日開盤, 'close': 最後一日收盤, 'dates': [date,...], 'closes': [close,...]}
    """
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
    params = {"stockNo": stock_id, "date": f"{year}{month:02d}01", "response": "json"}
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("stat") != "OK" or not data.get("data"):
            return None
        rows = data["data"]
        # 欄位: 日期,成交股數,成交金額,開盤價,最高價,最低價,收盤價,漲跌價差,成交筆數
        closes = []
        dates  = []
        for r in rows:
            try:
                c = float(r[6].replace(",", ""))
                closes.append(c)
                dates.append(r[0])
            except Exception:
                pass
        if len(closes) < 2:
            return None
        return {
            "open":   float(rows[0][3].replace(",", "")),
            "close":  closes[-1],
            "dates":  dates,
            "closes": closes,
        }
    except Exception:
        return None


def calc_last_month_return(stock_id: str) -> float | None:
    """計算上個月的漲幅 (%)。"""
    today = datetime.today()
    first = today.replace(day=1)
    last_month_last = first - timedelta(days=1)
    y, m = last_month_last.year, last_month_last.month
    info = fetch_monthly_price(stock_id, y, m)
    if info is None:
        return None
    if info["open"] == 0:
        return None
    return round((info["close"] - info["open"]) / info["open"] * 100, 2)


def consecutive_rise_days(stock_id: str) -> int:
    """
    計算最近連續收漲天數（收盤 > 前一日收盤）。
    最多查近 10 個交易日。
    """
    today = datetime.today()
    y, m = today.year, today.month
    info = fetch_monthly_price(stock_id, y, m)
    # 若本月資料不足，也取上個月
    closes = []
    if info:
        closes = info["closes"]
    if len(closes) < 3:
        first = today.replace(day=1)
        lm = (first - timedelta(days=1))
        prev = fetch_monthly_price(stock_id, lm.year, lm.month)
        if prev:
            closes = prev["closes"] + closes

    if len(closes) < 2:
        return 0

    count = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            count += 1
        else:
            break
    return count


def fetch_foreign_net_buy(date_str: str) -> pd.DataFrame:
    """
    取得特定日期外資買賣超資料（TWSE TWT38U）。
    date_str 格式：YYYYMMDD
    回傳 DataFrame，含 股票代號、外資買賣超。
    """
    params = {"date": date_str, "selectType": "ALLBUT0999", "response": "json"}
    try:
        resp = requests.get(TWSE_FOREIGN_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("stat") != "OK" or not data.get("data"):
            return pd.DataFrame()
        # 欄位順序（以實際 API 為準，第 0 欄=代號, 第 1 欄=名稱, 第 10 欄=外資買賣超張數）
        rows = data["data"]
        records = []
        for r in rows:
            try:
                code = r[0].strip()
                net  = int(r[10].replace(",", "").replace("+", ""))
                records.append({"股票代號": code, "外資買賣超": net})
            except Exception:
                pass
        return pd.DataFrame(records)
    except Exception:
        return pd.DataFrame()


def get_recent_trading_dates(n: int = 7) -> list[str]:
    """推算最近 n 個可能的交易日（往前推，格式 YYYYMMDD）。"""
    dates = []
    d = datetime.today()
    while len(dates) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:   # 週一到週五
            dates.append(d.strftime("%Y%m%d"))
    return dates


def check_foreign_consecutive(stock_id: str, min_days: int = 3, max_days: int = 5) -> int:
    """
    檢查外資是否連續 min_days ~ max_days 天買超。
    回傳實際連續買超天數（0 表示不符合）。
    """
    recent_dates = get_recent_trading_dates(max_days + 2)
    consecutive = 0
    for date_str in recent_dates:
        df = fetch_foreign_net_buy(date_str)
        if df.empty:
            continue
        row = df[df["股票代號"] == stock_id]
        if row.empty:
            break
        net = row["外資買賣超"].values[0]
        if net > 0:
            consecutive += 1
            if consecutive >= max_days:
                break
        else:
            break
        time.sleep(0.3)   # 避免過快請求
    return consecutive


# ── 主篩選流程 ──────────────────────────────────────────────────────────────
def run_screener() -> list[dict]:
    print("📡 取得上市全體行情...")
    df_all = fetch_twse_daily_all()

    # 條件 1：成交值 >= 1 億
    df_all["成交金額"] = pd.to_numeric(df_all["成交金額"], errors="coerce")
    df_vol = df_all[df_all["成交金額"] >= 1e8].copy()
    print(f"✅ 條件 1（成交值≥1億）：{len(df_vol)} 檔")

    results = []
    total = len(df_vol)

    for idx, (_, row) in enumerate(df_vol.iterrows(), 1):
        sid  = row["股票代號"]
        name = row["股票名稱"]
        print(f"  [{idx}/{total}] 檢查 {sid} {name}", end=" ")

        # 條件 2：上個月漲幅 > 15%
        last_ret = calc_last_month_return(sid)
        time.sleep(0.2)
        if last_ret is None or last_ret <= 15:
            print(f"❌ 上月漲幅={last_ret}")
            continue

        # 條件 3：連續收漲 >= 2 天
        rise_days = consecutive_rise_days(sid)
        time.sleep(0.2)
        if rise_days < 2:
            print(f"❌ 連漲={rise_days}天")
            continue

        # 條件 4：外資連續 3-5 天買超
        foreign_days = check_foreign_consecutive(sid)
        if foreign_days < 3:
            print(f"❌ 外資連買={foreign_days}天")
            continue

        print(f"✅ 上月漲幅={last_ret}%, 連漲={rise_days}天, 外資連買={foreign_days}天")
        results.append({
            "股票代號":     sid,
            "股票名稱":     name.strip(),
            "成交值(億)":   round(row["成交金額"] / 1e8, 2),
            "收盤價":       row["收盤價"],
            "上月漲幅(%)":  last_ret,
            "連續收漲(天)": rise_days,
            "外資連買(天)": foreign_days,
        })
        time.sleep(0.3)

    return results


# ── 寫入 Google Sheets ──────────────────────────────────────────────────────
def write_to_sheets(records: list[dict]):
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
    if not creds_json:
        raise EnvironmentError("缺少環境變數 GOOGLE_CREDENTIALS_JSON")

    creds_info = json.loads(creds_json)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    gc    = gspread.authorize(creds)
    sh    = gc.open_by_key(SPREADSHEET_ID)

    try:
        ws = sh.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=SHEET_NAME, rows=500, cols=20)

    ws.clear()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    header_row = [[f"篩選時間：{now_str}　　共 {len(records)} 檔符合條件"]]
    ws.update("A1", header_row)

    if not records:
        ws.update("A2", [["今日無符合條件的股票"]])
        print("⚠️  無符合條件的股票，已寫入空白結果。")
        return

    cols = ["股票代號", "股票名稱", "成交值(億)", "收盤價", "上月漲幅(%)", "連續收漲(天)", "外資連買(天)"]
    ws.update("A2", [cols])

    rows = [[r[c] for c in cols] for r in records]
    ws.update("A3", rows)

    # 格式化標頭（粗體 + 背景色）
    fmt_title = {"backgroundColor": {"red": 0.2, "green": 0.5, "blue": 0.8},
                 "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1},
                                "bold": True, "fontSize": 11}}
    fmt_header = {"backgroundColor": {"red": 0.9, "green": 0.95, "blue": 1},
                  "textFormat": {"bold": True}}
    ws.format("A1:G1", fmt_title)
    ws.format("A2:G2", fmt_header)

    print(f"✅ 已寫入 Google Sheets：{len(records)} 檔")


# ── 入口 ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"🚀 開始篩選 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    try:
        matched = run_screener()
        print(f"\n📊 篩選結果：共 {len(matched)} 檔符合條件")
        for r in matched:
            print(f"  {r['股票代號']} {r['股票名稱']}  上月漲幅={r['上月漲幅(%)']}%  "
                  f"連漲={r['連續收漲(天)']}天  外資連買={r['外資連買(天)']}天")
        write_to_sheets(matched)
        print("🎉 完成！")
    except Exception as e:
        print(f"❌ 執行失敗：{e}")
        raise
