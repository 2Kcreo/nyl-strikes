"""Post the NYL Stacked levels (Box 1 + Box 2) to Discord once a day, after the 9:30 lock.

Needs the GitHub secret DISCORD_WEBHOOK (a Discord channel webhook URL). Without it, does nothing.
Sends 4 messages: a header, Box 1, a label, Box 2. Box 1 and Box 2 are plain text so a
long-press -> Copy Text pastes straight into Stacked -> NQ (TradingView or MotiveWave).
Posts once per day (remembered in docs/data/discord_sent.json). Run with --force to post again.
"""
import json, os, sys, time, datetime as dt, urllib.request
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data")
SENT = os.path.join(DATA, "discord_sent.json")
PAGE = "https://2kcreo.github.io/nyl-strikes/stacked.html"


def fmt(k):
    k = float(k)
    return str(int(k)) if k.is_integer() else str(round(k, 2))


def boxes(d, iv):
    nyl = [f"{fmt(s['k'])} L{s['dens']}" for s in sorted(d["strikes"], key=lambda s: -s["k"])]
    ndx = [fmt(s["k"]) for s in (d.get("ndx") or {}).get("strikes", [])]
    b2 = []
    if iv:
        b2 = [f"{fmt(l['k'])} IVW {l['side']} {l['score']} L{l.get('layer', 20)}"
              for l in iv.get("levels", []) + iv.get("ndx_levels", [])]
    return nyl, ndx, b2, iv


def chunks(lines, limit=1990):
    out, cur = [], ""
    for ln in lines:
        if cur and len(cur) + 1 + len(ln) > limit:
            out.append(cur); cur = ln
        else:
            cur = ln if not cur else cur + "\n" + ln
    if cur: out.append(cur)
    return out


def send(url, text):
    body = json.dumps({"content": text, "allowed_mentions": {"parse": []}}).encode()
    for attempt in range(4):
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json", "User-Agent": "nyl-bot (github actions, 1.0)"})
        try:
            urllib.request.urlopen(req, timeout=20).read()
            time.sleep(1.2)
            return
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(float(e.headers.get("Retry-After", "2")) + 0.5); continue
            raise SystemExit(f"Discord said HTTP {e.code}: {e.read()[:200]!r}")
    raise SystemExit("Discord kept rate-limiting")


def main():
    url = os.environ.get("DISCORD_WEBHOOK", "").strip()
    if not url:
        print("No DISCORD_WEBHOOK secret: skipping Discord"); return
    force = "--force" in sys.argv
    day = json.load(open(os.path.join(DATA, "index.json")))[0]
    d = json.load(open(os.path.join(DATA, f"{day}.json")))
    if not force and "locked" not in (d.get("spot_src") or "").lower():
        print(f"{day}: not locked yet ({d.get('spot_src')}), waiting"); return
    sent = {}
    if os.path.exists(SENT):
        try: sent = json.load(open(SENT))
        except Exception: sent = {}
    if not force and sent.get("day") == day:
        print(f"{day}: already posted"); return

    iv = None
    p = os.path.join(DATA, "ivwalls", "latest.json")
    if os.path.exists(p):
        iv = json.load(open(p))
        if iv.get("day") != day: iv = None
    now = dt.datetime.now(ET)
    # give the IV walls until 10:30 ET to show up, then post without them
    if iv is None and not force and now.hour * 60 + now.minute < 10 * 60 + 30:
        print(f"{day}: IV walls not built yet, waiting"); return

    nyl, ndx, b2, iv = boxes(d, iv)
    date = dt.date.fromisoformat(day).strftime("%a %b %-d")
    locked = "locked" in (d.get("spot_src") or "").lower()
    head = (f"**NYL STACKED · {date} · {'9:30 locked' if locked else 'PRE-MARKET (not final)'}**\n"
            f"QQQ {'open' if locked else 'prior close'} {d.get('spot', 0):.2f} · Box 1: {len(nyl)} QQQ + {len(ndx)} NDX strikes · "
            f"Box 2: {len(b2)} IV walls\n"
            f"Long-press the message under each label → Copy Text → paste into Stacked → NQ.\n"
            f"Page: <{PAGE}>\n\n**Box 1 · NYL strikes** ↓")
    send(url, head)
    p1 = chunks(nyl + ndx)
    for i, c in enumerate(p1):
        if len(p1) > 1: send(url, f"Box 1 part {i + 1}/{len(p1)} ↓")
        send(url, c)
    if b2:
        p2 = chunks(b2)
        send(url, "**Box 2 · IV walls** ↓" + (f"  (in {len(p2)} parts: paste them one after another)" if len(p2) > 1 else ""))
        for c in p2: send(url, c)
    else:
        send(url, "Box 2 · IV walls: not built today (leave Box 2 as it is)")
    json.dump({"day": day, "posted": now.strftime("%Y-%m-%d %H:%M ET")}, open(SENT, "w"))
    print(f"{day}: posted to Discord")


if __name__ == "__main__":
    main()
