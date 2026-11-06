"""Backtest: do QQQ strikes that NDX/NDXP agree with hold better than QQQ-only strikes on NQ?
Runs on GitHub Actions (has ThetaData + Yahoo access). Writes results/backtest.json."""
import os, sys, json, random, datetime as dt
from pathlib import Path
import numpy as np, pandas as pd, engine, feeds
ROOT = Path(__file__).resolve().parent; OUT = ROOT / "results"; OUT.mkdir(exist_ok=True)
cfg = json.load(open(ROOT / "config.json"))
theta = feeds.Theta(lambda: os.environ.get("THETADATA_API_KEY", ""))
def df(fn, **kw):
    try:
        d = theta._df(fn, **kw); return d if d is not None and len(d) else None
    except Exception as e:
        print(f"  {fn} {kw.get('symbol')} {kw.get('date') or kw.get('start_date')}: {type(e).__name__}: {str(e)[:90]}"); return None
def prev_wd(d):
    d -= dt.timedelta(days=1)
    while d.weekday() >= 5: d -= dt.timedelta(days=1)
    return d
def parity(eod):
    e = eod[eod.expiration.astype(str) == sorted(eod.expiration.astype(str).unique())[0]]
    c_ = e.right.astype(str).str.upper().str.startswith("C"); c = e[c_].set_index("strike"); p = e[~c_].set_index("strike")
    d = ((c.bid + c.ask) / 2 - (p.bid + p.ask) / 2).dropna(); k = d.abs().idxmin(); return float(k + d.loc[k])
def levels(sym, day, P, spot, mdte, top=8, win=.03):
    eod = df("option_history_eod", symbol=sym, expiration="*", start_date=P, end_date=P, max_dte=mdte)
    oi = df("option_history_open_interest", symbol=sym, expiration="*", date=day, max_dte=mdte)
    poi = df("option_history_open_interest", symbol=sym, expiration="*", date=P, max_dte=mdte)
    if eod is None or oi is None: return None, None
    if poi is None: poi = oi
    prevC = parity(eod)
    r = engine.compute(day, P, oi, eod, poi, spot or prevC, prevC, dict(cfg, top_n=top, window_pct=win, dte_max=mdte))
    out = {}
    for fam, xs in r["fam"].items():
        if fam == "gamma_flip": continue
        for x in xs: out.setdefault(round(float(x["k"]), 2), set()).add(fam)
    return out, prevC

Y = feeds.Yahoo()
nq = Y.bars("NQ=F", "5m", "60d"); qq = Y.bars("QQQ", "5m", "60d"); nd = Y.bars("^NDX", "5m", "60d")
days = sorted({b[0].date() for b in nq if b[0].weekday() < 5})
today = dt.datetime.now().date()
days = [d for d in days if d < today][-int(os.environ.get("BT_DAYS", "35")):]
rng = random.Random(11); EV = []; DAYS = []
for day in days:
    P = prev_wd(day)
    rth = lambda B: [b for b in B if b[0].date() == day and dt.time(9, 30) <= b[0].time() < dt.time(16)]
    N, Q, X = rth(nq), rth(qq), rth(nd)
    if len(N) < 70 or not Q or not X: print(day, "skip (bars)"); continue
    rQ, rX = N[0][1] / Q[0][1], N[0][1] / X[0][1]          # NQ per QQQ $, NQ per NDX pt (at the open)
    q, _ = levels("QQQ", day, P, Q[0][1], 7)
    nx, _ = levels("NDXP", day, P, X[0][1], 9)
    nm, _ = levels("NDX", day, P, X[0][1], 35)
    if q is None or (nx is None and nm is None): print(day, "skip (options)"); continue
    ndx = {}
    for src in (nx or {}), (nm or {}):
        for k, f in src.items(): ndx.setdefault(k, set()).update(f)
    ndx_nq = [k * rX for k in ndx]
    H = np.array([b[2] for b in N]); L = np.array([b[3] for b in N]); C = np.array([b[4] for b in N])
    lv = []
    for k, f in q.items():
        p = k * rQ; nonEM = f - {"em_bands"}
        agree = any(abs(p - x) <= 0.5 * rQ for x in ndx_nq)
        lv.append(("Q", p, len(nonEM) >= 2, agree))
    for x in ndx_nq: lv.append(("N", x, False, False))
    for _ in range(len(q) * 3): lv.append(("R", rng.uniform(L.min() - 50, H.max() + 50), False, False))
    DAYS.append(str(day))
    for kind, p, star, agree in lv:
        start = 0
        for rep in range(2):
            i = next((j for j in range(start, len(N)) if L[j] - 1 <= p <= H[j] + 1 and (j == 0 or not (L[j - 1] - 1 <= p <= H[j - 1] + 1))), None)
            if i is None or i == 0: break
            side = 1 if C[i - 1] > p else -1
            fav = ((H[i:i + 13] - p) if side == 1 else (p - L[i:i + 13])).tolist(); adv = ((p - L[i:i + 13]) if side == 1 else (H[i:i + 13] - p)).tolist()
            EV.append(dict(day=str(day), kind=kind, star=star, agree=agree, side=side, p=p, c=float(C[i]), fav=fav, adv=adv))
            start = i + 1
    print(day, "QQQ", len(q), "NDX", len(ndx), "agree", sum(1 for l in lv if l[3]), "events", len(EV))

def confirm(e, X=10, T=40):
    d = (e["c"] - e["p"]) * e["side"]
    if d < 0: return None
    stop = d + X; mae = 0.0
    for f, a in zip(e["fav"][1:], e["adv"][1:]):
        fr, ar = f - d, a + d
        if ar >= stop: return -stop, stop
        mae = max(mae, ar)
        if fr >= T: return T, mae
    return (e["fav"][-1] - e["adv"][-1]) / 2 - d, mae
rows = []
for e in EV:
    r = confirm(e)
    if r: rows.append(dict(day=e["day"], kind=e["kind"], star=e["star"], agree=e["agree"], res=r[0], mae=r[1]))
D = pd.DataFrame(rows)
D.to_csv(OUT / "trades.csv", index=False)
groups = {"QQQ all": (D.kind == "Q"), "QQQ ★ (2+ layers)": (D.kind == "Q") & D.star, "QQQ + NDX agree": (D.kind == "Q") & D.agree,
          "QQQ ★ without NDX": (D.kind == "Q") & D.star & ~D.agree, "QQQ ★ with NDX": (D.kind == "Q") & D.star & D.agree,
          "NDX/NDXP levels": (D.kind == "N"), "Random lines": (D.kind == "R")}
res = {"days": DAYS, "rule": "touch, 5m close back on the approach side, enter at close, stop 10 past level, target 40, 60 min", "groups": {}}
bs_rng = np.random.default_rng(3); ud = np.array(sorted(D.day.unique()))
def boot(mask_a, mask_b):
    out = []
    for _ in range(3000):
        pick = bs_rng.choice(ud, len(ud)); s = pd.concat([D[D.day == d] for d in pick])
        a = s[mask_a(s)].res; b = s[mask_b(s)].res
        if len(a) and len(b): out.append(a.mean() - b.mean())
    o = np.array(out); return [round(float(np.percentile(o, 5)), 2), round(float(np.percentile(o, 95)), 2), round(float((o <= 0).mean()), 3)]
for g, m in groups.items():
    s = D[m]
    res["groups"][g] = {"n": int(len(s)), "days": int(s.day.nunique()), "win": round(float((s.res > 0).mean() * 100), 1) if len(s) else None,
                        "exp": round(float(s.res.mean()), 2) if len(s) else None, "mae_med": round(float(s.mae.median()), 1) if len(s) else None}
res["edge_vs_random"] = {
    "QQQ all": boot(lambda s: s.kind == "Q", lambda s: s.kind == "R"),
    "QQQ + NDX agree": boot(lambda s: (s.kind == "Q") & s.agree, lambda s: s.kind == "R"),
    "NDX/NDXP levels": boot(lambda s: s.kind == "N", lambda s: s.kind == "R")}
res["ndx_minus_noNdx_stars"] = boot(lambda s: (s.kind == "Q") & s.star & s.agree, lambda s: (s.kind == "Q") & s.star & ~s.agree)
(OUT / "backtest.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
