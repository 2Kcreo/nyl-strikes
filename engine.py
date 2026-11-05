"""paidgex level engine: pre-open QQQ option level families (same math as paidgex_lab.py)."""
import math, datetime as dt
import numpy as np, pandas as pd
from scipy.special import ndtr

R = 0.04
FAMILIES = ["volume", "stack", "gex_abs", "vex", "chex", "fresh_oi", "gex_walls", "oi_walls", "em_bands", "gamma_flip"]

def _phi(x): return np.exp(-x * x / 2) / math.sqrt(2 * math.pi)

def bs(S, K, T, iv, call):
    sq = iv * np.sqrt(T); d1 = (np.log(S / K) + (R + iv * iv / 2) * T) / sq; d2 = d1 - sq
    c = S * ndtr(d1) - K * np.exp(-R * T) * ndtr(d2)
    return np.where(call, c, c - S + K * np.exp(-R * T))

def solve_iv(px, S, K, T, call):
    lo, hi = np.full_like(px, 0.01), np.full_like(px, 3.0)
    for _ in range(50):
        m = (lo + hi) / 2; up = bs(S, K, T, m, call) < px
        lo, hi = np.where(up, m, lo), np.where(up, hi, m)
    iv = (lo + hi) / 2
    return np.where((iv > 0.05) & (iv < 2.0), iv, np.nan)

def greeks(S, K, T, iv):
    sq = iv * np.sqrt(T); d1 = (np.log(S / K) + (R + iv * iv / 2) * T) / sq; d2 = d1 - sq; p = _phi(d1)
    return p / (S * sq), -p * d2 / iv, -p * (2 * R * T - d2 * sq) / (2 * T * sq)

def _prep(f):
    f = f.copy()
    f["call"] = f.right.astype(str).str.upper().str.startswith("C")
    f["exp"] = pd.to_datetime(f.expiration).dt.date
    return f

def compute(day, P, oi, eod, prev_oi, S, prevC, cfg):
    """day/P: dates. oi: today's morning OI, eod: day P EOD quotes, prev_oi: P's morning OI (or None).
    S: QQQ spot used for the levels (9:30 open once locked). Returns QQQ-price levels per family."""
    oi, eod = _prep(oi), _prep(eod)
    eod["mid"] = np.where((eod.bid > 0) & (eod.ask > 0), (eod.bid + eod.ask) / 2, eod.close)
    tP = dt.datetime.combine(P, dt.time(16, 0))
    e = eod[(eod.exp > P) & (eod.mid > 0) & ((eod.call & (eod.strike >= prevC)) | (~eod.call & (eod.strike <= prevC)))].copy()
    e["T"] = [(dt.datetime.combine(x, dt.time(16, 0)) - tP).total_seconds() / (365 * 86400) for x in e.exp]
    e["iv"] = solve_iv(e.mid.to_numpy(float), prevC, e.strike.to_numpy(float), e["T"].to_numpy(float), e.call.to_numpy())
    ivt = e.dropna(subset=["iv"])[["exp", "strike", "iv"]].sort_values("strike")
    near = ivt[ivt.exp == ivt.exp.min()] if len(ivt) else ivt
    atm_iv = float(near.iloc[(near.strike - prevC).abs().argmin()].iv) if len(near) else 0.2

    o = oi[oi.open_interest > 0].copy()
    o["dte"] = [(x - day).days for x in o.exp]
    o = o[(o.dte >= 0) & (o.dte <= cfg["dte_max"]) & ((o.strike / S - 1).abs() <= cfg["window_pct"])]
    parts = []
    for ex, g in o.groupby("exp"):
        iv_e = ivt[ivt.exp == ex]
        if len(iv_e) == 0: iv_e = ivt[ivt.exp == ivt.exp.min()]
        if len(iv_e) == 0: continue
        parts.append(pd.merge_asof(g.sort_values("strike"), iv_e[["strike", "iv"]].sort_values("strike"), on="strike", direction="nearest"))
    if not parts: raise RuntimeError("no option rows matched implied volatility")
    o = pd.concat(parts).dropna(subset=["iv"])
    T0 = dt.datetime.combine(day, dt.time(9, 30))
    o["T"] = [max((dt.datetime.combine(x, dt.time(16, 0)) - T0).total_seconds(), 1800) / (365 * 86400) for x in o.exp]
    K, T, iv, OI = o.strike.to_numpy(float), o["T"].to_numpy(float), o.iv.to_numpy(float), o.open_interest.to_numpy(float)
    sgn = np.where(o.call, 1.0, -1.0)
    gam, van, cha = greeks(S, K, T, iv)
    o["gex"] = gam * OI * 100 * S * S * 0.01
    o["vex"] = van * OI * 100 * S * 0.01 * sgn
    o["chex"] = cha * OI * 100 * S / 365 * sgn
    o["gnet"] = o.gex * sgn
    by = o.groupby("strike").agg(gex_abs=("gex", "sum"), vex=("vex", "sum"), chex=("chex", "sum"), gnet=("gnet", "sum"))
    by["gex_call"] = o[o.call].groupby("strike").gex.sum(); by["gex_put"] = o[~o.call].groupby("strike").gex.sum()
    by["oi_call"] = o[o.call].groupby("strike").open_interest.sum(); by["oi_put"] = o[~o.call].groupby("strike").open_interest.sum()
    by = by.fillna(0)
    n = cfg["top_n"]
    def top(s, absval=False):
        s2 = s.abs() if absval else s
        s2 = s2[s2 > 0].sort_values(ascending=False)[:n]
        mx = float(s2.iloc[0]) if len(s2) else 1.0
        return [{"k": float(k), "pct": round(float(v) / mx * 100)} for k, v in s2.items()]
    fam = {}
    fam["gex_abs"] = top(by.gex_abs)
    fam["vex"] = top(by.vex, True)
    fam["chex"] = top(by.chex, True)
    fam["gex_walls"] = [{"k": float(by.gex_call.idxmax()), "pct": 100, "note": "call wall"}, {"k": float(by.gex_put.idxmax()), "pct": 100, "note": "put wall"}]
    up, dn = by[by.index >= S], by[by.index <= S]
    fam["oi_walls"] = ([{"k": float(up.oi_call.idxmax()), "pct": 100, "note": "call OI"}] if len(up) else []) + \
                      ([{"k": float(dn.oi_put.idxmax()), "pct": 100, "note": "put OI"}] if len(dn) else [])
    em = S * atm_iv * math.sqrt(1 / 252)
    fam["em_bands"] = [{"k": S + em, "pct": 100, "note": "+1 EM"}, {"k": S - em, "pct": 100, "note": "-1 EM"}]
    grid = np.linspace(S * 0.96, S * 1.04, 161); net = []
    for s_ in grid:
        g_, _, _ = greeks(s_, K, T, iv); net.append(np.sum(g_ * OI * 100 * s_ * s_ * 0.01 * sgn))
    net = np.array(net); cross = np.nonzero(np.diff(np.sign(net)))[0]
    fam["gamma_flip"] = []
    if len(cross):
        j = cross[np.argmin(np.abs(grid[cross] - S))]
        fam["gamma_flip"] = [{"k": float(grid[j] + (grid[j + 1] - grid[j]) * abs(net[j]) / (abs(net[j]) + abs(net[j + 1]))), "pct": 100}]
    fam["fresh_oi"] = []
    if prev_oi is not None and len(prev_oi):
        po = prev_oi.groupby(["expiration", "strike", "right"]).open_interest.sum()
        cur = oi.groupby(["expiration", "strike", "right"]).open_interest.sum()
        dlt = (cur - po.reindex(cur.index).fillna(0)).reset_index()
        dlt = dlt[(dlt.strike / S - 1).abs() <= cfg["window_pct"]].groupby("strike").open_interest.sum()
        fam["fresh_oi"] = top(dlt)
    ev = eod[((eod.strike / S - 1).abs() <= cfg["window_pct"]) & (eod.volume > 0)]
    ev = ev[[(x - P).days <= cfg["dte_max"] + 1 for x in ev.exp]]
    vol = ev.groupby("strike").volume.sum() if len(ev) else pd.Series(dtype=float)
    fam["volume"] = top(vol) if len(ev) else []
    prof = by.join(vol.rename("vol"), how="outer").fillna(0).sort_index()
    profile = [{"k": float(k), "gc": round(float(r.gex_call) / 1e6, 2), "gp": round(float(r.gex_put) / 1e6, 2), "gnet": round(float(r.gnet) / 1e6, 2),
                "vex": round(float(r.vex) / 1e6, 2), "chex": round(float(r.chex) / 1e6, 2), "oc": int(r.oi_call), "op": int(r.oi_put), "vol": int(r.vol)}
               for k, r in prof.iterrows() if abs(k / S - 1) <= cfg["window_pct"]]
    return {"fam": fam, "atm_iv": atm_iv, "em": em, "S": S, "prevC": prevC, "profile": profile}

def stack(fam_nq, pts):
    allv = sorted((x["p"], k) for k, xs in fam_nq.items() if k != "stack" for x in xs)
    out, cur = [], []
    def flush():
        ks = sorted({c[1] for c in cur})
        if len(ks) >= 2: out.append({"p": float(np.mean([c[0] for c in cur])), "pct": min(100, 40 + 20 * len(ks)), "note": "+".join(ks)})
    for v, k in allv:
        if cur and v - cur[-1][0] > pts: flush(); cur = []
        cur.append((v, k))
    if cur: flush()
    return out
