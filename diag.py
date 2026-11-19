import os, inspect, feeds
t = feeds.Theta(lambda: os.environ.get("THETADATA_API_KEY", ""))
c = t._c()
names = [n for n in dir(c) if n.startswith(("stock_", "index_")) and "history" in n]
print("methods:", names)
for n in ("stock_history_ohlc", "option_history_eod", "option_history_open_interest", "option_history_greeks_first_order"):
    if hasattr(c, n): print(n, inspect.signature(getattr(c, n)))
tests = [
 ("stock_history_ohlc", dict(symbol="QQQ", date="2026-11-17", interval="1m")),
 ("stock_history_ohlc", dict(symbol="QQQ", start_date="2026-11-17", end_date="2026-11-17", interval="1m")),
 ("stock_history_ohlc", dict(symbol="QQQ", date="2024-11-19", interval="1m")),
 ("stock_history_ohlc", dict(symbol="QQQ", start_date="2024-11-19", end_date="2024-11-19", interval="1m")),
 ("stock_history_eod", dict(symbol="QQQ", start_date="2024-11-18", end_date="2024-11-19")),
 ("option_history_eod", dict(symbol="QQQ", expiration="*", start_date="2024-11-18", end_date="2024-11-18", max_dte=9)),
 ("option_history_open_interest", dict(symbol="QQQ", expiration="*", date="2024-11-19", max_dte=8)),
 ("option_history_eod", dict(symbol="QQQ", expiration="*", start_date="2023-11-17", end_date="2023-11-17", max_dte=9)),
]
for fn, kw in tests:
    try:
        df = t._df(fn, **kw)
        print("OK", fn, kw, None if df is None else len(df)); 
        if df is not None and len(df): print(df.head(3).to_string()[:600])
    except Exception as e: print("ERR", fn, kw, type(e).__name__, str(e)[:200])
