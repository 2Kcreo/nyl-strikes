"""NDX IV walls for the long-history test (research only).

For each day already in research/ivlong (QQQ data), builds the same IV-wall table from NDXP options
(the daily-expiry NDX root, where the 0-2 DTE gamma the formula scores lives):
  - prior close NDXP option prices (IV, smile, curvature), that morning's NDXP open interest
  - NDX price at 9:31 = NDX prior close (put-call parity) x (QQQ 9:31 / QQQ prior close)
Saves research/ivlong_ndx/<day>.json. No look-ahead (same inputs as the QQQ walls).

Usage: python ivlong_ndx.py 2024-11-18 2026-11-17
"""
import sys, json, datetime as dt
from pathlib import Path
import ivwalls, ivlong

ROOT = Path(__file__).resolve().parent
QQQ = ROOT / "research" / "ivlong"
OUT = ROOT / "research" / "ivlong_ndx"; OUT.mkdir(parents=True, exist_ok=True)


def one(day):
    f = OUT / f"{day}.json"
    if f.exists(): return "exists"
    q = QQQ / f"{day}.json"
    if not q.exists(): return "no QQQ day"
    j = json.loads(q.read_text())
    P = dt.date.fromisoformat(j["P"])
    eod = ivlong.call("option_history_eod", symbol="NDXP", expiration="*", start_date=P, end_date=P, max_dte=9)
    if eod is None: return "no NDXP prior EOD"
    oi = ivlong.call("option_history_open_interest", symbol="NDXP", expiration="*", date=day, max_dte=8)
    if oi is None: return "no NDXP OI"
    prev_ndx = ivlong.parity(eod)
    S = prev_ndx * j["S"] / j["prevC"]
    t = ivwalls.table(day, S, P, eod, oi)
    if t is None: return "no IV table"
    by, pc_all, atm_iv = t
    cand = [[float(k), round(float(r.gex), 1), round(float(r.gex_cov_near), 1), round(float(r.rich), 5), round(float(r.curv), 5),
             int(r.oi_call), int(r.oi_put)] for k, r in by.iterrows()]
    f.write_text(json.dumps({"day": str(day), "S_ndx": round(S, 2), "prev_ndx": round(prev_ndx, 2), "S_qqq": j["S"],
                             "atm_iv": round(atm_iv, 4), "pc_all": round(float(pc_all), 4),
                             "cand_cols": ["k", "gex", "gex_cov_near", "rich", "curv", "oi_call", "oi_put"], "cand": cand}))
    return f"ok NDX={S:.1f} cand={len(cand)}"


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
