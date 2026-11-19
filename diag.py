import os, inspect, feeds, datetime as dt
D = dt.date.fromisoformat
t = feeds.Theta(lambda: os.environ.get("THETADATA_API_KEY", ""))
c = t._c()
for n in ("option_history_quote", "option_history_ohlc", "option_history_greeks_first_order", "index_history_ohlc", "index_history_price"):
    if hasattr(c, n): print(n, inspect.signature(getattr(c, n)))
tests = [
 ("option_history_greeks_first_order", dict(symbol="QQQ", expiration=D("2024-11-19"), date=D("2024-11-19"), interval="1m", strike_range=2)),
 ("option_history_quote", dict(symbol="QQQ", expiration=D("2024-11-19"), date=D("2024-11-19"), interval="1m", strike_range=2)),
 ("option_history_ohlc", dict(symbol="QQQ", expiration=D("2024-11-19"), date=D("2024-11-19"), interval="1m", strike_range=2)),
 ("option_history_quote", dict(symbol="QQQ", expiration=D("2023-01-18"), date=D("2023-01-18"), interval="1m", strike_range=2)),
 ("index_history_price", dict(symbol="NDX", date=D("2024-11-19"), interval="1m")),
]
for fn, kw in tests:
    try:
        df = t._df(fn, **kw)
        print("OK", fn, None if df is None else len(df)); print(list(df.columns)); print(df.head(4).to_string()[:900])
    except Exception as e: print("ERR", fn, type(e).__name__, str(e)[:300])
