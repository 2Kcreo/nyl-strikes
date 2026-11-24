"""Follow-up tests on the same 2 years (research/ivlong + ivlong_ndx), all inputs known by 9:31:
  1. Break trades at stacks: after the first touch, price closes 5 NQ pts through within 15 min -> trade the break
     (stop 10 pts back through the level, target 40, exit after 60 min). Same rule on random lines.
  2. Stacks as targets: from 9:31, does price reach a level 0.1%-1.5% away by the close, vs a mirror line the same
     distance on the other side? (and minutes to reach)
  3. Call / put walls only: the biggest support IV wall below and resistance IV wall above (QQQ and NDX), and the
     classic OI walls (most call OI above, most put OI below).
  4. Gamma regime: fade vs break, long gamma (9:31 price above the flip) vs short gamma.
  + TPO levels from the prior day's regular-hours minute prices (time at price): POC, VAH, VAL (70%), prior high,
    low, close, and today's opening range high/low after 10:30 (initial balance). Alone and stacked with GEX stacks.
Units as before: u = 0.037% of QQQ ~= 10 NQ points.
"""
import json, random
from pathlib import Path
import numpy as np, pandas as pd
from stack_test import walls, stacks

R = Path(__file__).resolve().parent / "research"
rng = random.Random(11)
FADE, BREAK, REACH = [], [], []


def tpo(px, step):
    """Prior-day TPO profile from regular-hours minute prices: POC, VAH, VAL (70% of minutes)."""
    b = np.round(px / step).astype(int)
    vals, cnt = np.unique(b, return_counts=True)
    i = int(np.argmax(cnt)); lo = hi = i; tot = cnt.sum(); acc = cnt[i]
    while acc < 0.7 * tot and (lo > 0 or hi < len(cnt) - 1):
        up = cnt[hi + 1] if hi < len(cnt) - 1 else -1
        dn = cnt[lo - 1] if lo > 0 else -1
        if up >= dn: hi += 1; acc += cnt[hi]
        else: lo -= 1; acc += cnt[lo]
    return vals[i] * step, vals[hi] * step, vals[lo] * step


def run(px, L, u, start, g, day, regime):
    """Up to 2 fresh touches from minute `start`. Records the fade result and the break result."""
    s0 = start
    for rep in range(2):
        i = None
        for m in range(max(s0, 1), 390):
            near = abs(px[m] - L) <= 0.25 * u or (px[m - 1] - L) * (px[m] - L) < 0
            if near and not abs(px[m - 1] - L) <= 0.25 * u: i = m; break
        if i is None: return
        side = 1 if px[i - 1] > L else -1
        # fade (same as before)
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
        FADE.append(dict(day=day, g=g, rep=rep + 1, regime=regime, hold=hold, res=res))
        # break: within 15 min a minute closes 5 pts through -> enter there, direction -side
        e = None
        for k in range(i, min(i + 16, 390)):
            if (px[k] - L) * side <= -0.5 * u: e = k; break
        bres = None
        if e is not None:
            dirn = -side; entry = px[e]
            stopp = L + side * 0.5 * u           # 5 pts back on the original side of the level
            for k in range(e + 1, min(e + 61, 390)):
                if (px[k] - stopp) * dirn <= 0: bres = (stopp - entry) * dirn; break
                if (px[k] - entry) * dirn >= 4 * u: bres = 4 * u; break
            if bres is None: bres = (px[min(e + 60, 389)] - entry) * dirn
            bres = bres / u * 10
        BREAK.append(dict(day=day, g=g, rep=rep + 1, regime=regime, broke=e is not None, res=bres))
        s0 = i + 1
        while s0 < 390 and abs(px[s0] - L) <= 1.0 * u: s0 += 1


prev = None
days = 0
for f in sorted((R / "ivlong").glob("20*.json")):
    j = json.loads(f.read_text()); day = j["day"]; S = j["S"]
    px = np.array([np.nan if x is None else x for x in j["path"]], float)
    ok = (~np.isnan(px)).sum() >= 300
    if ok: px = pd.Series(px).ffill().bfill().to_numpy()
    nf = R / "ivlong_ndx" / f"{day}.json"
    pday = prev; prev = (day, px) if ok else None
    if not ok or not nf.exists(): continue
    n = json.loads(nf.read_text()); conv = S / n["S_ndx"]
    days += 1; u = S * 0.00037
    flip = j["flip"][0] if j["flip"] else None
    regime = "unknown" if flip is None else ("long gamma" if S >= flip else "short gamma")

    items = []
    for k, dens, nt in j["nyl"]:
        if dens <= 12: items.append((float(k), "NYL", 0, dens, 9))
    wq = walls(j["cand"], j["cand_cols"], S, j["pc_all"])
    wn = walls(n["cand"], n["cand_cols"], n["S_ndx"], n["pc_all"])
    for k, side, sc, layer in wq:
        if layer <= 12: items.append((k, "IVQ", sc, layer, side))
    for k, side, sc, layer in wn:
        if layer <= 12: items.append((round(k * conv, 3), "IVN", sc, layer, side))

    G = {}
    for st in stacks(items, 0.5 * u):
        if len(st) < 2: continue
        nyl = [x for x in st if x[1] == "NYL"]; iv = [x for x in st if x[1] != "NYL"]
        price = nyl[0][0] if nyl else max(iv, key=lambda x: x[2])[0]
        G.setdefault("Stack 2+", []).append(price)
        if any(x[2] >= 40 for x in iv) and any(x[3] <= 8 for x in nyl): G.setdefault("Strong stack", []).append(price)
        if {x[1] for x in st} >= {"IVQ", "IVN"}: G.setdefault("Stack QQQ IVW + NDX IVW", []).append(price)
    # 3. call / put walls
    sup = [w for w in wq if w[1] == 1 and w[0] < S]; res = [w for w in wq if w[1] == -1 and w[0] >= S]
    if sup: G.setdefault("Put wall (top support IVW below)", []).append(max(sup, key=lambda w: w[2])[0])
    if res: G.setdefault("Call wall (top resistance IVW above)", []).append(max(res, key=lambda w: w[2])[0])
    supn = [w for w in wn if w[1] == 1 and w[0] < n["S_ndx"]]; resn = [w for w in wn if w[1] == -1 and w[0] >= n["S_ndx"]]
    if supn: G.setdefault("NDX put wall", []).append(round(max(supn, key=lambda w: w[2])[0] * conv, 3))
    if resn: G.setdefault("NDX call wall", []).append(round(max(resn, key=lambda w: w[2])[0] * conv, 3))
    c = pd.DataFrame(j["cand"], columns=j["cand_cols"])
    up, dn = c[c.k >= S], c[c.k < S]
    if len(up): G.setdefault("Classic call wall (most call OI above)", []).append(float(up.loc[up.oi_call.idxmax(), "k"]))
    if len(dn): G.setdefault("Classic put wall (most put OI below)", []).append(float(dn.loc[dn.oi_put.idxmax(), "k"]))
    # TPO levels (prior day, rescaled to today's prices with the overnight change in level? no: same QQQ prices)
    tp = []
    if pday is not None:
        ppx = pday[1]
        poc, vah, val = tpo(ppx, 0.05)
        tp = [("TPO POC", poc), ("TPO VAH", vah), ("TPO VAL", val), ("Prior high", ppx.max()), ("Prior low", ppx.min()), ("Prior close", ppx[-1])]
        for name, v in tp: G.setdefault(name, []).append(v)
        G["TPO all (POC/VAH/VAL/high/low/close)"] = [v for _, v in tp]
        tpv = [v for _, v in tp]
        st2 = G.get("Stack 2+", [])
        G["Stack 2+ on a TPO level"] = [p for p in st2 if any(abs(p - v) <= 0.5 * u for v in tpv)]
        G["Stack 2+ not near TPO"] = [p for p in st2 if not any(abs(p - v) <= 0.5 * u for v in tpv)]
        G["TPO level with a GEX level on it"] = [v for v in tpv if any(abs(v - x[0]) <= 0.5 * u for x in items)]
    lo, hi = px.min(), px.max()
    G["Random"] = [rng.uniform(lo - 0.002 * S, hi + 0.002 * S) for _ in range(40)]
    for g, levels in G.items():
        for L in set(round(x, 3) for x in levels): run(px, L, u, 1, g, day, regime)
    # initial balance (known at 10:30): touches after 10:30 only
    ibh, ibl = px[:60].max(), px[:60].min()
    for L in (ibh, ibl): run(px, L, u, 60, "Initial balance high/low (after 10:30)", day, regime)
    for L in [rng.uniform(lo - 0.002 * S, hi + 0.002 * S) for _ in range(20)]: run(px, L, u, 60, "Random (after 10:30)", day, regime)

    # 2. reach / magnet
    for g in ["Stack 2+", "Strong stack", "Stack QQQ IVW + NDX IVW", "TPO POC", "TPO all (POC/VAH/VAL/high/low/close)"]:
        for L in set(G.get(g, [])):
            dist = abs(L - S) / S
            if not 0.001 <= dist <= 0.015: continue
            for kind, lev in (("level", L), ("mirror", 2 * S - L)):
                hit = next((m for m in range(1, 390) if (px[m - 1] - lev) * (px[m] - lev) <= 0 or abs(px[m] - lev) <= 0.25 * u), None)
                REACH.append(dict(day=day, g=g, kind=kind, regime=regime, hit=hit is not None, mins=hit))

F, B, M = pd.DataFrame(FADE), pd.DataFrame(BREAK), pd.DataFrame(REACH)
ud = np.array(sorted(F.day.unique())); bs = np.random.default_rng(3)
fd = {d: F[F.day == d] for d in ud}; bd = {d: B[B.day == d] for d in ud}


def boot(D, g, col, base="Random", filt=None, B_=400):
    out = []
    for _ in range(B_):
        s = pd.concat([D[d] for d in bs.choice(ud, len(ud))])
        if filt is not None: s = s[filt(s)]
        a, r = s[s.g == g][col].dropna(), s[s.g == base][col].dropna()
        if len(a) and len(r): out.append(a.astype(float).mean() - r.astype(float).mean())
    o = np.array(out)
    return round(float(np.median(o)) * (100 if col == "hold" else 1), 2), round(float((o <= 0).mean()), 3)


def fade_row(g, base="Random", filt=None):
    s = F[F.g == g] if filt is None else F[(F.g == g) & filt(F)]
    h, t = s.hold.dropna(), s.res.dropna()
    dh, ph = boot(fd, g, "hold", base, filt); dp, pp = boot(fd, g, "res", base, filt)
    return dict(touches=len(s), hold=round(h.mean() * 100, 1), pts=round(t.mean(), 2), hold_vs_random=dh, p_hold=ph, pts_vs_random=dp, p_pts=pp)


def break_row(g, base="Random", filt=None):
    s = B[B.g == g] if filt is None else B[(B.g == g) & filt(B)]
    t = s.res.dropna()
    dp, pp = boot(bd, g, "res", base, filt)
    return dict(touches=len(s), broke_pct=round(s.broke.mean() * 100, 1), trades=len(t), win=round((t > 0).mean() * 100, 1),
                pts=round(t.mean(), 2), pts_vs_random=dp, p_pts=pp)


out = {"days": days, "first": str(ud[0]), "last": str(ud[-1]), "1_break": {}, "1_break_first_touch": {}, "2_reach": {},
       "3_walls": {}, "4_regime": {}, "tpo": {}}
for g in ["Stack 2+", "Strong stack", "Stack QQQ IVW + NDX IVW"]:
    out["1_break"][g] = break_row(g)
    out["1_break_first_touch"][g] = break_row(g, filt=lambda s: s.rep == 1)
out["1_break"]["Random"] = break_row("Random"); out["1_break_first_touch"]["Random"] = break_row("Random", filt=lambda s: s.rep == 1)
for g in M.g.unique():
    s = M[M.g == g]; lv, mi = s[s.kind == "level"], s[s.kind == "mirror"]
    # paired by day bootstrap of (reach level - reach mirror)
    per = s.groupby(["day", "kind"]).hit.mean().unstack()
    diffs = []
    dd = per.dropna()
    for _ in range(400):
        x = dd.sample(len(dd), replace=True, random_state=int(rng.random() * 1e9))
        diffs.append((x["level"] - x["mirror"]).mean())
    diffs = np.array(diffs)
    out["2_reach"][g] = dict(levels=int(len(lv)), reach_pct=round(lv.hit.mean() * 100, 1), mirror_reach_pct=round(mi.hit.mean() * 100, 1),
                             median_minutes_to_reach=float(lv.mins.dropna().median()) if lv.hit.any() else None,
                             chance_no_edge=round(float((diffs <= 0).mean()), 3))
for g in ["Put wall (top support IVW below)", "Call wall (top resistance IVW above)", "NDX put wall", "NDX call wall",
          "Classic call wall (most call OI above)", "Classic put wall (most put OI below)"]:
    out["3_walls"][g] = {"fade": fade_row(g), "break": break_row(g)}
for rg in ["long gamma", "short gamma"]:
    fl = lambda s, rg=rg: s.regime == rg
    out["4_regime"][rg] = {g: {"fade": fade_row(g, filt=fl), "break": break_row(g, filt=fl)} for g in ["Stack 2+", "Strong stack"]}
    out["4_regime"][rg]["Random"] = {"fade": {k: v for k, v in fade_row("Random", filt=fl).items() if "random" not in k and not k.startswith("p_")},
                                     "break": {k: v for k, v in break_row("Random", filt=fl).items() if "random" not in k and not k.startswith("p_")}}
for g in ["TPO POC", "TPO VAH", "TPO VAL", "Prior high", "Prior low", "Prior close", "TPO all (POC/VAH/VAL/high/low/close)",
          "Stack 2+ on a TPO level", "Stack 2+ not near TPO", "TPO level with a GEX level on it"]:
    out["tpo"][g] = {"fade": fade_row(g), "break": break_row(g)}
out["tpo"]["Initial balance high/low (after 10:30)"] = {"fade": fade_row("Initial balance high/low (after 10:30)", base="Random (after 10:30)"),
                                                       "break": break_row("Initial balance high/low (after 10:30)", base="Random (after 10:30)")}
(R / "stack_test2_results.json").write_text(json.dumps(out, indent=1, default=float))
print(json.dumps(out, indent=1, default=float))
