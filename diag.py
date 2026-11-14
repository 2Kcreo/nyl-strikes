import os, datetime as dt, feeds
Y = feeds.Yahoo()
for sym in ("QQQ", "NQ=F", "^NDX"):
    bs = Y.bars(sym, "5m", "60d")
    print(sym, "bars", len(bs), "first", bs[0][0] if bs else None)
    for day in ("2026-10-14", "2026-10-15", "2026-10-29", "2026-11-13"):
        d = dt.date.fromisoformat(day)
        sel = [b for b in bs if b[0].date() == d and dt.time(9, 0) <= b[0].time() <= dt.time(9, 40)]
        print(" ", day, [(b[0].strftime("%H:%M"), round(b[4], 2)) for b in sel])
    for day in ("2026-10-14", "2026-11-13"):
        d = dt.date.fromisoformat(day)
        print("  first bars of", day, [(b[0].strftime("%H:%M"), round(b[4], 2)) for b in bs if b[0].date() == d][:4])
t = feeds.Theta(lambda: os.environ.get("THETADATA_API_KEY", ""))
for fn, kw in (("stock_history_ohlc", dict(symbol="QQQ", date="2026-10-14", interval="5m")), ("stock_history_ohlc", dict(symbol="QQQ", start_date="2026-10-14", end_date="2026-10-14", interval="5m"))):
    try:
        df = t._df(fn, **kw); print(fn, kw, None if df is None else df.head(3).to_string(), None if df is None else len(df))
        if df is not None: print(df[df.astype(str).apply(lambda r: "09:2" in " ".join(r), axis=1)].head(6).to_string())
    except Exception as e: print(fn, kw, type(e).__name__, str(e)[:200])
