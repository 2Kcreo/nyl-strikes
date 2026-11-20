"""Long-history tests of IV walls vs NYL vs random lines on QQQ minute prices (research/ivlong/*.json).

Units: "u" = 0.037% of the day's QQQ price ~= 10 NQ points at NQ 27,000. Results are shown in NQ points.
  touch  = minute price within 0.25u of the level, or crosses it between two minutes (up to 2 fresh touches per level)
  hold   = within 30 min price gets 15 NQ pts back the way it came before 15 pts through
  trade  = enter at the touch, stop 10 pts past the level, target 40, exit after 60 min
  magnet = for levels 0.1%-1.5% from the 9:31 price: does price reach it by the close, vs a mirror line
           the same distance on the other side; stall = minutes spent within 5 pts of it in the hour after
Groups: IVW strong (40+), IVW all, NYL 12/layer, Both (strong IVW on an NYL strike), Random.
Splits: gamma regime (9:31 price above/below the gamma flip), time of day, year 1 vs year 2.
"""
import json, random, sys
from pathlib import Path
import numpy as np, pandas as pd

D = Path(__file__).resolve().parent / "research" / "ivlong"
rng = random.Random(5)
EV, MG = [], []
files = sorted(D.glob("20*.json"))
for f in files:
    j = json.loads(f.read_text()); day = j["day"]; S = j["S"]; path = j["path"]
    px = np.array([np.nan if x is None else x for x in path], float)
    ok = ~np.isnan(px)
    if ok.sum() < 300: continue
    px = pd.Series(px).ffill().bfill().to_numpy()
    u = S * 0.00037
    c = pd.DataFrame(j["cand"], columns=j["cand_cols"]).set_index("k")
    c["score"] = c.gex_cov_near.abs() * (c.rich.clip(lower=0) + c.curv.fillna(0).clip(lower=0))
    c = c[c.score > 0]
    top = pd.concat([c[c.index >= S].nlargest(10, "score"), c[c.index < S].nlargest(10, "score")])
    mx = top.score.max() if len(top) else 1
    strong = set(top[top.score / mx >= 0.4].index)
    ivw_all = set(top.index)
    nyl = {round(k, 2) for k, dens, nt in j["nyl"] if dens <= 12}
    both = {k for k in strong if any(abs(k - n) <= 0.5 for n in nyl)}
    # NDX IV walls (same formula on NDXP options), moved onto QQQ prices with the 9:31 NDX/QQQ ratio
    ndx_strong, ndx_all = set(), set()
    nf = D.parent / "ivlong_ndx" / f"{day}.json"
    if nf.exists():
        n = json.loads(nf.read_text()); conv = S / n["S_ndx"]
        cn = pd.DataFrame(n["cand"], columns=n["cand_cols"]).set_index("k")
        cn["score"] = cn.gex_cov_near.abs() * (cn.rich.clip(lower=0) + cn.curv.fillna(0).clip(lower=0))
        cn = cn[cn.score > 0]; Sn = n["S_ndx"]
        tn = pd.concat([cn[cn.index >= Sn].nlargest(10, "score"), cn[cn.index < Sn].nlargest(10, "score")])
        if len(tn):
            mxn = tn.score.max()
            ndx_strong = {round(k * conv, 3) for k in tn[tn.score / mxn >= 0.4].index}
            ndx_all = {round(k * conv, 3) for k in tn.index}
    tol = 0.0005 * S
    both_iv = {k for k in strong if any(abs(k - n) <= tol for n in ndx_strong)}
    flip = j["flip"][0] if j["flip"] else None
    regime = "unknown" if flip is None else ("long gamma (above flip)" if S >= flip else "short gamma (below flip)")
    year = "year 1 (Nov24-Nov25)" if day < "2025-11-17" else "year 2 (Nov25-Nov26)"
    lo, hi = px.min(), px.max()
    groups = [("IVW strong", strong), ("IVW all", ivw_all), ("NYL 12", nyl), ("Both (IVW strong on NYL)", both),
              ("NYL only (no strong IVW)", nyl - {n for n in nyl if any(abs(n - k) <= 0.5 for k in strong)}),
              ("NDX IVW strong", ndx_strong), ("NDX IVW all", ndx_all), ("QQQ + NDX IVW strong agree", both_iv),
              ("Random", {rng.uniform(lo - 0.002 * S, hi + 0.002 * S) for _ in range(40)})]
    for g, levels in groups:
        for L in levels:
            # ---- touches
            start = 1
            for rep in range(2):
                i = None
                for m in range(start, 390):
                    near = abs(px[m] - L) <= 0.25 * u or (px[m - 1] - L) * (px[m] - L) < 0
                    was = abs(px[m - 1] - L) <= 0.25 * u
                    if near and not was: i = m; break
                if i is None: break
                side = 1 if px[i - 1] > L else -1
                hold = None
                for k in range(i + 1, min(i + 31, 390)):
                    if (px[k] - L) * side >= 1.5 * u: hold = True; break
                    if (px[k] - L) * side <= -1.5 * u: hold = False; break
                res = None
                d = (px[i] - L) * side
                if d >= -0.25 * u:
                    stop, tgt = -(1 * u + d), 4 * u
                    for k in range(i + 1, min(i + 61, 390)):
                        mv = (px[k] - px[i]) * side
                        if mv <= stop: res = stop; break
                        if mv >= tgt: res = tgt; break
                    if res is None: res = (px[min(i + 60, 389)] - px[i]) * side
                    res = res / u * 10
                tod = "first hour" if i < 60 else ("midday 10:30-14:00" if i < 270 else "last 2 hours")
                EV.append(dict(day=day, year=year, g=g, regime=regime, tod=tod, hold=hold, res=res))
                start = i + 1
                # require price to leave before a second touch
                while start < 390 and abs(px[start] - L) <= 1.0 * u: start += 1
            # ---- magnet
            if g == "Random": continue
            dist = abs(L - S) / S
            if 0.001 <= dist <= 0.015:
                for kind, lev in (("level", L), ("mirror", 2 * S - L)):
                    hit = next((m for m in range(1, 390) if (px[m - 1] - lev) * (px[m] - lev) <= 0 or abs(px[m] - lev) <= 0.25 * u), None)
                    stall = None
                    if hit is not None:
                        w = px[hit:hit + 60]; stall = int((np.abs(w - lev) <= 0.5 * u).sum())
                    MG.append(dict(day=day, year=year, g=g, kind=kind, regime=regime, hit=hit is not None, stall=stall))

E = pd.DataFrame(EV); M = pd.DataFrame(MG)
ud = np.array(sorted(E.day.unique())); bs = np.random.default_rng(1)
byday = {d: E[E.day == d] for d in ud}

def st(s):
    h = s.hold.dropna(); t = s.res.dropna()
    return dict(n=int(len(s)), hold=round(h.mean() * 100, 1) if len(h) else None, trades=int(len(t)),
                win=round((t > 0).mean() * 100, 1) if len(t) else None, pts=round(t.mean(), 2) if len(t) else None)

def edge(g, filt=None, B=1000):
    out_h, out_p = [], []
    for _ in range(B):
        s = pd.concat([byday[d] for d in bs.choice(ud, len(ud))])
        if filt is not None: s = s[filt(s)]
        a, r = s[s.g == g], s[s.g == "Random"]
        if len(a.hold.dropna()) and len(r.hold.dropna()):
            out_h.append((a.hold.dropna().mean() - r.hold.dropna().mean()) * 100)
            out_p.append(a.res.dropna().mean() - r.res.dropna().mean())
    h, p = np.array(out_h), np.array(out_p)
    return dict(hold_vs_random=round(float(np.median(h)), 1), hold_chance_no_edge=round(float((h <= 0).mean()), 3),
                pts_vs_random=round(float(np.median(p)), 2), pts_chance_no_edge=round(float((p <= 0).mean()), 3))

G = ["IVW strong", "IVW all", "NDX IVW strong", "NDX IVW all", "QQQ + NDX IVW strong agree", "NYL 12", "Both (IVW strong on NYL)", "NYL only (no strong IVW)", "Random"]
R = {"days": int(len(ud)), "first": str(ud[0]), "last": str(ud[-1]), "overall": {}, "edge": {}, "regime": {}, "time_of_day": {}, "year": {}, "magnet": {}}
for g in G:
    R["overall"][g] = st(E[E.g == g])
    if g != "Random": R["edge"][g] = edge(g)
for rg in ["long gamma (above flip)", "short gamma (below flip)"]:
    R["regime"][rg] = {g: st(E[(E.g == g) & (E.regime == rg)]) for g in G}
    R["regime"][rg]["edge IVW strong"] = edge("IVW strong", lambda s, rg=rg: s.regime == rg, 500)
    R["regime"][rg]["edge NDX IVW strong"] = edge("NDX IVW strong", lambda s, rg=rg: s.regime == rg, 500)
    R["regime"][rg]["edge NYL 12"] = edge("NYL 12", lambda s, rg=rg: s.regime == rg, 500)
for t in ["first hour", "midday 10:30-14:00", "last 2 hours"]:
    R["time_of_day"][t] = {g: st(E[(E.g == g) & (E.tod == t)]) for g in G}
    R["time_of_day"][t]["edge IVW strong"] = edge("IVW strong", lambda s, t=t: s.tod == t, 500)
    R["time_of_day"][t]["edge NDX IVW strong"] = edge("NDX IVW strong", lambda s, t=t: s.tod == t, 500)
for y in sorted(E.year.unique()):
    R["year"][y] = {g: st(E[(E.g == g) & (E.year == y)]) for g in G}
    R["year"][y]["edge IVW strong"] = edge("IVW strong", lambda s, y=y: s.year == y, 500)
    R["year"][y]["edge NYL 12"] = edge("NYL 12", lambda s, y=y: s.year == y, 500)
    R["year"][y]["edge NDX IVW strong"] = edge("NDX IVW strong", lambda s, y=y: s.year == y, 500)
for g in G[:-1]:
    s = M[M.g == g]
    lv, mi = s[s.kind == "level"], s[s.kind == "mirror"]
    R["magnet"][g] = dict(levels=int(len(lv)), reach_pct=round(lv.hit.mean() * 100, 1), mirror_reach_pct=round(mi.hit.mean() * 100, 1),
                          stall_min=round(lv.stall.dropna().mean(), 1), mirror_stall_min=round(mi.stall.dropna().mean(), 1))
out = Path(__file__).resolve().parent / "research" / ("ivlong_results_ndx.json" if (D.parent / "ivlong_ndx").exists() else "ivlong_results.json")
out.write_text(json.dumps(R, indent=1)); print(json.dumps(R, indent=1))
