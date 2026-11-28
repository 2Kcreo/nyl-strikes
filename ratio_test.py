"""Which NQ/QQQ ratio method puts the Stacked levels in the right place on NQ, and does placement matter?

Data: Yahoo NQ=F, QQQ, ^NDX bars (1-minute for the last ~29 days, 5-minute for ~60 days), the daily
NYL lists (docs/data/<day>.json) and IV walls (research/ivwalls or docs/data/ivwalls).

Ratio methods (each gives NQ/QQQ and NQ/NDX for the day):
  A  open      NQ 9:30 open / QQQ 9:30 open; NDX = A x QQQ prev close / NDX prev close  (TradingView + new MW)
  B  prior pm  median of NQ/QQQ and NQ/NDX over the prior day's 15:00-16:00 bars        (old MW)
  C  9:40-10   median 9:40-10:00 (only known at 10:00)
  D  premkt    median 9:00-9:29 using QQQ pre-market prints; NDX like A
  E  live      rolling median of the last 60 regular-hours minutes (moves during the day)
Tests:
  1  accuracy  NQ points between where a method puts a level and where it really is at each bar
               (truth = NQ / QQQ at that bar), QQQ levels and NDX levels
  2  holds     stacks / singles / all levels / random zones built with each method, touched on NQ
               hold = within 30 min price goes 15 pts back the way it came before 15 pts through
  3  offset    method A stacks moved -20..+20 NQ pts: if the exact spot mattered, holds would peak at 0
  4  zone pad  method A stacks touched with 0 / 2.5 / 5 pts of padding
  5  splits    method A: 1st vs 2nd touch, first hour vs later, support vs resistance
"""
import json, random, statistics as stt, datetime as dt, time, sys
from pathlib import Path
import numpy as np
import feeds

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "research" / "ratio_test_results.json"
rng = random.Random(11)
Y = feeds.Yahoo()


def bars_range(sym, interval, p1, p2):
    Y._session()
    import urllib.request
    s = urllib.request.quote(sym)
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?interval={interval}&period1={p1}&period2={p2}"
           f"&includePrePost=true&crumb={Y.crumb}")
    for a in range(3):
        try: return feeds.parse_chart(json.loads(Y.op.open(url, timeout=25).read()))
        except Exception as e:
            err = e; time.sleep(2)
    print("fetch failed", sym, interval, err); return []


def load(sym):
    now = int(time.time())
    m1 = []
    for w in range(4):
        p2 = now - w * 7 * 86400; p1 = p2 - 7 * 86400 + 60
        m1 += bars_range(sym, "1m", p1, p2)
    m5 = bars_range(sym, "5m", now - 59 * 86400, now)
    return {"1m": {b[0]: b for b in m1}, "5m": {b[0]: b for b in m5}}


def day_bars(src, day, res):
    return sorted((b for t, b in src[res].items() if t.date() == day), key=lambda b: b[0])


def tm(b): return b[0].hour * 60 + b[0].minute


def med(x): return stt.median(x) if x else None


def main():
    print("loading prices"); P = {s: load(s) for s in ("NQ=F", "QQQ", "^NDX")}
    days = sorted({t.date() for t in P["QQQ"]["5m"]} | {t.date() for t in P["QQQ"]["1m"]})
    res_days, acc, EV, OFF, PAD, SPL = [], {}, [], {}, {}, []
    prev = None
    for day in days:
        res = "1m" if day_bars(P["QQQ"], day, "1m") and day_bars(P["NQ=F"], day, "1m") else "5m"
        step = 1 if res == "1m" else 5
        nq, qq, nx = (day_bars(P[s], day, res) for s in ("NQ=F", "QQQ", "^NDX"))
        rth = lambda bs: [b for b in bs if 9 * 60 + 30 <= tm(b) < 16 * 60]
        nqr, qqr, nxr = rth(nq), rth(qq), rth(nx)
        if len(qqr) < (300 if res == "1m" else 60) or len(nqr) < len(qqr) * 0.9:
            prev = (nq, qq, nx, res) if len(qqr) > 40 else prev; continue
        NQ = {b[0]: b for b in nq}; QQ = {b[0]: b for b in qq}; NX = {b[0]: b for b in nx}
        f = ROOT / "docs" / "data" / f"{day}.json"
        ivf = ROOT / "research" / "ivwalls" / f"{day}.json"
        if not ivf.exists(): ivf = ROOT / "docs" / "data" / "ivwalls" / f"{day}.json"
        if not f.exists() or prev is None:
            prev = (nq, qq, nx, res); continue
        d = json.loads(f.read_text()); iv = json.loads(ivf.read_text()) if ivf.exists() else None
        o = qqr[0][0]
        if (o.hour, o.minute) != (9, 30) or o not in NQ:
            prev = (nq, qq, nx, res); continue
        # prior day's closes
        pq = [b for b in prev[1] if tm(b) < 16 * 60 and tm(b) >= 9 * 60 + 30]
        px_ = [b for b in prev[2] if tm(b) < 16 * 60 and tm(b) >= 9 * 60 + 30]
        if not pq or not px_: prev = (nq, qq, nx, res); continue
        qPrevC, xPrevC = pq[-1][4], px_[-1][4]
        pNQ = {b[0]: b for b in prev[0]}; pNX = {b[0]: b for b in prev[2]}

        def window(nqd, other, lo, hi):
            return [nqd[b[0]][4] / b[4] for b in other if lo <= tm(b) < hi and b[0] in nqd]

        M = {}
        rA = NQ[o][1] / qqr[0][1]; M["A open"] = (rA, rA * qPrevC / xPrevC)
        rB = med(window(pNQ, prev[1], 15 * 60, 16 * 60)); nB = med(window(pNX, prev[2], 15 * 60, 16 * 60))
        nB2 = med([pNQ[b[0]][4] / b[4] for b in prev[2] if 15 * 60 <= tm(b) < 16 * 60 and b[0] in pNQ])
        if rB and nB2: M["B prior pm"] = (rB, nB2)
        rC = med(window(NQ, qq, 9 * 60 + 40, 10 * 60)); nC = med(window(NQ, nx, 9 * 60 + 40, 10 * 60))
        if rC and nC: M["C 9:40-10"] = (rC, nC)
        rD = med(window(NQ, qq, 9 * 60, 9 * 60 + 30))
        if rD: M["D premkt"] = (rD, rD * qPrevC / xPrevC)
        # live (E): rolling 60-minute median, per bar
        liveQ, liveN = {}, {}
        histQ = [pNQ[b[0]][4] / b[4] for b in prev[1] if 9 * 60 + 30 <= tm(b) < 16 * 60 and b[0] in pNQ][-(60 // step):]
        histN = [pNQ[b[0]][4] / b[4] for b in prev[2] if 9 * 60 + 30 <= tm(b) < 16 * 60 and b[0] in pNQ][-(60 // step):]
        xmap = {b[0]: b for b in nxr}
        for b in qqr:
            if b[0] in NQ and not (9 * 60 + 30 <= tm(b) < 9 * 60 + 35): histQ = (histQ + [NQ[b[0]][4] / b[4]])[-(60 // step):]
            if b[0] in xmap and b[0] in NQ and not (9 * 60 + 30 <= tm(b) < 9 * 60 + 35):
                histN = (histN + [NQ[b[0]][4] / xmap[b[0]][4]])[-(60 // step):]
            liveQ[b[0]] = med(histQ); liveN[b[0]] = med(histN)

        # ---- test 1: accuracy (truth at each bar from 9:35; C only counted from 10:00)
        for b in qqr:
            if tm(b) < 9 * 60 + 35 or b[0] not in NQ: continue
            tq = NQ[b[0]][4] / b[4]
            xb = xmap.get(b[0]); tn = NQ[b[0]][4] / xb[4] if xb else None
            ms = dict(M); ms["E live"] = (liveQ.get(b[0]), liveN.get(b[0]))
            for name, (rq, rn) in ms.items():
                if name.startswith("C") and tm(b) < 10 * 60: continue
                a = acc.setdefault(name, {"q": [], "n": [], "q_first": [], "q_later": []})
                if rq: e = abs(b[4] * (rq - tq)); a["q"].append(e); a["q_first" if tm(b) < 10 * 60 + 30 else "q_later"].append(e)
                if rn and tn: a["n"].append(abs(xb[4] * (rn - tn)))

        # ---- levels in "QQQ units" and "NDX units"
        mem = []  # (kind, k, layer, src)
        for s in d["strikes"]:
            if s["dens"] <= 12: mem.append(("q", s["k"]))
        for s in d.get("ndx", {}).get("strikes", []): mem.append(("n", s["k"]))
        if iv:
            for l in iv.get("levels", []):
                if l.get("layer", 20) <= 12: mem.append(("q", l["k"]))
            for l in iv.get("ndx_levels", []):
                if l.get("layer", 20) <= 12: mem.append(("n", l["k"]))

        hi_, lo_ = max(b[2] for b in nqr), min(b[3] for b in nqr)

        def build(rq, rn):
            pts = sorted((k * rq if kind == "q" else k * rn) for kind, k in mem)
            grp, a = [], 0
            while a < len(pts):
                b2 = a
                while b2 + 1 < len(pts) and pts[b2 + 1] - pts[b2] <= 5: b2 += 1
                grp.append((pts[a], pts[b2], b2 - a + 1)); a = b2 + 1
            return grp

        def touches(zones, label, pad=0.0, store=None, conv=None):
            """zones: list of (lo, hi). conv: optional per-bar shift function (for live)"""
            for lo, hi in zones:
                lo -= pad; hi += pad
                start, n = 1, 0
                while n < 2:
                    i = None
                    for m in range(start, len(nqr)):
                        b, pb = nqr[m], nqr[m - 1]
                        if tm(b) < 9 * 60 + 35 or tm(b) >= 15 * 60 + 55: continue
                        sh = conv(m) if conv else 0
                        L, H = lo + sh, hi + sh
                        if b[3] <= H and b[2] >= L and (pb[3] > H or pb[2] < L): i = m; break
                    if i is None: break
                    sh = conv(i) if conv else 0
                    L, H = lo + sh, hi + sh
                    side = 1 if nqr[i - 1][3] > H else -1
                    ref_near, ref_far = (H, L) if side == 1 else (L, H)
                    hold = None
                    if side == 1 and nqr[i][3] < L - 15: hold = False
                    if side == -1 and nqr[i][2] > H + 15: hold = False
                    if hold is None:
                        for k in range(i + 1, min(i + 1 + 30 // step, len(nqr))):
                            b = nqr[k]
                            thr = (b[3] <= L - 15) if side == 1 else (b[2] >= H + 15)
                            bnc = (b[2] >= H + 15) if side == 1 else (b[3] <= L - 15)
                            if thr: hold = False; break
                            if bnc: hold = True; break
                    rec = dict(day=str(day), g=label, hold=hold, rep=n + 1, first_hour=tm(nqr[i]) < 10 * 60 + 30,
                               side="support" if side == 1 else "resistance")
                    (store if store is not None else EV).append(rec)
                    n += 1
                    start = i + 1
                    while start < len(nqr) and nqr[start][3] <= H + 10 and nqr[start][2] >= L - 10: start += 1

        # ---- test 2: holds per method
        for name, (rq, rn) in M.items():
            g = build(rq, rn)
            touches([(a, b) for a, b, c in g if c >= 2], f"{name} | stacks")
            touches([(a, b) for a, b, c in g if c == 1], f"{name} | singles")
        # live: build with the 10:00 live ratio and shift each bar by how live moved since (approximation of a moving line)
        gA = build(*M["A open"])
        zw = [b - a for a, b, c in gA if c >= 2] or [3]
        w = stt.median(zw)
        rz = []
        for _ in range(40):
            c0 = rng.uniform(lo_ - 30, hi_ + 30); rz.append((c0 - w / 2, c0 + w / 2))
        touches(rz, "Random zones (stack width)")
        touches([(c - 0.01, c + 0.01) for c in (rng.uniform(lo_ - 30, hi_ + 30) for _ in range(40))], "Random lines")
        # ---- test 3: offsets on A stacks
        stA = [(a, b) for a, b, c in gA if c >= 2]
        for off in np.arange(-20, 20.01, 2.5):
            touches([(a + off, b + off) for a, b in stA], f"off {off:+.1f}", store=OFF.setdefault(f"{off:+.1f}", []))
        # ---- test 4: padding
        for pad in (0, 2.5, 5):
            touches(stA, f"pad {pad}", pad=pad, store=PAD.setdefault(str(pad), []))
            touches(rz, f"pad {pad} random", pad=pad, store=PAD.setdefault(f"{pad} random", []))
        # ---- test 5: splits for A stacks
        touches(stA, "A stacks", store=SPL)
        res_days.append(dict(day=str(day), res=res, **{k: [round(v[0], 4), round(v[1], 5)] for k, v in M.items()},
                             shiftAB_q=round((M["A open"][0] - M.get("B prior pm", (M["A open"][0],))[0]) * qqr[0][1], 1)))
        prev = (nq, qq, nx, res)
        print(day, res, {k: round(v[0], 3) for k, v in M.items()})

    # ---- summarise
    def rate(evs):
        h = [e["hold"] for e in evs if e["hold"] is not None]
        return (round(100 * sum(h) / len(h), 1) if h else None), len(h)

    def boot(evs, base, B=1000):
        """CI of hold-rate difference vs base, resampling days"""
        ds = sorted({e["day"] for e in evs} | {e["day"] for e in base})
        by = lambda E: {dd: [e["hold"] for e in E if e["day"] == dd and e["hold"] is not None] for dd in ds}
        a, b = by(evs), by(base); r = np.random.default_rng(3); diffs = []
        for _ in range(B):
            s = r.choice(ds, len(ds))
            x = sum((a[dd] for dd in s), []); y = sum((b[dd] for dd in s), [])
            if x and y: diffs.append(100 * (np.mean(x) - np.mean(y)))
        return [round(float(np.percentile(diffs, 5)), 1), round(float(np.percentile(diffs, 95)), 1)] if diffs else None

    out = {"days": len(res_days), "per_day": res_days}
    out["accuracy_nq_pts"] = {k: {"QQQ levels median": round(stt.median(v["q"]), 2), "QQQ p90": round(float(np.percentile(v["q"], 90)), 2),
                                  "QQQ median first hour": round(stt.median(v["q_first"]), 2) if v["q_first"] else None,
                                  "QQQ median after": round(stt.median(v["q_later"]), 2) if v["q_later"] else None,
                                  "NDX levels median": round(stt.median(v["n"]), 2) if v["n"] else None,
                                  "NDX p90": round(float(np.percentile(v["n"], 90)), 2) if v["n"] else None, "bars": len(v["q"])}
                              for k, v in acc.items()}
    rnd = [e for e in EV if e["g"] == "Random zones (stack width)"]
    groups = sorted({e["g"] for e in EV})
    out["holds"] = {g: {"hold %": rate([e for e in EV if e["g"] == g])[0], "touches": rate([e for e in EV if e["g"] == g])[1],
                        "vs random zones (90% CI)": boot([e for e in EV if e["g"] == g], rnd)} for g in groups}
    AB = [e for e in EV if e["g"] == "A open | stacks"]; BB = [e for e in EV if e["g"] == "B prior pm | stacks"]
    out["A vs B stacks (90% CI, A minus B)"] = boot(AB, BB)
    out["offset_curve"] = {k: {"hold %": rate(v)[0], "touches": rate(v)[1]} for k, v in sorted(OFF.items(), key=lambda x: float(x[0]))}
    out["padding"] = {k: {"hold %": rate(v)[0], "touches": rate(v)[1]} for k, v in PAD.items()}
    out["splits_A_stacks"] = {
        "1st touch": rate([e for e in SPL if e["rep"] == 1]), "2nd touch": rate([e for e in SPL if e["rep"] == 2]),
        "first hour": rate([e for e in SPL if e["first_hour"]]), "after 10:30": rate([e for e in SPL if not e["first_hour"]]),
        "support": rate([e for e in SPL if e["side"] == "support"]), "resistance": rate([e for e in SPL if e["side"] == "resistance"])}
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "per_day"}, indent=1))


if __name__ == "__main__":
    main()
