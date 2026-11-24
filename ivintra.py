"""Intraday IV walls (research only): the same IV-wall table rebuilt at 10:30 and 11:30 instead of the morning.

For each day already in research/ivlong:
  - QQQ option quotes at 10:30 and 11:30 (30-minute snapshots, 0-2 DTE, wide strike range) -> fresh IV curve
  - that morning's open interest (same as the morning walls: OI doesn't update during the day)
  - QQQ price at that minute from the day's minute path
Saves research/ivintra/<day>.json with the candidate table at each time. Nothing after the snapshot time is used.

Usage: python ivintra.py 2024-11-18 2026-11-17
"""
import sys, json, inspect, datetime as dt
from pathlib import Path
import numpy as np, pandas as pd
import ivwalls, ivlong

ROOT = Path(__file__).resolve().parent
QQQ = ROOT / "research" / "ivlong"
OUT = ROOT / "research" / "ivintra"; OUT.mkdir(parents=True, exist_ok=True)
TIMES = {"10:30": 60, "11:30": 120}          # minutes after 9:30

# ivwalls.table with the clock moved from "prior close" to a time during the day:
# IV and time to expiry are measured from TA, and same-day (0 DTE) options are included.
_src = inspect.getsource(ivwalls.table)
_src = (_src.replace("def table(day, S, P, eod, oi):", "def table_at(day, S, TA, eod, oi):")
            .replace("tP = dt.datetime.combine(P, dt.time(16, 0))", "tP = TA")
            .replace("(eod.exp > P)", "(eod.exp >= day)")
            .replace("T0 = dt.datetime.combine(day, dt.time(9, 30))", "T0 = TA"))
assert "table_at" in _src and "tP = TA" in _src and "T0 = TA" in _src and "eod.exp >= day" in _src
_ns = dict(vars(ivwalls)); exec(_src, _ns); table_at = _ns["table_at"]


def one(day):
    f = OUT / f"{day}.json"
    if f.exists(): return "exists"
    j = json.loads((QQQ / f"{day}.json").read_text())
    q = ivlong.call("option_history_quote", symbol="QQQ", expiration="*", date=day, interval="30m", max_dte=2, strike_range=45)
    if q is None: return "no quotes"
    oi = ivlong.call("option_history_open_interest", symbol="QQQ", expiration="*", date=day, max_dte=8)
    if oi is None: return "no OI"
    ts = pd.to_datetime(q.timestamp)
    q = q.assign(m=(ts.dt.hour * 60 + ts.dt.minute) - (9 * 60 + 30))
    out = {"day": str(day), "times": {}}
    for name, m in TIMES.items():
        snap = q[q.m == m]
        S = j["path"][m] if j["path"][m] is not None else None
        if not len(snap) or S is None: continue
        TA = dt.datetime.combine(day, dt.time(9, 30)) + dt.timedelta(minutes=m)
        t = table_at(day, S, TA, snap.drop(columns=["m"]), oi)
        if t is None: continue
        by, pc_all, atm_iv = t
        cand = [[float(k), round(float(r.gex), 1), round(float(r.gex_cov_near), 1), round(float(r.rich), 5), round(float(r.curv), 5),
                 int(r.oi_call), int(r.oi_put)] for k, r in by.iterrows()]
        out["times"][name] = {"m": m, "S": S, "atm_iv": round(atm_iv, 4), "pc_all": round(float(pc_all), 4), "cand": cand}
    if not out["times"]: return "no table"
    out["cand_cols"] = ["k", "gex", "gex_cov_near", "rich", "curv", "oi_call", "oi_put"]
    f.write_text(json.dumps(out))
    return "ok " + " ".join(f"{k}:{len(v['cand'])}" for k, v in out["times"].items())


def main():
    a, b = dt.date.fromisoformat(sys.argv[1]), dt.date.fromisoformat(sys.argv[2])
    d = a
    while d <= b:
        if d.weekday() < 5 and (QQQ / f"{d}.json").exists():
            try: print(d, one(d), flush=True)
            except Exception as e: print(d, "FAILED", type(e).__name__, str(e)[:200], flush=True)
        d += dt.timedelta(days=1)


if __name__ == "__main__":
    main()
