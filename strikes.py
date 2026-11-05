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
    (DATA / f"{day}.json").write_text(json.dumps(out, indent=1))
    days = sorted({p.stem for p in DATA.glob("20*.json")}, reverse=True)[:60]
    (DATA / "index.json").write_text(json.dumps(days))
    print(f"{day}: {sum(1 for s in out['strikes'] if s['dens'] <= 8)} strikes (8/layer), OI {oi_src}, QQQ {spot:.2f} ({spot_src})")

if __name__ == "__main__":
    main()
