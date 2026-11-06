"""Builds today's VEX key QQQ strikes in the cloud (GitHub Actions) and saves them for the website in docs/data/."""
import os, sys, json, datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd, engine, feeds
ROOT = Path(__file__).resolve().parent; DATA = ROOT / "docs" / "data"; DATA.mkdir(parents=True, exist_ok=True)
ET = ZoneInfo("America/New_York")
TAG = {"volume": "VOL", "gex_abs": "GEX", "vex": "VEX", "chex": "CHX", "fresh_oi": "NEW", "gex_walls": "WALL", "oi_walls": "OI", "em_bands": "EM"}
theta = feeds.Theta(lambda: os.environ.get("THETADATA_API_KEY", ""))
def prev_wd(d):
    d -= dt.timedelta(days=1)
    while d.weekday() >= 5: d -= dt.timedelta(days=1)
    return d
def get(kind, d):
    try:
        df = theta.oi(d) if kind == "oi" else theta.eod(d)
        return df if df is not None and len(df) else None
    except Exception as e:
        print(f"ThetaData {kind} {d}: {type(e).__name__}: {e}"); return None
def parity_spot(eod):
    e = eod[eod.expiration.astype(str) == sorted(eod.expiration.astype(str).unique())[0]]
    call = e.right.astype(str).str.upper().str.startswith("C")
    c = e[call].set_index("strike"); p = e[~call].set_index("strike")
    d = ((c.bid + c.ask) / 2 - (p.bid + p.ask) / 2).dropna(); k = d.abs().idxmin(); return float(k + d.loc[k])

def main():
    if not os.environ.get("THETADATA_API_KEY"): sys.exit("THETADATA_API_KEY secret is not set in the repo settings.")
    now = dt.datetime.now(ET); day = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else now.date()
    if day.weekday() >= 5: print("Weekend, nothing to do."); return
    P = prev_wd(day); eod = None
    for _ in range(6):
        eod = get("eod", P)
        if eod is not None: break
        P = prev_wd(P)
    if eod is None: sys.exit("No prior-day option prices.")
    oi = get("oi", day); oi_src = str(day)
    if oi is None and day == now.date() and now.time() >= dt.time(6, 30):   # today's OI posts ~6:30 ET
        try:
            oi = theta.oi_snapshot(); oi = oi if oi is not None and len(oi) else None
            if oi is not None: print("open interest from today's snapshot:", len(oi), "rows", list(oi.columns)); oi_src = f"{day} (snapshot)"
        except Exception as e: print(f"ThetaData oi snapshot: {type(e).__name__}: {e}"); oi = None
    if oi is None: oi = get("oi", P); oi_src = f"{P} (today's not out yet)"
    if oi is None: sys.exit("No open interest.")
    poi = get("oi", P) if oi_src == str(day) else oi
    if poi is None: poi = oi
    prevC = parity_spot(eod); spot = prevC; spot_src = "prior close"
    try:
        b = [x for x in feeds.Yahoo().bars("QQQ", "1m", "1d") if x[0].date() == day and x[0].time() >= dt.time(9, 30)]
        if b: spot, spot_src = b[0][1], "9:30 open"
    except Exception as e: print(f"Yahoo: {e}")
    cfg = json.load(open(ROOT / "config.json"))
    rows, em, flip = {}, None, []
    for dens, (n, w) in {"5": (5, .02), "8": (8, .03), "12": (12, .03), "20": (20, .045)}.items():
        r = engine.compute(day, P, oi, eod, poi, spot, prevC, dict(cfg, top_n=n, window_pct=w))
        for fam, xs in r["fam"].items():
            if fam == "gamma_flip": continue
            for x in xs:
                k = round(float(x["k"])) if fam == "em_bands" else round(float(x["k"]), 2)
                e = rows.setdefault(k, {"k": k, "tags": set(), "dens": int(dens)})
                e["tags"].add(TAG.get(fam, fam)); e["dens"] = min(e["dens"], int(dens))
        if dens == "8": em = r["em"]; flip = [round(x["k"], 1) for x in r["fam"].get("gamma_flip", [])]
    out = {"day": str(day), "built": now.strftime("%Y-%m-%d %H:%M ET"), "oi": oi_src, "spot": round(spot, 2), "spot_src": spot_src,
           "em": round(em, 2), "flip": flip,
           "strikes": [{"k": e["k"], "tags": sorted(e["tags"]), "dens": e["dens"], "star": len(e["tags"] - {"EM"}) >= 2}
                       for e in sorted(rows.values(), key=lambda e: -e["k"])]}
    # ---- NDX / NDXP layer (index options = the exact index NQ follows). Probe what the plan returns.
    out["ndx_status"] = {}
    ndx_rows = {}
    for sym in ("NDX", "NDXP"):
        st = {}
        try:
            e2 = None; P2 = P
            for _ in range(4):
                mdte = 35 if sym == "NDX" else 9          # NDX root = monthly (3rd Friday) expiries, often >9 days out
                try: e2 = theta._df("option_history_eod", symbol=sym, expiration="*", start_date=P2, end_date=P2, max_dte=mdte)
                except Exception as ex: st["eod_error"] = f"{type(ex).__name__}: {str(ex)[:160]}"; e2 = None
                if e2 is not None and len(e2): break
                P2 = prev_wd(P2)
            st["eod_rows"] = 0 if e2 is None else len(e2)
            o2 = None
            try: o2 = theta._df("option_history_open_interest", symbol=sym, expiration="*", date=day, max_dte=mdte)
            except Exception as ex: st["oi_hist_error"] = f"{type(ex).__name__}: {str(ex)[:160]}"
            if (o2 is None or not len(o2)) and day == now.date() and now.time() >= dt.time(6, 30):
                try: o2 = theta._df("option_snapshot_open_interest", symbol=sym, expiration="*", max_dte=mdte)
                except Exception as ex: st["oi_snap_error"] = f"{type(ex).__name__}: {str(ex)[:160]}"
            if o2 is None or not len(o2):
                try: o2 = theta._df("option_history_open_interest", symbol=sym, expiration="*", date=P2, max_dte=mdte); st["oi_from"] = str(P2)
                except Exception as ex: st["oi_prev_error"] = f"{type(ex).__name__}: {str(ex)[:160]}"
            st["oi_rows"] = 0 if o2 is None else len(o2)
            if st["eod_rows"] and st["oi_rows"]:
                s2 = parity_spot(e2); st["spot"] = round(s2, 2)
                r = engine.compute(day, P2, o2, e2, o2, s2, s2, dict(cfg, top_n=8, window_pct=.03))
                for fam, xs in r["fam"].items():
                    if fam in ("gamma_flip",): continue
                    for x in xs:
                        k = round(float(x["k"]))
                        e = ndx_rows.setdefault(k, {"k": k, "tags": set(), "src": set()})
                        e["tags"].add(TAG.get(fam, fam)); e["src"].add(sym)
                st["ok"] = True
        except Exception as ex:
            st["error"] = f"{type(ex).__name__}: {str(ex)[:200]}"
        out["ndx_status"][sym] = st
        print(sym, st)
    if ndx_rows:
        ndx_spot = next((v["spot"] for v in out["ndx_status"].values() if v.get("spot")), None)
        ratio = ndx_spot / prevC if ndx_spot else None          # NDX points per QQQ dollar
        out["ndx"] = {"spot": ndx_spot, "ratio": round(ratio, 4) if ratio else None,
                      "strikes": [{"k": e["k"], "tags": sorted(e["tags"]), "src": sorted(e["src"]), "qqq": round(e["k"] / ratio, 2) if ratio else None}
                                  for e in sorted(ndx_rows.values(), key=lambda e: -e["k"])]}
        # confluence: QQQ strikes with an NDX/NDXP level within $0.50 QQQ get an NDX tag and become stacked
        if ratio:
            for sobj in out["strikes"]:
                if any(abs(n["qqq"] - sobj["k"]) <= 0.5 for n in out["ndx"]["strikes"]):
                    sobj["tags"] = sorted(set(sobj["tags"]) | {"NDX"}); sobj["star"] = len(set(sobj["tags"]) - {"EM"}) >= 2
    (DATA / f"{day}.json").write_text(json.dumps(out, indent=1))
    days = sorted({p.stem for p in DATA.glob("20*.json")}, reverse=True)[:60]
    (DATA / "index.json").write_text(json.dumps(days))
    print(f"{day}: {sum(1 for s in out['strikes'] if s['dens'] <= 8)} strikes (8/layer), OI {oi_src}, QQQ {spot:.2f} ({spot_src})")

if __name__ == "__main__":
    main()
