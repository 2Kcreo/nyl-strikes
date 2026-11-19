"""Long-history data for the IV wall tests (research only).

For each trading day between two dates, saves research/ivlong/<day>.json with:
  - QQQ minute prices 9:30-15:59, rebuilt from 0-2 DTE option quotes (call - put + strike at the
    strikes nearest the money; the plan has no stock data, but option quotes go back years)
  - the opening QQQ price (9:31) used to build that day's levels
  - every strike's IV-wall inputs (ivwalls.table: gamma, smile-adjusted 0-2 DTE gamma, richness, curvature, put/call)
  - NYL strikes (same engine and layers as the site) and the gamma flip
Levels use the prior close's option prices and that morning's open interest only (no look-ahead).

Usage: python ivlong.py 2024-11-18 2025-05-16
"""
import os, sys, json, datetime as dt
from pathlib import Path
import numpy as np, pandas as pd
import engine, feeds, ivwalls

ROOT = Path(__file__).resolve().parent; OUT = ROOT / "research" / "ivlong"; OUT.mkdir(parents=True, exist_ok=True)
theta = feeds.Theta(lambda: os.environ.get("THETADATA_API_KEY", ""))
CFG = json.load(open(ROOT / "config.json"))
LAYERS = {5: (5, .02), 8: (8, .03), 12: (12, .03), 20: (20, .045)}


def call(fn, tries=3, **kw):
    for i in range(tries):
        try:
            df = theta._df(fn, **kw); return df if df is not None and len(df) else None
        except Exception as e:
            msg = str(e)
            if "No data" in msg or "NoDataFound" in type(e).__name__: return None
            print(f"  {fn} try {i + 1}: {type(e).__name__}: {msg[:120]}")
    return None


def minute_path(day):
    q = call("option_history_quote", symbol="QQQ", expiration="*", date=day, interval="1m", max_dte=2, strike_range=12)
    if q is None: return None
    q = q.copy()
    q["exp"] = pd.to_datetime(q.expiration).dt.date
    q = q[q.exp == q.exp.min()]
    q = q[(q.bid > 0) & (q.ask > 0)]
    q["mid"] = (q.bid + q.ask) / 2
    q["call"] = q.right.astype(str).str.upper().str.startswith("C")
    ts = pd.to_datetime(q.timestamp)
    q["m"] = (ts.dt.hour * 60 + ts.dt.minute) - (9 * 60 + 30)
    c = q[q.call].pivot_table(index="m", columns="strike", values="mid")
    p = q[~q.call].pivot_table(index="m", columns="strike", values="mid")
    ks = sorted(set(c.columns) & set(p.columns))
    if not ks: return None
    c, p = c[ks], p[ks]
    diff = (c - p)
    path = [None] * 390
    for m in diff.index:
        if not 0 <= m < 390: continue
        row = diff.loc[m].dropna()
        if not len(row): continue
        near = row.abs().nsmallest(3).index
        path[int(m)] = round(float(np.median([k + row[k] for k in near])), 3)
    return path


def nyl_levels(day, P, oi, eod, poi, S, prevC):
    rows, flip, em = {}, [], None
    for dens, (n, w) in LAYERS.items():
        r = engine.compute(day, P, oi, eod, poi, S, prevC, dict(CFG, top_n=n, window_pct=w))
        for fam, xs in r["fam"].items():
            if fam == "gamma_flip": continue
            for x in xs:
                k = round(float(x["k"])) if fam == "em_bands" else round(float(x["k"]), 2)
                e = rows.setdefault(k, {"tags": set(), "dens": dens}); e["tags"].add(fam); e["dens"] = min(e["dens"], dens)
        if dens == 8:
            em = r["em"]; flip = [round(x["k"], 2) for x in r["fam"].get("gamma_flip", [])]
    return [[k, v["dens"], len(v["tags"] - {"em_bands"})] for k, v in sorted(rows.items())], flip, em


def parity(eod):
    e = eod[eod.expiration.astype(str) == sorted(eod.expiration.astype(str).unique())[0]]
    cl = e.right.astype(str).str.upper().str.startswith("C"); c = e[cl].set_index("strike"); p = e[~cl].set_index("strike")
    d = ((c.bid + c.ask) / 2 - (p.bid + p.ask) / 2).dropna(); k = d.abs().idxmin(); return float(k + d.loc[k])


def one(day):
    f = OUT / f"{day}.json"
    if f.exists(): return "exists"
    oi = call("option_history_open_interest", symbol="QQQ", expiration="*", date=day, max_dte=8)
    if oi is None: return "no OI (holiday?)"
    P = ivwalls.prev_wd(day); eod = None
    for _ in range(6):
        eod = call("option_history_eod", symbol="QQQ", expiration="*", start_date=P, end_date=P, max_dte=9)
        if eod is not None: break
        P = ivwalls.prev_wd(P)
    if eod is None: return "no prior EOD"
    path = minute_path(day)
    if path is None or sum(x is not None for x in path) < 300: return "no minute path"
    S = next(x for x in path[1:] if x is not None)   # 9:31 price
    t = ivwalls.table(day, S, P, eod, oi)
    if t is None: return "no IV table"
    by, pc_all, atm_iv = t
    poi = call("option_history_open_interest", symbol="QQQ", expiration="*", date=P, max_dte=8)
    prevC = parity(eod)
    nyl, flip, em = nyl_levels(day, P, oi, eod, poi if poi is not None else oi, S, prevC)
    cand = [[float(k), round(float(r.gex), 1), round(float(r.gex_cov_near), 1), round(float(r.rich), 5), round(float(r.curv), 5),
             int(r.oi_call), int(r.oi_put)] for k, r in by.iterrows()]
    f.write_text(json.dumps({"day": str(day), "P": str(P), "S": S, "prevC": round(prevC, 3), "atm_iv": round(atm_iv, 4), "em": em,
                             "flip": flip, "pc_all": round(float(pc_all), 4),
                             "cand_cols": ["k", "gex", "gex_cov_near", "rich", "curv", "oi_call", "oi_put"], "cand": cand,
                             "nyl": nyl, "path": path}))
    return f"ok S={S:.2f} cand={len(cand)} nyl={len(nyl)} flip={flip}"


def main():
    a, b = dt.date.fromisoformat(sys.argv[1]), dt.date.fromisoformat(sys.argv[2])
    d = a
    while d <= b:
        if d.weekday() < 5:
            try: print(d, one(d), flush=True)
            except Exception as e: print(d, "FAILED", type(e).__name__, str(e)[:200], flush=True)
        d += dt.timedelta(days=1)


if __name__ == "__main__":
    main()
