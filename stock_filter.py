import os
import re
import sys
import traceback
from datetime import datetime, timedelta
import requests
import pandas as pd

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
OUTPUT_CSV = "result.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

session = requests.Session()
session.headers.update(HEADERS)


def send_telegram(message: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] Telegram token/chat_id 未設定，略過通知")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        resp = session.post(url, json=payload, timeout=20)
        print(f"[INFO] Telegram status={resp.status_code}")
        resp.raise_for_status()
    except Exception as e:
        print(f"[WARN] Telegram 發送失敗: {e}")


def clean_num(x):
    if pd.isna(x):
        return pd.NA
    s = str(x).strip()
    s = s.replace(",", "").replace(" ", "")
    s = s.replace("－", "-").replace("—", "-").replace("–", "-")
    s = s.replace("+", "")
    s = s.replace("%", "")
    s = re.sub(r"[^\d\.\-]", "", s)
    if s in {"", "-", "."}:
        return pd.NA
    try:
        return float(s)
    except:
        return pd.NA


def is_numeric_stock_id(s):
    return bool(re.fullmatch(r"\d{4}", str(s).strip()))


def get_recent_dates(days=40):
    base = datetime.now()
    dates = []
    d = base
    while len(dates) < days:
        if d.weekday() < 5:
            dates.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return dates


def fetch_daily_market(date_str: str) -> pd.DataFrame:
    """
    抓上市個股日資料（成交金額、收盤價、漲跌等）
    優先用 TWSE 公開日資料端點，並兼容欄位變動。
    """
    urls = [
        f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={date_str}&type=ALLBUT0999&response=json",
        f"https://www.twse.com.tw/exchangeReport/MI_INDEX?date={date_str}&response=json",
    ]

    for url in urls:
        try:
            print(f"[INFO] 抓日資料: {url}")
            resp = session.get(url, timeout=30)
            print(f"[DEBUG] market status={resp.status_code}")
            resp.raise_for_status()
            data = resp.json()
            print(f"[DEBUG] market keys={list(data.keys())}")

            if data.get("stat") not in {"OK", "ok", "Ok"}:
                print(f"[WARN] {date_str} market stat={data.get('stat')}")
                continue

            rows = None
            fields = None

            for kf, kd in [
                ("fields9", "data9"),
                ("fields8", "data8"),
                ("fields", "data"),
            ]:
                if data.get(kf) and data.get(kd):
                    fields = data.get(kf)
                    rows = data.get(kd)
                    break

            if not fields or not rows:
                print(f"[WARN] {date_str} 找不到資料表格")
                continue

            print(f"[DEBUG] market fields={fields[:10]}")
            df = pd.DataFrame(rows, columns=fields)

            colmap = {}
            for c in df.columns:
                if "證券代號" in c or c in ["股票代號", "代號", "證券代號"]:
                    colmap[c] = "stock_id"
                elif "證券名稱" in c or c in ["股票名稱", "名稱"]:
                    colmap[c] = "stock_name"
                elif "收盤價" in c or c == "收盤":
                    colmap[c] = "close"
                elif "漲跌" in c and "價差" in c:
                    colmap[c] = "change"
                elif "漲跌價差" in c:
                    colmap[c] = "change"
                elif "成交金額" in c:
                    colmap[c] = "turnover"

            df = df.rename(columns=colmap)

            required = ["stock_id", "stock_name", "close", "change", "turnover"]
            if not all(c in df.columns for c in required):
                print(f"[WARN] {date_str} 欄位不足: {df.columns.tolist()}")
                continue

            df = df[df["stock_id"].apply(is_numeric_stock_id)].copy()
            for c in ["close", "change", "turnover"]:
                df[c] = df[c].apply(clean_num)

            df = df.dropna(subset=["close", "change", "turnover"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df["change"] = pd.to_numeric(df["change"], errors="coerce")
            df["turnover"] = pd.to_numeric(df["turnover"], errors="coerce")
            df = df.dropna(subset=["close", "change", "turnover"])

            print(f"[INFO] {date_str} market rows={len(df)}")
            return df[["stock_id", "stock_name", "close", "change", "turnover"]].copy()

        except Exception as e:
            print(f"[WARN] market fetch failed {date_str}: {e}")

    return pd.DataFrame()


def fetch_foreign_daily(date_str: str) -> pd.DataFrame:
    """
    抓外資每日淨買超，回傳 [stock_id, foreign_net]
    """
    urls = [
        f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_str}&selectType=ALLBUT0999&response=json",
        f"https://www.twse.com.tw/fund/T86?date={date_str}&selectType=ALLBUT0999&response=json",
    ]

    for url in urls:
        try:
            print(f"[INFO] 抓外資資料: {url}")
            resp = session.get(url, timeout=30)
            print(f"[DEBUG] foreign status={resp.status_code}")
            resp.raise_for_status()
            data = resp.json()
            print(f"[DEBUG] foreign keys={list(data.keys())}")

            if data.get("stat") not in {"OK", "ok", "Ok"}:
                print(f"[WARN] {date_str} foreign stat={data.get('stat')}")
                continue

            rows = data.get("data", [])
            fields = data.get("fields", [])
            if not rows or not fields:
                print(f"[WARN] {date_str} 外資資料無 rows/fields")
                continue

            print(f"[DEBUG] foreign fields={fields[:10]}")
            df = pd.DataFrame(rows, columns=fields)

            stock_col = None
            net_col = None

            for c in df.columns:
                if "證券代號" in c or c in ["證券代號", "代號"]:
                    stock_col = c
                if "外資" in c and "買賣超" in c:
                    net_col = c
                if "買賣超股數" in c and "外資" in c:
                    net_col = c

            if stock_col is None:
                print(f"[WARN] {date_str} 找不到股票代號欄位")
                continue

            if net_col is None:
                buy_col = next((c for c in df.columns if "買進" in c and "外資" in c), None)
                sell_col = next((c for c in df.columns if "賣出" in c and "外資" in c), None)
                if buy_col and sell_col:
                    df["foreign_net"] = df[buy_col].apply(clean_num) - df[sell_col].apply(clean_num)
                    net_col = "foreign_net"
                else:
                    print(f"[WARN] {date_str} 找不到外資淨買超欄位")
                    continue

            out = pd.DataFrame()
            out["stock_id"] = df[stock_col].astype(str).str.strip()
            out["foreign_net"] = df[net_col].apply(clean_num)
            out = out[out["stock_id"].apply(is_numeric_stock_id)]
            out["foreign_net"] = pd.to_numeric(out["foreign_net"], errors="coerce")
            out = out.dropna(subset=["foreign_net"])

            print(f"[INFO] {date_str} foreign rows={len(out)}")
            return out[["stock_id", "foreign_net"]].copy()

        except Exception as e:
            print(f"[WARN] foreign fetch failed {date_str}: {e}")

    return pd.DataFrame()


def get_latest_valid_trading_dates():
    dates = get_recent_dates(40)
    market_cache = {}

    valid_dates = []
    for d in dates:
        df = fetch_daily_market(d)
        if not df.empty:
            valid_dates.append(d)
            market_cache[d] = df
        if len(valid_dates) >= 25:
            break

    return valid_dates, market_cache


def foreign_consecutive_count(series):
    cnt = 0
    for v in series:
        if pd.isna(v):
            break
        if v > 0:
            cnt += 1
        else:
            break
    return cnt


def main():
    run_date = datetime.now().strftime("%Y-%m-%d")
    print("=" * 70)
    print(f"[INFO] stock_filter start: {run_date}")
    print("=" * 70)

    try:
        valid_dates, market_cache = get_latest_valid_trading_dates()
        print(f"[INFO] valid trading dates={valid_dates[:10]}")
        if len(valid_dates) < 2:
            msg = f"❌ {run_date} 無法取得足夠交易日資料。"
            print(msg)
            pd.DataFrame().to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
            send_telegram(msg)
            return

        today_date = valid_dates[0]
        yesterday_date = valid_dates[1]
        date_20d_ago = valid_dates[20] if len(valid_dates) > 20 else None
        if not date_20d_ago:
            msg = f"❌ {run_date} 無法取得 20 個交易日前資料。"
            print(msg)
            pd.DataFrame().to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
            send_telegram(msg)
            return

        print(f"[INFO] today={today_date}, yesterday={yesterday_date}, 20d_ago={date_20d_ago}")

        df_today = market_cache.get(today_date, pd.DataFrame())
        df_yday = market_cache.get(yesterday_date, fetch_daily_market(yesterday_date))
        df_20d = market_cache.get(date_20d_ago, fetch_daily_market(date_20d_ago))

        if df_today.empty or df_20d.empty:
            msg = f"❌ {run_date} 今日或 20 日前資料取得失敗。"
            print(msg)
            pd.DataFrame().to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
            send_telegram(msg)
            return

        foreign_dates = valid_dates[:5]
        foreign_dfs = []
        for d in foreign_dates:
            df_f = fetch_foreign_daily(d)
            if not df_f.empty:
                df_f = df_f.rename(columns={"foreign_net": f"foreign_{d}"})
                foreign_dfs.append(df_f.set_index("stock_id"))
        if not foreign_dfs:
            msg = f"❌ {run_date} 外資資料全部抓取失敗。"
            print(msg)
            pd.DataFrame().to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
            send_telegram(msg)
            return

        df_foreign = pd.concat(foreign_dfs, axis=1).reset_index()
        print(f"[INFO] foreign merged rows={len(df_foreign)}")

        df = df_today.rename(columns={"close": "close_today", "change": "change_today", "turnover": "turnover_today"}).copy()
        df = df.merge(
            df_yday[["stock_id", "change"]].rename(columns={"change": "change_yesterday"}),
            on="stock_id",
            how="left",
        )
        df = df.merge(
            df_20d[["stock_id", "close"]].rename(columns={"close": "close_20d"}),
            on="stock_id",
            how="left",
        )
        df = df.merge(df_foreign, on="stock_id", how="left")

        df["pct_20d"] = (df["close_today"] - df["close_20d"]) / df["close_20d"] * 100
        foreign_cols = [c for c in df.columns if c.startswith("foreign_")]
        print(f"[INFO] foreign cols={foreign_cols}")

        def check_foreign(row):
            vals = [row.get(c, pd.NA) for c in foreign_cols]
            cnt = foreign_consecutive_count(vals)
            return 3 <= cnt <= 5, cnt

        foreign_check = df.apply(check_foreign, axis=1, result_type="expand")
        df["foreign_ok"] = foreign_check[0]
        df["foreign_consecutive_days"] = foreign_check[1]

        cond1 = df["turnover_today"] > 1e8
        cond2 = df["pct_20d"] > 15
        cond3 = df["foreign_ok"] == True
        cond4 = (df["change_today"] > 0) & (df["change_yesterday"] > 0)

        print(f"[FILTER] turnover > 1e8: {int(cond1.sum())}")
        print(f"[FILTER] pct_20d > 15: {int(cond2.sum())}")
        print(f"[FILTER] foreign 3~5 days: {int(cond3.sum())}")
        print(f"[FILTER] up today & yesterday: {int(cond4.sum())}")

        result = df[cond1 & cond2 & cond3 & cond4].copy()
        print(f"[INFO] matched rows={len(result)}")

        if result.empty:
            out = pd.DataFrame(columns=[
                "日期", "股票名稱", "代號", "今日收盤價", "20日漲幅(%)", "成交金額(元)", "外資連買天數", "法人籌碼狀態"
            ])
            out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
            msg = f"📭 {run_date} 無符合條件的標的。"
            print(msg)
            send_telegram(msg)
            return

        result["法人籌碼狀態"] = result["foreign_consecutive_days"].apply(lambda x: f"外資連續淨買超 {int(x)} 天")
        result["20日漲幅(%)"] = result["pct_20d"].round(2)
        result["今日收盤價"] = result["close_today"].round(2)
        result["成交金額(元)"] = result["turnover_today"].round(0).astype("Int64")
        result["日期"] = run_date

        out = result[[
            "日期", "stock_name", "stock_id", "今日收盤價",
            "20日漲幅(%)", "成交金額(元)", "foreign_consecutive_days", "法人籌碼狀態"
        ]].copy()
        out.columns = ["日期", "股票名稱", "代號", "今日收盤價", "20日漲幅(%)", "成交金額(元)", "外資連買天數", "法人籌碼狀態"]
        out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
        print(f"[INFO] saved {OUTPUT_CSV}")

        lines = [f"📈 <b>台股篩選結果</b>", f"日期：{run_date}", f"符合條件：{len(result)} 檔", ""]
        for _, r in result.iterrows():
            lines.append(
                f"• <b>{r['stock_name']}</b> ({r['stock_id']})\n"
                f"  漲幅：{r['20日漲幅(%)']:.2f}%\n"
                f"  法人籌碼：{r['法人籌碼狀態']}\n"
                f"  收盤價：{r['close_today']:.2f}，成交金額：{int(r['turnover_today']):,}"
            )
        msg = "\n".join(lines)
        send_telegram(msg)
        print("[INFO] done")

    except Exception as e:
        print(f"[ERROR] unexpected: {e}")
        traceback.print_exc()
        try:
            pd.DataFrame().to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
        except:
            pass
        send_telegram(f"❌ {run_date} 篩選腳本執行失敗：{e}")


if __name__ == "__main__":
    main()
