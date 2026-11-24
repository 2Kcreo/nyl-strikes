"""Test 5: do IV walls rebuilt during the day (10:30 / 11:30, research/ivintra) hold better than the morning walls?
Touches are counted only after the rebuild time, for the morning walls, the fresh walls and random lines alike.
Same hold / fade / break rules as stack_test2.py.
"""
import json, random
from pathlib import Path
import numpy as np, pandas as pd
import stack_test2 as T2
from stack_test import walls

R = Path(__file__).resolve().parent / "research"
rng = random.Random(21)
T2.FADE.clear(); T2.BREAK.clear()
days = 0
for f in sorted((R / "ivintra").glob("20*.json")):
    day = f.stem
    qf = R / "ivlong" / f"{day}.json"
    if not qf.exists(): continue
    j = json.loads(qf.read_text()); it = json.loads(f.read_text())
    px = np.array([np.nan if x is None else x for x in j["path"]], float)
    if (~np.isnan(px)).sum() < 300: continue
    px = pd.Series(px).ffill().bfill().to_numpy()
    S = j["S"]; u = S * 0.00037; days += 1
    flip = j["flip"][0] if j["flip"] else None
    regime = "unknown" if flip is None else ("long gamma" if S >= flip else "short gamma")
    morning = walls(j["cand"], j["cand_cols"], S, j["pc_all"])
    lo, hi = px.min(), px.max()
    for name, t in it["times"].items():
        m = t["m"]
        fresh = walls(t["cand"], it["cand_cols"], t["S"], t["pc_all"])
        G = {f"Morning walls (after {name})": [w[0] for w in morning if w[3] <= 12],
             f"Morning strong 40+ (after {name})": [w[0] for w in morning if w[3] <= 12 and w[2] >= 40],
             f"{name} walls": [w[0] for w in fresh if w[3] <= 12],
             f"{name} strong 40+": [w[0] for w in fresh if w[3] <= 12 and w[2] >= 40],
             f"{name} walls that are new (not in morning list)": [w[0] for w in fresh if w[3] <= 12 and not any(abs(w[0] - x[0]) < 0.01 for x in morning if x[3] <= 12)],
             f"Random (after {name})": [rng.uniform(lo - 0.002 * S, hi + 0.002 * S) for _ in range(30)]}
        for g, levels in G.items():
            for L in set(round(x, 3) for x in levels): T2.run(px, L, u, m, g, day, regime)

F, B = pd.DataFrame(T2.FADE), pd.DataFrame(T2.BREAK)
ud = np.array(sorted(F.day.unique())); bs = np.random.default_rng(5)
fd = {d: F[F.day == d] for d in ud}; bd = {d: B[B.day == d] for d in ud}


def boot(D, g, col, base, B_=400):
    out = []
    for _ in range(B_):
        s = pd.concat([D[d] for d in bs.choice(ud, len(ud))])
        a, r = s[s.g == g][col].dropna(), s[s.g == base][col].dropna()
        if len(a) and len(r): out.append(a.astype(float).mean() - r.astype(float).mean())
    o = np.array(out)
    return round(float(np.median(o)) * (100 if col == "hold" else 1), 2), round(float((o <= 0).mean()), 3)


out = {"days": days, "first": str(ud[0]), "last": str(ud[-1])}
for name in ["10:30", "11:30"]:
    base = f"Random (after {name})"; res = {}
    for g in [f"Morning walls (after {name})", f"Morning strong 40+ (after {name})", f"{name} walls", f"{name} strong 40+",
              f"{name} walls that are new (not in morning list)", base]:
        s, b = F[F.g == g], B[B.g == g]
        row = dict(touches=len(s), hold=round(s.hold.dropna().mean() * 100, 1), fade_pts=round(s.res.dropna().mean(), 2),
                   break_pts=round(b.res.dropna().mean(), 2))
        if g != base:
            row["hold_vs_random"], row["p_hold"] = boot(fd, g, "hold", base)
            row["fade_pts_vs_random"], row["p_fade"] = boot(fd, g, "res", base)
            row["break_pts_vs_random"], row["p_break"] = boot(bd, g, "res", base)
        res[g] = row
    out[name] = res
(R / "stack_test5_results.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
