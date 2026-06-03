"""
stock_filter.py
台股篩選腳本 - 專為 GitHub Actions 環境設計
資料來源: 台灣證券交易所 (TWSE) 公開 API + 玩股網
篩選條件:
  1. 成交金額 > 1 億元
  2. 過去 20 個交易日漲幅 > 15%
  3. 外資近 5 日連續 3~5 天淨買超
  4. 今日與昨日收盤價皆上漲
"""

import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta

# ─── 環境變數 ────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.twse.com.tw/",
}

OUTPUT_CSV = "result.csv"


# ─── Telegram 通知 ────────────────────────────────────────────────────────────
def send_telegram(message: str) -> None:
    """透過 Telegram Bot API 發送訊息，失敗時僅印出警告，不中斷程式。"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] Telegram 環境變數未設定，跳過通知。")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        print("[INFO] Telegram 通知發送成功。")
    except Exception as e:
        print(f"[WARN] Telegram 發送失敗: {e}")


# ─── 取得交易日曆 ─────────────────────────────────────────────────────────────
def get_recent_trading_dates(n: int = 30) -> list[str]:
    """
    從 TWSE 取得最近 n 個交易日的日期清單 (格式 YYYYMMDD)。
    使用大盤指數歷史資料來推算交易日。
    """
    print("[INFO] 取得近期交易日清單...")
    end_date = datetime.today()
    # 往前取兩個月資料確保涵蓋足夠交易日
    start_date = end_date - timedelta(days=90)
    url = (
        "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST"
        f"?date={end_date.strftime('%Y%m%d')}&response=json"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("stat") != "OK":
            raise ValueError("TWSE 大盤資料回傳異常")
        # 取資料中的日期欄 (民國年轉西元)
        rows = data.get("data", [])
        dates = []
        for row in rows:
            roc_date = row[0].replace("/", "")  # e.g. "113/05/01" -> "1130501"
            year = int(roc_date[:3]) + 1911
            mmdd = roc_date[3:]
            dates.append(f"{year}{mmdd}")
        dates = sorted(set(dates), reverse=True)
        print(f"[INFO] 取得 {len(dates)} 個交易日 (本月)。")
        return dates[:n]
    except Exception as e:
        print(f"[WARN] 取得交易日失敗，改用推算方式: {e}")
        # Fallback: 排除週末估算
        dates = []
        cur = end_date
        while len(dates) < n:
            if cur.weekday() < 5:
                dates.append(cur.strftime("%Y%m%d"))
            cur -= timedelta(days=1)
        return dates


# ─── 取得全市場成交量排行 (TWSE) ──────────────────────────────────────────────
def fetch_twse_daily_trades(date: str) -> pd.DataFrame:
    """
    取得指定日期 TWSE 所有上市股票的成交資料。
    回傳 DataFrame: [stock_id, stock_name, close, change, volume_value]
    """
    url = (
        f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
        f"?date={date}&type=ALLBUT0999&response=json"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("stat") != "OK":
            print(f"[WARN] {date} TWSE 資料回傳異常: {data.get('stat')}")
            return pd.DataFrame()

      def fetch_twse_daily_trades(date: str) -> pd.DataFrame:
    """
    【改良版】動態搜尋資料，自動適應證交所欄位變動
    """
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={date}&type=ALLBUT0999&response=json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        data = resp.json()
        
        # 核心修改：遍歷所有表格結構，找出包含「證券代號」的欄位表
        target_df = None
        
        # 檢查 data 中的 tables (新版格式)
        if "tables" in data:
            for table in data["tables"]:
                if any("證券代號" in str(c) for c in table.get("fields", [])):
                    target_df = pd.DataFrame(table["data"], columns=table["fields"])
                    break
        
        # 若表格中找不到，再檢查舊版格式
        if target_df is None:
            for i in range(10): # 檢查 data8, data9...
                key_data = f"data{i}"
                key_fields = f"fields{i}"
                if key_data in data and key_fields in data:
                    if any("證券代號" in str(c) for c in data[key_fields]):
                        target_df = pd.DataFrame(data[key_data], columns=data[key_fields])
                        break
        
        if target_df is None:
            print(f"[WARN] {date} 找不到包含「證券代號」的資料表。")
            return pd.DataFrame()

        # 【關鍵清洗】：移除欄位名稱的任何空格、換行或括號，避免比對失效
        target_df.columns = [str(c).replace(" ", "").replace("(", "").replace(")", "").replace("\n", "") for c in target_df.columns]

        # 映射欄位 (使用模糊匹配的概念)
        col_map = {
            "證券代號": "stock_id",
            "證券名稱": "stock_name",
            "收盤價": "close",
            "漲跌價差": "change",
            "成交金額": "volume_value"
        }
        
        # 執行重命名
        target_df.rename(columns=col_map, inplace=True)
        
        # 確保必要欄位存在
        required = ["stock_id", "stock_name", "close", "change", "volume_value"]
        if not all(col in target_df.columns for col in required):
            print(f"[WARN] 欄位缺失。當前欄位: {list(target_df.columns)}")
            return pd.DataFrame()

        # 數值清洗
        for col in ["close", "change", "volume_value"]:
            target_df[col] = pd.to_numeric(target_df[col].astype(str).str.replace(",", "").str.replace("+", ""), errors="coerce")

        return target_df[required].dropna(subset=["stock_id"])

    except Exception as e:
        print(f"[ERROR] 抓取資料發生異常: {e}")
        return pd.DataFrame()


        print(f"[INFO] {date} 取得 {len(rows)} 筆上市資料，欄位: {fields}")

        df = pd.DataFrame(rows, columns=fields)

        # 標準化欄位名稱
        col_map = {}
        for col in df.columns:
            if "證券代號" in col or "股票代號" in col:
                col_map[col] = "stock_id"
            elif "證券名稱" in col or "股票名稱" in col:
                col_map[col] = "stock_name"
            elif "收盤" in col:
                col_map[col] = "close"
            elif "漲跌價差" in col or "漲跌" in col:
                col_map[col] = "change"
            elif "成交金額" in col:
                col_map[col] = "volume_value"
        df.rename(columns=col_map, inplace=True)

        required = ["stock_id", "stock_name", "close", "change", "volume_value"]
        for col in required:
            if col not in df.columns:
                print(f"[WARN] 缺少欄位 {col}，跳過此日期。")
                return pd.DataFrame()

        # 清理數值 (移除逗號、+/- 符號)
        for col in ["close", "change", "volume_value"]:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(",", "", regex=False)
                .str.replace("+", "", regex=False)
                .str.strip()
            )
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # 過濾非純數字代號 (ETF、權證等)
        df = df[df["stock_id"].str.match(r"^\d{4}$", na=False)].copy()
        df.reset_index(drop=True, inplace=True)
        return df[["stock_id", "stock_name", "close", "change", "volume_value"]]

    except Exception as e:
        print(f"[ERROR] 取得 {date} TWSE 資料失敗: {e}")
        return pd.DataFrame()


# ─── 取得外資買賣超資料 (TWSE) ────────────────────────────────────────────────
def fetch_foreign_net_buy(date: str) -> pd.DataFrame:
    """
    取得指定日期外資買賣超資料。
    回傳 DataFrame: [stock_id, foreign_net]  (正數=買超, 負數=賣超)
    """
    url = (
        f"https://www.twse.com.tw/rwd/zh/fund/T86"
        f"?date={date}&selectType=ALLBUT0999&response=json"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("stat") != "OK":
            print(f"[WARN] {date} 外資資料異常: {data.get('stat')}")
            return pd.DataFrame()

        fields = data.get("fields", [])
        rows = data.get("data", [])
        if not fields or not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=fields)

        col_map = {}
        for col in df.columns:
            if "證券代號" in col:
                col_map[col] = "stock_id"
            elif "外陸資買賣超股數" in col or "外資及陸資買賣超" in col:
                col_map[col] = "foreign_net"
            # 部分版本欄位名稱不同，兜底處理
            elif col in ["外資買賣超股數(不含外資自營商)", "外資及陸資(不含外資自營商)買賣超股數"]:
                col_map[col] = "foreign_net"

        df.rename(columns=col_map, inplace=True)

        if "stock_id" not in df.columns:
            print(f"[WARN] {date} 外資資料缺少 stock_id 欄位。fields={fields}")
            return pd.DataFrame()

        # 若沒有 foreign_net，嘗試用「買進」-「賣出」計算
        if "foreign_net" not in df.columns:
            buy_col = next((c for c in df.columns if "買進" in c), None)
            sell_col = next((c for c in df.columns if "賣出" in c), None)
            if buy_col and sell_col:
                df["foreign_net"] = (
                    pd.to_numeric(df[buy_col].str.replace(",", "", regex=False), errors="coerce") -
                    pd.to_numeric(df[sell_col].str.replace(",", "", regex=False), errors="coerce")
                )
            else:
                print(f"[WARN] {date} 無法計算外資買賣超。")
                return pd.DataFrame()

        df["foreign_net"] = (
            df["foreign_net"]
            .astype(str)
            .str.replace(",", "", regex=False)
            .str.strip()
        )
        df["foreign_net"] = pd.to_numeric(df["foreign_net"], errors="coerce")
        df = df[df["stock_id"].str.match(r"^\d{4}$", na=False)].copy()
        return df[["stock_id", "foreign_net"]].dropna()

    except Exception as e:
        print(f"[ERROR] 取得 {date} 外資資料失敗: {e}")
        return pd.DataFrame()


# ─── 主篩選邏輯 ───────────────────────────────────────────────────────────────
def main():
    today_str = datetime.today().strftime("%Y-%m-%d")
    print(f"\n{'='*60}")
    print(f"[INFO] 台股篩選啟動 | 日期: {today_str}")
    print(f"{'='*60}\n")

    # 1. 取得近 30 個交易日
    trading_dates = get_recent_trading_dates(n=30)
    if len(trading_dates) < 22:
        msg = f"❌ [{today_str}] 無法取得足夠交易日資料，篩選中止。"
        print(f"[ERROR] {msg}")
        send_telegram(msg)
        return

    today_date = trading_dates[0]
    yesterday_date = trading_dates[1]
    date_20d_ago = trading_dates[20]  # 約 1 個月前 (20 交易日)
    dates_5d = trading_dates[:5]  # 近 5 個交易日 (含今日)

    print(f"[INFO] 今日: {today_date}, 昨日: {yesterday_date}, 20日前: {date_20d_ago}")
    print(f"[INFO] 近 5 個交易日: {dates_5d}")

    # 2. 取得今日成交資料
    print("\n[INFO] ── 抓取今日成交資料 ──")
    df_today = fetch_twse_daily_trades(today_date)
    if df_today.empty:
        msg = f"❌ [{today_str}] 今日成交資料取得失敗，可能非交易日或資料未更新。"
        print(f"[WARN] {msg}")
        send_telegram(msg)
        return
    time.sleep(1)

    # 3. 取得昨日成交資料
    print("\n[INFO] ── 抓取昨日成交資料 ──")
    df_yesterday = fetch_twse_daily_trades(yesterday_date)
    if df_yesterday.empty:
        print("[WARN] 昨日資料取得失敗，技術面條件將無法驗證。")
    time.sleep(1)

    # 4. 取得 20 日前收盤價
    print("\n[INFO] ── 抓取 20 日前收盤價 ──")
    df_20d = fetch_twse_daily_trades(date_20d_ago)
    if df_20d.empty:
        msg = f"❌ [{today_str}] 20 日前資料取得失敗，無法計算漲幅。"
        print(f"[WARN] {msg}")
        send_telegram(msg)
        return
    time.sleep(1)

    # 5. 取得近 5 日外資買賣超
    print("\n[INFO] ── 抓取近 5 日外資買賣超 ──")
    foreign_list = []
    for d in dates_5d:
        df_f = fetch_foreign_net_buy(d)
        if not df_f.empty:
            df_f = df_f.rename(columns={"foreign_net": f"foreign_{d}"})
            foreign_list.append(df_f.set_index("stock_id"))
        time.sleep(1)

    if not foreign_list:
        msg = f"❌ [{today_str}] 外資資料完全取得失敗。"
        print(f"[ERROR] {msg}")
        send_telegram(msg)
        return

    df_foreign = pd.concat(foreign_list, axis=1).reset_index()
    df_foreign.rename(columns={"index": "stock_id"}, inplace=True)
    print(f"[INFO] 外資資料合併完成，共 {len(df_foreign)} 筆。")

    # ─── 開始篩選 ─────────────────────────────────────────────────────────────
    print("\n[INFO] ── 開始套用篩選條件 ──")

    # 合併今日 + 昨日 + 20日前資料
    df = df_today.copy()
    df = df.rename(columns={"close": "close_today", "change": "change_today"})

    if not df_yesterday.empty:
        df_y = df_yesterday[["stock_id", "change"]].rename(columns={"change": "change_yesterday"})
        df = df.merge(df_y, on="stock_id", how="left")
    else:
        df["change_yesterday"] = float("nan")

    df_20 = df_20d[["stock_id", "close"]].rename(columns={"close": "close_20d"})
    df = df.merge(df_20, on="stock_id", how="left")

    # 合併外資
    df = df.merge(df_foreign, on="stock_id", how="left")

    print(f"[INFO] 合併後總筆數: {len(df)}")

    # 條件 1: 成交金額 > 1 億 (單位: 元)
    cond1 = df["volume_value"] > 1e8
    print(f"[FILTER] 條件1 (成交金額 > 1億): {cond1.sum()} 筆")

    # 條件 2: 近 20 個交易日漲幅 > 15%
    df["pct_change_20d"] = (df["close_today"] - df["close_20d"]) / df["close_20d"] * 100
    cond2 = df["pct_change_20d"] > 15
    print(f"[FILTER] 條件2 (20日漲幅 > 15%): {cond2.sum()} 筆")

    # 條件 3: 外資近 5 日連續 3~5 天淨買超
    foreign_cols = [c for c in df.columns if c.startswith("foreign_")]
    def check_foreign_consecutive(row):
        """計算從最新日起連續買超天數，需達 3 天以上。"""
        vals = [row.get(c, float("nan")) for c in foreign_cols]
        count = 0
        for v in vals:  # foreign_cols 已按日期降序排列 (最新在前)
            if pd.isna(v):
                break
            if v > 0:
                count += 1
            else:
                break
        return 3 <= count <= 5

    if foreign_cols:
        cond3 = df.apply(check_foreign_consecutive, axis=1)
    else:
        cond3 = pd.Series([False] * len(df))
    print(f"[FILTER] 條件3 (外資連續3-5天買超): {cond3.sum()} 筆")

    # 條件 4: 今日與昨日收盤價皆上漲
    cond4_today = df["change_today"] > 0
    cond4_yest = df["change_yesterday"] > 0
    cond4 = cond4_today & cond4_yest
    print(f"[FILTER] 條件4 (今日+昨日皆收漲): {cond4.sum()} 筆")

    # 綜合篩選
    df_result = df[cond1 & cond2 & cond3 & cond4].copy()
    print(f"\n[INFO] ✅ 符合所有條件的股票: {len(df_result)} 筆")

    # ─── 計算外資連續買超天數 ─────────────────────────────────────────────────
    def count_consecutive_buy(row):
        vals = [row.get(c, float("nan")) for c in foreign_cols]
        count = 0
        for v in vals:
            if pd.isna(v):
                break
            if v > 0:
                count += 1
            else:
                break
        return count

    if not df_result.empty:
        df_result["foreign_consecutive_days"] = df_result.apply(count_consecutive_buy, axis=1)
        df_result["pct_change_20d"] = df_result["pct_change_20d"].round(2)

        # 整理輸出欄位
        output_cols = [
            "stock_id", "stock_name", "close_today",
            "change_today", "volume_value",
            "pct_change_20d", "foreign_consecutive_days"
        ]
        df_output = df_result[output_cols].copy()
        df_output.columns = [
            "股票代號", "股票名稱", "今日收盤價",
            "今日漲跌", "成交金額(元)",
            "20日漲幅(%)", "外資連續買超(天)"
        ]

        # 儲存 CSV
        df_output.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
        print(f"[INFO] 結果已儲存至 {OUTPUT_CSV}")

        # 組成 Telegram 訊息
        lines = [
            f"📈 <b>台股篩選結果</b>",
            f"🗓 日期: {today_str}",
            f"✅ 符合條件共 {len(df_result)} 支",
            "─────────────────────",
        ]
        for _, row in df_result.iterrows():
            lines.append(
                f"🔹 <b>{row['stock_name']} ({row['stock_id']})</b>\n"
                f"   收盤: {row['close_today']:.2f}  漲跌: {row['change_today']:+.2f}\n"
                f"   20日漲幅: {row['pct_change_20d']:.2f}%\n"
                f"   外資連買: {int(row['foreign_consecutive_days'])} 天"
            )
        message = "\n".join(lines)

    else:
        # 無符合標的
        df_output = pd.DataFrame(columns=[
            "股票代號", "股票名稱", "今日收盤價",
            "今日漲跌", "成交金額(元)",
            "20日漲幅(%)", "外資連續買超(天)"
        ])
        df_output.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
        print("[INFO] 今日無符合條件標的，已儲存空白 CSV。")
        message = (
            f"📭 <b>台股篩選結果</b>\n"
            f"🗓 日期: {today_str}\n"
            f"今日無符合所有篩選條件的標的。"
        )

    print(f"\n[INFO] Telegram 訊息:\n{message}\n")
    send_telegram(message)
    print("[INFO] 篩選完成！")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        today_str = datetime.today().strftime("%Y-%m-%d")
        err_msg = f"❌ [{today_str}] 台股篩選腳本發生未預期錯誤: {e}"
        print(f"[ERROR] {err_msg}")
        import traceback
        traceback.print_exc()
        send_telegram(err_msg)
