"""Data feeds: ThetaData (QQQ options, your key) and Yahoo (NQ=F / QQQ minute bars)."""
import os, json, time, inspect, datetime as dt, urllib.request, http.cookiejar
from zoneinfo import ZoneInfo
import pandas as pd

ET = ZoneInfo("America/New_York")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

class Yahoo:
    def __init__(self):
        self.op, self.crumb, self.t = None, None, 0
    def _session(self):
        if self.op and time.time() - self.t < 1800: return
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        op.addheaders = [("User-Agent", UA)]
        try: op.open("https://fc.yahoo.com", timeout=15)
        except Exception: pass
        self.crumb = op.open("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=15).read().decode()
        self.op, self.t = op, time.time()
    def bars(self, symbol, interval="1m", rng="1d"):
        self._session()
        sym = urllib.request.quote(symbol)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval={interval}&range={rng}&includePrePost=true&crumb={self.crumb}"
        try:
            raw = self.op.open(url, timeout=20).read()
        except Exception:
            self.op = None; self._session(); raw = self.op.open(url, timeout=20).read()
        return parse_chart(json.loads(raw))

def parse_chart(js):
    r = js["chart"]["result"][0]; q = r["indicators"]["quote"][0]; out = []
    for i, t in enumerate(r.get("timestamp") or []):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c): continue
        out.append((dt.datetime.fromtimestamp(t, ET).replace(tzinfo=None), o, h, l, c))
    return out

class Theta:
    def __init__(self, key_getter):
        self.key_getter, self.client, self.key = key_getter, None, None
    def _c(self):
        key = self.key_getter()
        if not key: raise RuntimeError("no ThetaData key set")
        if self.client is None or key != self.key:
            os.environ["THETADATA_API_KEY"] = key
            from thetadata import ThetaClient
            kw = {"dataframe_type": "pandas"}
            if "api_key" in inspect.signature(ThetaClient).parameters: kw["api_key"] = key
            self.client, self.key = ThetaClient(**kw), key
        return self.client
    def _df(self, fn, **kw):
        df = getattr(self._c(), fn)(**kw)
        if hasattr(df, "to_pandas"): df = df.to_pandas()
        return df
    def oi(self, day):  return self._df("option_history_open_interest", symbol="QQQ", expiration="*", date=day, max_dte=8)
    def oi_snapshot(self):
        """Today's open interest (posted ~6:30 ET) from the snapshot endpoint; the history endpoint only has it after the day ends."""
        return self._df("option_snapshot_open_interest", symbol="QQQ", expiration="*", max_dte=8)
    def eod(self, day): return self._df("option_history_eod", symbol="QQQ", expiration="*", start_date=day, end_date=day, max_dte=9)
