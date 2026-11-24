"""Which stacked / single levels actually hold? 2 years of QQQ minute prices (research/ivlong) with that
morning's NYL list (QQQ, layers), QQQ IV walls and NDX IV walls (research/ivlong_ndx), all known by 9:31.

Members of a stack: NYL QQQ strike (layer <= 12), QQQ IV wall (layer <= 12), NDX IV wall (layer <= 12),
all put on QQQ prices (NDX with the 9:31 NDX/QQQ ratio). NYL NDX strikes are not in the 2-year data.
Units: u = 0.037% of QQQ ~= 10 NQ points.
  touch = minute price within 0.25u of the level, or crosses it (up to 2 fresh touches per level)
  hold  = within 30 min price gets 15 NQ pts back the way it came before 15 pts through
  trade = enter at the touch, stop 10 pts past the level, target 40, exit after 60 min (NQ points)
Every group is compared with random lines on the same days (bootstrap over days).
"""
import json, random
from pathlib import Path
import numpy as np, pandas as pd

R = Path(__file__).resolve().parent / "research"
rng = random.Random(7)


def walls(cand, cols, S, pc_all):
    """Same picking as ivwalls.pick_walls: top 20 by score each side, layer by rank, side by put/call, strength 0-100."""
    c = pd.DataFrame(cand, columns=cols).set_index("k")
    c["score"] = c.gex_cov_near.abs() * (c.rich.clip(lower=0) + c.curv.fillna(0).clip(lower=0))
    c = c[c.score > 0]
    up, dn = c[c.index >= S].nlargest(20, "score"), c[c.index < S].nlargest(20, "score")
    up = up.assign(rank=range(1, len(up) + 1)); dn = dn.assign(rank=range(1, len(dn) + 1))
    c = pd.concat([up, dn])
    if not len(c): return []
    mx = c.score.max(); out = []
    for k, r in c.iterrows():
        pc = r.oi_put / r.oi_call if r.oi_call > 0 else 99
        rel = pc / pc_all if pc_all > 0 else pc
        side = 1 if rel >= 1.3 else -1 if rel <= 0.77 else 0
        layer = 5 if r["rank"] <= 5 else 8 if r["rank"] <= 8 else 12 if r["rank"] <= 12 else 20
        out.append((float(k), side, round(r.score / mx * 100), layer))
    return out


def stacks(items, tol):
    """items: (price, kind, strength, layer, side). Chain items within tol into groups."""
    items = sorted(items); out = []; a = 0
    while a < len(items):
        b = a
        while b + 1 < len(items) and items[b + 1][0] - items[b][0] <= tol: b += 1
        out.append(items[a:b + 1]); a = b + 1
    return out


EV = []
days = 0
for f in sorted((R / "ivlong").glob("20*.json")):
    j = json.loads(f.read_text()); day = j["day"]; S = j["S"]
    px = np.array([np.nan if x is None else x for x in j["path"]], float)
    if (~np.isnan(px)).sum() < 300: continue
    px = pd.Series(px).ffill().bfill().to_numpy()
    nf = R / "ivlong_ndx" / f"{day}.json"
    if not nf.exists(): continue
    n = json.loads(nf.read_text()); conv = S / n["S_ndx"]
    days += 1
    u = S * 0.00037
    flip = j["flip"][0] if j["flip"] else None
    regime = "unknown" if flip is None else ("long gamma" if S >= flip else "short gamma")

    # members: (qqq price, kind, strength, layer, side)
    items = []
    for k, dens, nt in j["nyl"]:
        if dens <= 12: items.append((float(k), "NYL", 0, dens, 9))
    for k, side, sc, layer in walls(j["cand"], j["cand_cols"], S, j["pc_all"]):
        if layer <= 12: items.append((k, "IVQ", sc, layer, side))
    for k, side, sc, layer in walls(n["cand"], n["cand_cols"], n["S_ndx"], n["pc_all"]):
        if layer <= 12: items.append((round(k * conv, 3), "IVN", sc, layer, side))

    groups = {}
    def add(g, price, extra=None):
        groups.setdefault(g, []).append(price)

    for pts in (3, 5, 10):
        tol = pts / 10 * u
        for st in stacks(items, tol):
            if len(st) < 2: continue
            nyl = [x for x in st if x[1] == "NYL"]; iv = [x for x in st if x[1] != "NYL"]
            price = nyl[0][0] if nyl else max(iv, key=lambda x: x[2])[0]
            if pts == 5:
                add("Stack 2+", price)
                if len(st) >= 3: add("Stack 3+", price)
                if any(x[2] >= 40 for x in iv) and any(x[3] <= 8 for x in nyl): add("Strong stack (IVW 40+ and NYL L5/L8)", price)
                if any(x[2] >= 40 for x in iv): add("Stack with an IVW 40+", price)
                if iv:
                    best = max(iv, key=lambda x: x[2]); below = price < S
                    agree = (best[4] == 1 and below) or (best[4] == -1 and not below)
                    add("Stack, side agrees" if agree else "Stack, side mixed/against", price)
                if nyl and iv: add("Stack NYL + IV wall", price)
                if {x[1] for x in st} >= {"IVQ", "IVN"}: add("Stack QQQ IVW + NDX IVW", price)
            else:
                add(f"Stack 2+ ({pts} pts)", price)
    # singles (5 pt rule)
    singles = [st[0] for st in stacks(items, 0.5 * u) if len(st) == 1]
    for x in singles:
        strong = (x[1] == "NYL" and x[3] <= 8) or (x[1] != "NYL" and x[2] >= 40)
        add("Single, all", x[0])
        add("Single, strong (NYL L5/L8 or IVW 40+)" if strong else "Single, weak", x[0])
    for name, pool in (("Nearest 3 each side, all levels", [x[0] for x in items]), ("Nearest 3 each side, singles", [x[0] for x in singles])):
        pool = sorted(set(pool))
        for p in [p for p in pool if p >= S][:3] + [p for p in pool if p < S][-3:]: add(name, p)
    add_all = sorted({x[0] for x in items})
    for p in add_all: add("All levels", p)
    lo, hi = px.min(), px.max()
    groups["Random"] = [rng.uniform(lo - 0.002 * S, hi + 0.002 * S) for _ in range(40)]

    for g, levels in groups.items():
        for L in set(round(x, 3) for x in levels):
            start = 1
            for rep in range(2):
                i = None
                for m in range(start, 390):
                    near = abs(px[m] - L) <= 0.25 * u or (px[m - 1] - L) * (px[m] - L) < 0
                    if near and not abs(px[m - 1] - L) <= 0.25 * u: i = m; break
                if i is None: break
                side = 1 if px[i - 1] > L else -1
                hold = None
                for k in range(i + 1, min(i + 31, 390)):
                    if (px[k] - L) * side >= 1.5 * u: hold = True; break
                    if (px[k] - L) * side <= -1.5 * u: hold = False; break
                res = None; d = (px[i] - L) * side
                if d >= -0.25 * u:
                    stop, tgt = -(1 * u + d), 4 * u
                    for k in range(i + 1, min(i + 61, 390)):
                        mv = (px[k] - px[i]) * side
                        if mv <= stop: res = stop; break
                        if mv >= tgt: res = tgt; break
                    if res is None: res = (px[min(i + 60, 389)] - px[i]) * side
                    res = res / u * 10
                EV.append(dict(day=day, g=g, rep=rep + 1, regime=regime, tod="first hour" if i < 60 else "after", hold=hold, res=res))
                start = i + 1
                while start < 390 and abs(px[start] - L) <= 1.0 * u: start += 1

E = pd.DataFrame(EV)
ud = np.array(sorted(E.day.unique())); bs = np.random.default_rng(1)
byday = {d: E[E.day == d] for d in ud}


def st(s):
    h = s.hold.dropna(); t = s.res.dropna()
    return dict(touches=int(len(s)), hold=round(h.mean() * 100, 1) if len(h) else None,
                win=round((t > 0).mean() * 100, 1) if len(t) else None, pts=round(t.mean(), 2) if len(t) else None)


def edge(g, filt=None, B=400):
    hh, pp = [], []
    for _ in range(B):
        s = pd.concat([byday[d] for d in bs.choice(ud, len(ud))])
        if filt is not None: s = s[filt(s)]
        a, r = s[s.g == g], s[s.g == "Random"]
        if len(a.hold.dropna()) and len(r.hold.dropna()):
            hh.append((a.hold.dropna().mean() - r.hold.dropna().mean()) * 100); pp.append(a.res.dropna().mean() - r.res.dropna().mean())
    hh, pp = np.array(hh), np.array(pp)
    return dict(hold_vs_random=round(float(np.median(hh)), 1), chance_no_hold_edge=round(float((hh <= 0).mean()), 3),
                pts_vs_random=round(float(np.median(pp)), 2), chance_no_pts_edge=round(float((pp <= 0).mean()), 3))


G = [g for g in ["Stack 2+", "Stack 3+", "Stack 2+ (3 pts)", "Stack 2+ (10 pts)", "Strong stack (IVW 40+ and NYL L5/L8)",
                 "Stack with an IVW 40+", "Stack, side agrees", "Stack, side mixed/against", "Stack NYL + IV wall",
                 "Stack QQQ IVW + NDX IVW", "Single, all", "Single, strong (NYL L5/L8 or IVW 40+)", "Single, weak",
                 "Nearest 3 each side, all levels", "Nearest 3 each side, singles", "All levels", "Random"] if g in set(E.g)]
out = {"days": days, "first": str(ud[0]), "last": str(ud[-1]), "overall": {}, "first_touch": {}, "second_touch": {}, "regime": {}}
for g in G:
    out["overall"][g] = {**st(E[E.g == g]), **({} if g == "Random" else edge(g))}
for g in ["Stack 2+", "Strong stack (IVW 40+ and NYL L5/L8)", "Stack, side agrees", "Single, all", "Random"]:
    out["first_touch"][g] = {**st(E[(E.g == g) & (E.rep == 1)]), **({} if g == "Random" else edge(g, lambda s: s.rep == 1))}
    out["second_touch"][g] = {**st(E[(E.g == g) & (E.rep == 2)]), **({} if g == "Random" else edge(g, lambda s: s.rep == 2))}
for rg in ["long gamma", "short gamma"]:
    out["regime"][rg] = {g: {**st(E[(E.g == g) & (E.regime == rg)]), **({} if g == "Random" else edge(g, lambda s, rg=rg: s.regime == rg, 300))}
                         for g in ["Stack 2+", "Strong stack (IVW 40+ and NYL L5/L8)", "Stack, side agrees", "Random"]}
(R / "stack_test_results.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
