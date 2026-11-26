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


def chunks(lines, limit=1980):
    out, cur = [], ""
    for ln in lines:
        if cur and len(cur) + 1 + len(ln) > limit:
            out.append(cur); cur = ln
        else:
            cur = ln if not cur else cur + "\n" + ln
    if cur: out.append(cur)
    return out


PURPLE = 0xEC4899  # pink


def send(url, text=None, embed=None):
    msg = {"allowed_mentions": {"parse": []}}
    if text: msg["content"] = text
    if embed: msg["embeds"] = [embed]
    body = json.dumps(msg).encode()
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
    status = "🟢 9:30 locked (final)" if locked else "🟡 Pre-market (not final, wait for 9:30)"
    qqq = f"{d.get('spot', 0):.2f} ({'9:30 open' if locked else 'prior close'})"
    desc = (
        f"**Status**\n{status}\n\n"
        f"**QQQ**\n{qqq}\n\n"
        f"**Levels**\n📘 Box 1 · NYL strikes: **{len(nyl)} QQQ + {len(ndx)} NDX**\n"
        f"📙 Box 2 · IV walls: **{len(b2)}**" + ("" if b2 else " (not built today)") + "\n\n"
        "**How to use**\n"
        "1. Long-press the grey box under each label → **Copy Text**\n"
        "2. Open **Stacked → NQ** settings (TradingView or MotiveWave)\n"
        "3. Paste Box 1 into *NYL strikes*, Box 2 into *IV walls* → OK\n\n"
        f"🌐 [Open the NYL Stacked page]({PAGE})")
    send(url, embed={"title": f"📊  NYL Stacked · {date}", "description": desc, "color": PURPLE,
                     "footer": {"text": f"NYL · built {(d.get('built') or '').split(' ')[-1]} ET"}})

    def box(title, sub, lines, color):
        parts = chunks(lines)
        note = sub + (f"\nSent in {len(parts)} parts: copy and paste each one, in order." if len(parts) > 1 else "")
        send(url, embed={"title": title, "description": note, "color": color})
        for c in parts: send(url, "```\n" + c + "\n```")

    box("📘  Box 1 · NYL strikes", f"{len(nyl)} QQQ + {len(ndx)} NDX · paste into **NYL strikes (QQQ + NDX)**", nyl + ndx, 0xF472B6)
    if b2:
        box("📙  Box 2 · IV walls", f"{len(b2)} walls · paste into **IV walls (QQQ + NDX)**", b2, 0xF9A8D4)
    else:
        send(url, embed={"title": "📙  Box 2 · IV walls", "description": "Not built today. Leave Box 2 as it is.", "color": 0xF9A8D4})
    json.dump({"day": day, "posted": now.strftime("%Y-%m-%d %H:%M ET")}, open(SENT, "w"))
    print(f"{day}: posted to Discord")


if __name__ == "__main__":
    main()
