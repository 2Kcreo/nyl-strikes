"""IV walls (research only, not part of the NYL site).

For each day: which QQQ strikes have big dealer gamma exposure AND options that are priced richer than the
smooth IV curve around them, plus the put/call open-interest ratio at that strike.

No look-ahead: IV comes from the PRIOR day's closing option prices, open interest is the figure posted that
morning (prior close), and spot is the same pre-open QQQ price NYL saved for that day (docs/data/<day>.json).

  score = smile-adjusted gamma exposure (0-2 DTE) x (IV richness vs the smooth curve + curvature bump vs neighbours)
  side  = strike P/C vs the day's overall P/C: >= 1.3x -> support, <= 0.77x -> resistance, otherwise mixed

Usage: python ivwalls.py 2026-09-01 2026-11-18   -> research/ivwalls/<day>.json + all.csv + levels.txt
"""
import os, sys, json, math, datetime as dt
from zoneinfo import ZoneInfo
from pathlib import Path
import numpy as np, pandas as pd
import engine, feeds

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "docs" / "data"
OUT = ROOT / "research" / "ivwalls"; OUT.mkdir(parents=True, exist_ok=True)
theta = feeds.Theta(lambda: os.environ.get("THETADATA_API_KEY", ""))
TOP = 40            # levels per day (up to 20 above price, 20 below), each tagged with its layer 5/8/12/20
WINDOW = 0.03       # +/- 3% around spot
DTE_MAX = 35        # include monthlies
FIT_WIN = 0.06      # strikes used to fit the smooth IV curve (+/- 6%)


def prev_wd(d):
    d -= dt.timedelta(days=1)
    while d.weekday() >= 5: d -= dt.timedelta(days=1)
    return d


def get(kind, d):
    try:
        df = theta.oi(d) if kind == "oi" else theta.eod(d)
        return df if df is not None and len(df) else None
    except Exception as e:
        print(f"  ThetaData {kind} {d}: {type(e).__name__}: {str(e)[:120]}"); return None


def table(day, S, P, eod, oi):
    """Every strike near S with gamma, smile-adjusted gamma, IV richness, curvature, put/call OI. None if no data."""
    prevC = S  # IV solve anchor below uses put-call parity on the prior close
    eod, oi = engine._prep(eod), engine._prep(oi)
    # prior-close forward from parity (nearest expiry)
    e0 = eod[eod.exp == eod.exp.min()]
    c = e0[e0.call].set_index("strike"); p = e0[~e0.call].set_index("strike")
    d = ((c.bid + c.ask) / 2 - (p.bid + p.ask) / 2).dropna()
    if len(d): k = d.abs().idxmin(); prevC = float(k + d.loc[k])

    # 1) IV per (expiry, strike) from prior close, OTM side, decent quotes only
    eod["mid"] = (eod.bid + eod.ask) / 2
    q = eod[(eod.exp > P) & (eod.bid > 0) & (eod.ask > 0) & ((eod.ask - eod.bid) <= 0.35 * eod.mid + 0.02)
            & ((eod.call & (eod.strike >= prevC)) | (~eod.call & (eod.strike <= prevC)))].copy()
    q = q[(q.strike / prevC - 1).abs() <= FIT_WIN]
    tP = dt.datetime.combine(P, dt.time(16, 0))
    q["T"] = [(dt.datetime.combine(x, dt.time(16, 0)) - tP).total_seconds() / (365 * 86400) for x in q.exp]
    q["iv"] = engine.solve_iv(q.mid.to_numpy(float), prevC, q.strike.to_numpy(float), q["T"].to_numpy(float), q.call.to_numpy())
    q = q.dropna(subset=["iv"])

    # 2) smooth curve per expiry (quadratic in log-moneyness) -> richness = iv / fitted - 1
    rows = []
    for (ex, is_call), g in q.groupby(["exp", "call"]):   # puts and calls get their own curve (puts always sit higher)
        if len(g) < 6: continue
        x = np.log(g.strike.to_numpy(float) / prevC); y = g.iv.to_numpy(float)
        cf = np.polyfit(x, y, 2); fit = np.polyval(cf, x)
        fp, fpp = 2 * cf[0] * x + cf[1], np.full(len(x), 2 * cf[0])   # smile slope / bend vs log-moneyness
        # curvature: how far this strike's IV pokes above the straight line between its two neighbours
        g2 = g.sort_values("strike"); xs = np.log(g2.strike.to_numpy(float) / prevC); ys = g2.iv.to_numpy(float)
        cv = np.full(len(ys), np.nan)
        if len(ys) >= 3:
            w = (xs[1:-1] - xs[:-2]) / (xs[2:] - xs[:-2]); lin = ys[:-2] + w * (ys[2:] - ys[:-2])
            cv[1:-1] = ys[1:-1] / lin - 1
        cvm = dict(zip(g2.strike.to_numpy(float), cv))
        ks = g.strike.to_numpy(float)
        rows.append(pd.DataFrame({"exp": ex, "strike": ks, "iv": y, "rich": y / fit - 1, "curv": [cvm.get(k, np.nan) for k in ks], "fp": fp, "fpp": fpp}))
    if not rows: return None
    ivs = pd.concat(rows)
    atm = ivs[ivs.exp == ivs.exp.min()]; atm_iv = float(atm.iloc[(atm.strike - prevC).abs().argmin()].iv)

    # 3) gamma exposure from this morning's open interest, using each strike's own IV
    o = oi[oi.open_interest > 0].copy()
    o["dte"] = [(x - day).days for x in o.exp]
    o = o[(o.dte >= 0) & (o.dte <= DTE_MAX) & ((o.strike / S - 1).abs() <= WINDOW)]
    o = o.merge(ivs, on=["exp", "strike"], how="inner")
    if not len(o): return None
    T0 = dt.datetime.combine(day, dt.time(9, 30))
    T = np.array([max((dt.datetime.combine(x, dt.time(16, 0)) - T0).total_seconds(), 1800) / (365 * 86400) for x in o.exp])
    gam, _, _ = engine.greeks(S, o.strike.to_numpy(float), T, o.iv.to_numpy(float))
    o["gex"] = gam * o.open_interest.to_numpy(float) * 100 * S * S * 0.01
    o["rich_w"] = o.rich * o.gex
    # smile-adjusted ("covariant") gamma: the IV curve moves with price (sticky moneyness), so
    # total gamma = gamma + 2*vanna*dIV/dS + volga*(dIV/dS)^2 + vega*d2IV/dS2
    Kc, sig = o.strike.to_numpy(float), o.iv.to_numpy(float)
    sq = sig * np.sqrt(T); d1 = (np.log(S / Kc) + (engine.R + sig * sig / 2) * T) / sq; d2 = d1 - sq; ph = engine._phi(d1)
    vega = S * ph * np.sqrt(T); vanna = -ph * d2 / sig; volga = vega * d1 * d2 / sig
    sS = -o.fp.to_numpy(float) / S; sSS = (o.fpp.to_numpy(float) + o.fp.to_numpy(float)) / (S * S)
    gtot = gam + 2 * vanna * sS + volga * sS ** 2 + vega * sSS
    o["gex_cov"] = gtot * o.open_interest.to_numpy(float) * 100 * S * S * 0.01
    o["gex_cov_near"] = np.where(o.dte <= 2, o.gex_cov, 0.0)
    o["curv_w"] = o.curv.fillna(0) * o.gex

    by = o.groupby("strike").agg(gex=("gex", "sum"), rich_w=("rich_w", "sum"), curv_w=("curv_w", "sum"), gex_cov=("gex_cov", "sum"), gex_cov_near=("gex_cov_near", "sum"), iv=("iv", "mean"))
    by["rich"] = by.rich_w / by.gex.replace(0, np.nan)
    by["curv"] = by.curv_w / by.gex.replace(0, np.nan)
    by["oi_call"] = o[o.call].groupby("strike").open_interest.sum()
    by["oi_put"] = o[~o.call].groupby("strike").open_interest.sum()
    by = by.fillna(0)
    # score (picked by test, see research/ivwalls/test.json): smile-adjusted gamma from 0-2 DTE options
    # x (IV richness vs the curve + curvature bump vs neighbours)
    by["score"] = by.gex_cov_near.abs() * (by.rich.clip(lower=0) + by.curv.fillna(0).clip(lower=0))
    pc_all = by.oi_put.sum() / max(by.oi_call.sum(), 1)   # the day's overall put/call, so "put-heavy" is relative
    return by, pc_all, atm_iv


def build(day, publish=False):
    js = DATA / f"{day}.json"
    if not js.exists(): print(f"{day}: no NYL file, skipped"); return None
    meta = json.loads(js.read_text()); S = float(meta["spot"])
    P = prev_wd(day); eod = None
    for _ in range(6):
        eod = get("eod", P)
        if eod is not None: break
        P = prev_wd(P)
    oi = get("oi", day)
    if oi is None and day == dt.datetime.now(ZoneInfo("America/New_York")).date():   # today's OI: snapshot (posts ~6:30 ET)
        try:
            oi = theta.oi_snapshot(); oi = oi if oi is not None and len(oi) else None
        except Exception as e: print(f"  oi snapshot: {type(e).__name__}: {e}"); oi = None
        if oi is None: oi = get("oi", P)
    if eod is None or oi is None: print(f"{day}: missing data, skipped"); return None
    t = table(day, S, P, eod, oi)
    if t is None: print(f"{day}: no IV curve / overlap, skipped"); return None
    by, pc_all, atm_iv = t
    (OUT / "cand").mkdir(exist_ok=True)
    by.assign(spot=S, pc_all=pc_all, nq=(meta.get("nq") or {}).get("ratio")).to_csv(OUT / "cand" / f"{day}.csv")   # every strike, for testing variants
    by = by[by.score > 0]
    up, dn = by[by.index >= S].nlargest(TOP // 2, "score"), by[by.index < S].nlargest(TOP // 2, "score")
    up = up.assign(rank=range(1, len(up) + 1)); dn = dn.assign(rank=range(1, len(dn) + 1))
    by = pd.concat([up, dn])
    by["layer"] = [5 if r <= 5 else 8 if r <= 8 else 12 if r <= 12 else 20 for r in by["rank"]]   # like NYL's per-layer
    mx = float(by.score.max()) if len(by) else 1.0
    nq = (meta.get("nq") or {}).get("ratio")

    levels = []
    for k, r in by.sort_index(ascending=False).iterrows():
        pc = (r.oi_put / r.oi_call) if r.oi_call > 0 else float("inf")
        rel = pc / pc_all if pc_all > 0 else pc
        side = "support" if rel >= 1.3 else "resistance" if rel <= 0.77 else "mixed"
        levels.append({"k": float(k), "nq": round(k * nq * 4) / 4 if nq else None, "score": round(r.score / mx * 100), "layer": int(r.layer),
                       "side": side, "pc": None if math.isinf(pc) else round(pc, 2),
                       "iv_pct": round(r.iv / atm_iv * 100), "rich_pct": round(r.rich * 100, 1),
                       "dist": round(k - S, 2)})
    out = {"day": str(day), "spot": S, "spot_src": meta.get("spot_src"), "atm_iv": round(atm_iv, 4),
           "iv_from_close_of": str(P), "pc_all": round(pc_all, 2), "oi": str(day), "nq_ratio": nq, "levels": levels}
    (OUT / f"{day}.json").write_text(json.dumps(out, indent=1))
    if publish:   # served by the website for NYL Sync (not shown on the NYL page)
        pub = ROOT / "docs" / "data" / "ivwalls"; pub.mkdir(parents=True, exist_ok=True)
        (pub / f"{day}.json").write_text(json.dumps(out, indent=1)); (pub / "latest.json").write_text(json.dumps(out, indent=1))
    print(f"{day}: {len(levels)} IV walls, QQQ {S:.2f}, ATM IV {atm_iv:.1%}")
    return out


def main():
    if not os.environ.get("THETADATA_API_KEY"): sys.exit("THETADATA_API_KEY is not set.")
    if sys.argv[1:2] == ["--today"]:   # daily build (GitHub Actions, right after the NYL strikes)
        day = dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else dt.datetime.now(ZoneInfo("America/New_York")).date()
        build(day, publish=True); return
    a, b = dt.date.fromisoformat(sys.argv[1]), dt.date.fromisoformat(sys.argv[2])
    d = a
    while d <= b:
        if d.weekday() < 5:
            try: build(d)
            except Exception as e: print(f"{d}: FAILED {type(e).__name__}: {e}")
        d += dt.timedelta(days=1)
    # combined files
    days = sorted(OUT.glob("20*.json")); rows = []; txt = []
    for f in days:
        j = json.loads(f.read_text())
        for l in j["levels"]:
            rows.append([j["day"], j["spot"], l["k"], l["nq"], l["score"], l["side"], l["pc"], l["iv_pct"], l["rich_pct"], l["dist"]])
        txt.append(f"=== {dt.date.fromisoformat(j['day']).strftime('%a %b %d')} · QQQ {j['spot']} · ATM IV {j['atm_iv']:.1%}\n" +
                   "\n".join(f"{l['k']:g} IVW {l['side']} {l['score']} L{l.get('layer', 20)}" for l in j["levels"]) + "\n")
    pd.DataFrame(rows, columns=["day", "qqq_spot", "strike", "nq_level", "score_0_100", "side", "put_call_oi", "iv_pct_of_atm",
                                "iv_rich_vs_curve_pct", "dist_from_spot"]).to_csv(OUT / "all.csv", index=False)
    (OUT / "levels.txt").write_text("IV WALLS (QQQ strikes) - built pre-open from prior-close IV, morning open interest and pre-open QQQ\nEach line: strike, side (support / resistance / mixed from put/call OI), strength 0-100.\nPaste one day's block into the IV Walls indicator.\n\n" + "\n".join(txt))


if __name__ == "__main__":
    main()
