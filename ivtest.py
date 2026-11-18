"""Test IV wall variants on NQ (Sept-Nov) against random lines and NYL strikes. Writes research/ivwalls/test.json.

Event: NQ 5m bar touches the level (first touch, then a second fresh touch), regular hours only.
  hold  = within the next 30 min price moves 15+ pts back the way it came before it closes 15+ pts through.
  trade = the NYL backtest rule: touch bar closes back on the approach side -> enter at that close,
          stop 10 pts past the level, target 40, exit after 60 min.
"""
import json, random, datetime as dt
from pathlib import Path
import numpy as np, pandas as pd, feeds

ROOT = Path(__file__).resolve().parent; IVD = ROOT / "research" / "ivwalls"; CAND = IVD / "cand"; NYL = ROOT / "docs" / "data"
N_EACH = 10  # per side, per variant

def pick(c, col, S):
    c = c[c[col] > 0]
    return list(c[c.index >= S].nlargest(N_EACH, col).index) + list(c[c.index < S].nlargest(N_EACH, col).index)

def variants(c, S):
    c = c.copy(); r = c.rich.clip(lower=0)
    c["A_gex_x_rich"] = c.gex * r
    c["B_rich_bigGEX"] = np.where(c.gex >= c.gex.median(), r, 0)
    c["C_gex_only"] = c.gex
    c["D_gex_x_1plusrich"] = c.gex * (1 + 5 * c.rich).clip(lower=0)
    c["E_sqrtgex_x_rich"] = np.sqrt(c.gex) * r
    out = {v: pick(c, v, S) for v in ["A_gex_x_rich", "B_rich_bigGEX", "C_gex_only", "D_gex_x_1plusrich", "E_sqrtgex_x_rich"]}
    # strength split + labelled side for the current formula (A)
    a = c[c.A_gex_x_rich > 0].copy(); mx = a.A_gex_x_rich.max()
    pc = (a.oi_put / a.oi_call.replace(0, np.nan)) / a.pc_all
    a["side"] = np.where(pc >= 1.3, "support", np.where(pc <= 0.77, "resistance", "mixed"))
    a["strong"] = a.A_gex_x_rich / mx >= 0.4
    return out, a

Y = feeds.Yahoo()
nq = Y.bars("NQ=F", "5m", "60d"); qq = Y.bars("QQQ", "5m", "60d")
rng = random.Random(7); EV = []
for f in sorted(CAND.glob("20*.csv")):
    day = dt.date.fromisoformat(f.stem)
    rth = lambda B: [b for b in B if b[0].date() == day and dt.time(9, 30) <= b[0].time() < dt.time(16)]
    N, Q = rth(nq), rth(qq)
    if len(N) < 70 or not Q: print(day, "skip (bars)"); continue
    rQ = N[0][1] / Q[0][1]
    c = pd.read_csv(f, index_col=0); S = float(c.spot.iloc[0])
    lv = []
    vs, a = variants(c, S)
    for v, ks in vs.items(): lv += [(v, k, None, None) for k in ks]
    for k, r in a.loc[vs["A_gex_x_rich"]].iterrows(): lv.append(("A_side", k, r.side, bool(r.strong)))
    js = NYL / f"{day}.json"
    if js.exists():
        lv += [("NYL_12", s["k"], None, None) for s in json.loads(js.read_text())["strikes"] if s["dens"] <= 12]
    H = np.array([b[2] for b in N]); L = np.array([b[3] for b in N]); C = np.array([b[4] for b in N])
    lv += [("Random", rng.uniform(L.min() / rQ - 2, H.max() / rQ + 2), None, None) for _ in range(40)]
    for kind, k, side_lbl, strong in lv:
        p = k * rQ; start = 0
        for rep in range(2):
            i = next((j for j in range(start, len(N)) if L[j] - 1 <= p <= H[j] + 1 and (j == 0 or not (L[j - 1] - 1 <= p <= H[j - 1] + 1))), None)
            if i is None or i == 0: break
            side = 1 if C[i - 1] > p else -1   # 1 = came from above (level acting as support)
            fav = ((H[i:i + 13] - p) if side == 1 else (p - L[i:i + 13])); adv = ((p - L[i:i + 13]) if side == 1 else (H[i:i + 13] - p))
            closes = (C[i:i + 7] - p) * side
            hold = None
            for b in range(1, min(7, len(closes))):
                if fav[b] >= 15: hold = True; break
                if closes[b] <= -15: hold = False; break
            d = (C[i] - p) * side; res = None
            if d >= 0:
                stop = d + 10; res = None
                for fv, av in zip(fav[1:], adv[1:]):
                    if av + d >= stop: res = -stop; break
                    if fv - d >= 40: res = 40.0; break
                if res is None: res = float(C[min(i + 12, len(C) - 1)] - C[i]) * side
            EV.append(dict(day=str(day), kind=kind, side=side, lbl=side_lbl, strong=strong, hold=hold, res=res))
            start = i + 1
    print(day, "levels", len(lv), "events", len(EV))

D = pd.DataFrame(EV); D.to_csv(IVD / "test_events.csv", index=False)
bs = np.random.default_rng(3); ud = np.array(sorted(D.day.unique()))
def stats(s):
    h = s.hold.dropna(); t = s.res.dropna()
    return {"touches": int(len(s)), "hold_pct": round(float(h.mean() * 100), 1) if len(h) else None,
            "trades": int(len(t)), "win_pct": round(float((t > 0).mean() * 100), 1) if len(t) else None,
            "pts_per_trade": round(float(t.mean()), 2) if len(t) else None}
def edge(ma):   # bootstrap by day: hold% difference vs random
    out = []
    for _ in range(2000):
        pk = bs.choice(ud, len(ud)); s = pd.concat([D[D.day == d] for d in pk])
        a = s[ma(s)].hold.dropna(); b = s[s.kind == "Random"].hold.dropna()
        if len(a) and len(b): out.append((a.mean() - b.mean()) * 100)
    o = np.array(out); return {"hold_pct_minus_random": round(float(np.median(o)), 1), "range_90": [round(float(np.percentile(o, 5)), 1), round(float(np.percentile(o, 95)), 1)], "chance_no_edge": round(float((o <= 0).mean()), 3)}
res = {"days": len(ud), "groups": {}, "edge": {}}
kinds = ["A_gex_x_rich", "B_rich_bigGEX", "C_gex_only", "D_gex_x_1plusrich", "E_sqrtgex_x_rich", "NYL_12", "Random"]
for k in kinds:
    res["groups"][k] = stats(D[D.kind == k])
    if k != "Random": res["edge"][k] = edge(lambda s, k=k: s.kind == k)
A = D[D.kind == "A_side"]
res["A_split"] = {
    "strong (40+)": stats(A[A.strong == True]), "weak (<40)": stats(A[A.strong == False]),
    "support hit from above": stats(A[(A.lbl == "support") & (A.side == 1)]), "support hit from below": stats(A[(A.lbl == "support") & (A.side == -1)]),
    "resistance hit from below": stats(A[(A.lbl == "resistance") & (A.side == -1)]), "resistance hit from above": stats(A[(A.lbl == "resistance") & (A.side == 1)]),
    "mixed": stats(A[A.lbl == "mixed"])}
(IVD / "test.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
