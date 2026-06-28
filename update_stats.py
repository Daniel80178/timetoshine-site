"""
TIMETOSHINE — promo page stats updater.

Reads closed-trade history and rewrites the live numbers in promo/index.html.
Designed to be run by a Windows Task Scheduler job on a schedule (e.g. every
hour or once a day after market close).

Data sources, in priority order:
  1) bot_log/closed_trades.csv  -- populated by the V5 bot from 2026-06-11 onward
  2) myfxbook/*.xlsx            -- newest XLSX export (manual fallback / pre-Jun-11 history)

Whichever exists with the most recent / complete data wins.

After updating the HTML, the script can optionally `git add/commit/push` so the
Netlify-linked GitHub repo auto-deploys. Set GIT_AUTO_PUSH = True once the repo
is wired up.
"""

from __future__ import annotations
import csv
import json
import random
import re
import sys
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

HERE             = Path(__file__).resolve().parent
INDEX_HTML       = HERE / "index.html"
DAILY_POST_TXT   = HERE / "daily_post.txt"
BOT_LOG_DIR      = Path(r"C:\TradingBots\TIMETOSHINE\bot_log")
CLOSED_CSV       = BOT_LOG_DIR / "closed_trades.csv"
XLSX_DIR         = Path(r"C:\TradingBots\TIMETOSHINE_DEPLOY\myfxbook")
QUOTE_HISTORY    = BOT_LOG_DIR / "quote_history.json"
TELEGRAM_CONFIG  = BOT_LOG_DIR / "telegram_config.json"   # local-only, never in git
FTP_CONFIG       = BOT_LOG_DIR / "ftp_config.json"        # Afrihost FTP, never in git
MANUAL_BALANCE   = BOT_LOG_DIR / "manual_balance.json"   # optional override; wins when newer than last CSV trade

LAUNCH_DATE         = date(2026, 6, 1)
QUOTE_NOREPEAT_DAYS = 14

GIT_AUTO_PUSH = True   # GitHub repo wired up + Netlify auto-deploys on push


# ----------------------------------------------------------------------
# 90-quote bank (mirrors project_trading_quotes_bank.md)
# ----------------------------------------------------------------------
QUOTES = [
    ("The four most dangerous words in investing are: 'this time it's different.'", "Sir John Templeton"),
    ("Cut your losses short, let your winners run.", "David Ricardo"),
    ("Plan the trade, and trade the plan.", "Anonymous market saying"),
    ("Amateurs think about how much money they can make. Professionals think about how much money they could lose.", "Jack Schwager"),
    ("Discipline beats brilliance every time.", "Anonymous market saying"),
    ("Don't trust your instincts. Trust your plan.", "Anonymous market saying"),
    ("Stick to your system, even when it hurts.", "Anonymous market saying"),
    ("The system works if you do.", "Anonymous market saying"),
    ("Every trader has strengths and weaknesses. Stick to your own style and you get the good and the bad in your own approach.", "Michael Marcus"),
    ("The biggest secret about success is that there isn't any big secret about it.", "Larry Hite"),
    ("Markets reward those who do their homework and punish those who don't.", "Anonymous market saying"),
    ("Profit is the reward for patience and discipline, not for being clever.", "Anonymous market saying"),
    ("The big money is not in the buying and selling, but in the waiting.", "Charlie Munger"),
    ("The market is a device for transferring money from the impatient to the patient.", "Warren Buffett"),
    ("It was never my thinking that made the big money for me. It always was my sitting.", "Jesse Livermore"),
    ("The desire for constant action irrespective of underlying conditions is responsible for many losses in Wall Street.", "Jesse Livermore"),
    ("Patience is bitter, but its fruit is sweet.", "Jean-Jacques Rousseau"),
    ("Time in the market beats timing the market.", "Anonymous market saying"),
    ("Inaction is a position.", "Anonymous market saying"),
    ("Cash is a position too.", "Anonymous market saying"),
    ("Most of the time, the best thing to do is nothing.", "Anonymous market saying"),
    ("Markets reward patience and punish urgency.", "Anonymous market saying"),
    ("Rule No. 1: Never lose money. Rule No. 2: Never forget Rule No. 1.", "Warren Buffett"),
    ("Risk comes from not knowing what you're doing.", "Warren Buffett"),
    ("Markets can stay irrational longer than you can stay solvent.", "John Maynard Keynes"),
    ("Risk management is the most important thing to be well understood. Undertrade, undertrade, undertrade.", "Bruce Kovner"),
    ("Survival is the first rule of trading. Profits come second.", "Ed Seykota"),
    ("Successful investing is about managing risk, not avoiding it.", "Benjamin Graham"),
    ("Take care of the downside, and the upside will take care of itself.", "Anonymous market saying"),
    ("Capital preservation is the first job.", "Anonymous market saying"),
    ("Risk is what's left when you think you've accounted for everything.", "Carl Richards"),
    ("Plan for the worst, hope for the best, and accept what comes.", "Anonymous market saying"),
    ("It's not whether you're right or wrong that's important, but how much you make when you're right and how much you lose when you're wrong.", "George Soros"),
    ("I'm only rich because I know when I'm wrong. I basically have survived by recognizing my mistakes.", "George Soros"),
    ("I don't try to be right or wrong. I try to make money.", "Stanley Druckenmiller"),
    ("Letting losses run is the single most serious mistake made by most investors.", "William O'Neil"),
    ("Take your losses quickly and your profits slowly.", "Anonymous market saying"),
    ("A good trader does not fear being wrong.", "Anonymous market saying"),
    ("Losses are tuition.", "Anonymous market saying"),
    ("In trading, it's not about how often you're right — it's about how much you make when you are.", "George Soros"),
    ("Gold is money. Everything else is credit.", "J.P. Morgan"),
    ("When paper money systems begin to crack at the seams, the fault lines develop along the gold price.", "James Sinclair"),
    ("Gold has worked down from Alexander's time. When something holds good for two thousand years, I do not believe it can be so because of prejudice or mistaken theory.", "Bernard Baruch"),
    ("Gold doesn't pay interest. But it doesn't default either.", "Anonymous market saying"),
    ("Throughout history, gold has held its value when nothing else has.", "Anonymous market saying"),
    ("When all else fails, there's gold.", "Anonymous market saying"),
    ("Gold thrives on uncertainty.", "Anonymous market saying"),
    ("Paper currencies come and go. Gold endures.", "Anonymous market saying"),
    ("Be fearful when others are greedy, and greedy when others are fearful.", "Warren Buffett"),
    ("The intelligent investor is a realist who sells to optimists and buys from pessimists.", "Benjamin Graham"),
    ("Markets are never wrong — opinions are.", "Jesse Livermore"),
    ("Bulls make money, bears make money, pigs get slaughtered.", "Anonymous market saying"),
    ("The trend is your friend, until the end when it bends.", "Anonymous market saying"),
    ("Don't fight the tape.", "Anonymous Wall Street saying"),
    ("Don't fight the Fed.", "Martin Zweig"),
    ("What everybody knows isn't worth knowing.", "Bernard Baruch"),
    ("Don't confuse genius with a bull market.", "Humphrey Neill"),
    ("The crowd is usually wrong at extremes.", "Anonymous market saying"),
    ("If you don't know who you are, the markets are an expensive place to find out.", "George Goodman ('Adam Smith')"),
    ("The investor's chief problem — and even his worst enemy — is likely to be himself.", "Benjamin Graham"),
    ("The most important quality for an investor is temperament, not intellect.", "Warren Buffett"),
    ("Trading is a psychological game. Most people think they're playing against the market, but the market doesn't care. You're playing against yourself.", "Martin Schwartz"),
    ("The goal of a successful trader is to make the best trades. Money is secondary.", "Alexander Elder"),
    ("If you can keep your head when all about you are losing theirs… the world is yours.", "Rudyard Kipling"),
    ("Know yourself or the market will teach you.", "Anonymous market saying"),
    ("You can't control the market, but you can control yourself.", "Anonymous market saying"),
    ("Frankly, I don't see markets; I see risks, rewards, and money.", "Larry Hite"),
    ("Trading is a probability game, not a certainty game.", "Anonymous market saying"),
    ("Edge isn't predicting. Edge is process.", "Anonymous market saying"),
    ("Manage the trade, not the prediction.", "Anonymous market saying"),
    ("I want my edge, not my opinion, to drive my trades.", "Anonymous market saying"),
    ("Process produces results, not predictions.", "Anonymous market saying"),
    ("The best trades have fundamentals, technicals, and market tone all aligned.", "Michael Marcus"),
    ("All trades should have an edge before you take them.", "Anonymous market saying"),
    ("Compound interest is the eighth wonder of the world. He who understands it earns it; he who doesn't, pays it.", "Attributed to Albert Einstein"),
    ("Wealth is what you don't see.", "Morgan Housel"),
    ("The hardest financial skill is getting the goalpost to stop moving.", "Morgan Housel"),
    ("Saving is a hedge against life's unavoidable ability to surprise the hell out of you.", "Morgan Housel"),
    ("Money compounds for the patient and bleeds for the impatient.", "Anonymous market saying"),
    ("Small edges compound into large fortunes — given time.", "Anonymous market saying"),
    ("There is nothing new in Wall Street. There can't be, because speculation is as old as the hills.", "Jesse Livermore"),
    ("The market is a voting machine in the short run and a weighing machine in the long run.", "Benjamin Graham"),
    ("Know what you own, and know why you own it.", "Peter Lynch"),
    ("Cut your losses short, let your winners run — both rules require courage.", "Anonymous market saying"),
    ("There is no means of avoiding the final collapse of a boom brought about by credit expansion.", "Ludwig von Mises"),
    ("A bull market is like sex — it feels best just before it ends.", "Barton Biggs"),
    ("The market is a great teacher — its lessons are expensive but unforgettable.", "Anonymous market saying"),
    ("Survive first. Profit second.", "Anonymous market saying"),
    ("The market will always be there tomorrow.", "Anonymous market saying"),
    ("The best traders aren't smarter than the rest. They're more disciplined.", "Anonymous market saying"),
]


# ----------------------------------------------------------------------
# Data loaders
# ----------------------------------------------------------------------

def load_from_closed_csv():
    """Read the bot's own closed_trades.csv (post-Jun-11). Returns list of trade dicts or []."""
    if not CLOSED_CSV.exists():
        return []
    out = []
    with open(CLOSED_CSV, "r", encoding="utf-8", newline="") as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            try:
                out.append({
                    "dt":      datetime.fromisoformat(r["ts_close_utc"].replace("Z", "+00:00")),
                    "net":     float(r["net_pl"]),
                    "balance": float(r["balance_after"]),
                })
            except Exception:
                continue
    out.sort(key=lambda t: t["dt"])
    return out


def load_from_xlsx():
    """Read the newest cTrader XLSX export. Returns list of trade dicts or []."""
    try:
        import openpyxl
    except ImportError:
        return []
    xlsx_files = sorted(XLSX_DIR.glob("cT_*_*.xlsx"))
    if not xlsx_files:
        return []
    latest = xlsx_files[-1]
    out = []
    wb = openpyxl.load_workbook(latest, data_only=True)
    ws = wb["Records"]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        try:
            symbol, direction, close_time, entry, close, qty, vol, net, balance = row
            dt = datetime.strptime(close_time, "%d/%m/%Y %H:%M:%S.%f")
            out.append({
                "dt":      dt.replace(tzinfo=timezone.utc),
                "net":     float(net),
                "balance": float(balance),
            })
        except Exception:
            continue
    out.sort(key=lambda t: t["dt"])
    return out


def load_manual_balance():
    """Read the optional manual_balance.json. Returns dict with parsed asof datetime, or None.

    Schema: {"current_balance": 19100.0, "asof": "2026-06-28T20:30:00Z", "note": "..."}
    Used when bot logs are stale (weekend / post-20:00-SAST closes) — Daniel sets the live
    balance manually and the website reflects it instead of the last CSV trade.
    """
    if not MANUAL_BALANCE.exists():
        return None
    try:
        with open(MANUAL_BALANCE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        balance = float(data["current_balance"])
        asof_str = str(data["asof"]).replace("Z", "+00:00")
        asof_dt  = datetime.fromisoformat(asof_str)
        if asof_dt.tzinfo is None:
            asof_dt = asof_dt.replace(tzinfo=timezone.utc)
        return {"current_balance": balance, "asof": asof_dt, "note": data.get("note", "")}
    except Exception as e:
        print(f"  [warn] manual_balance.json invalid, ignoring: {e}")
        return None


def merge_sources(closed, xlsx):
    """Combine closed-CSV (canonical going forward) with XLSX (historical backfill).

    Strategy: use XLSX for trades dated <= the earliest ts in closed_csv, plus all
    closed_csv trades. If closed_csv is empty, return XLSX. If XLSX is empty, return closed.
    """
    if not closed:
        return xlsx
    if not xlsx:
        return closed
    cutoff = closed[0]["dt"]
    historical = [t for t in xlsx if t["dt"] < cutoff]
    return historical + closed


# ----------------------------------------------------------------------
# Stats computation
# ----------------------------------------------------------------------

def compute_stats(trades, manual=None):
    """Return a dict of stat strings ready for HTML substitution.

    `manual` (optional): dict from load_manual_balance(). When its `asof` is newer than
    the last CSV trade, its `current_balance` overrides the displayed end balance — so
    weekend manual closes show on the site without waiting for the bot to log them.
    Win rate / trade count / profit factor are NEVER touched (those need real trade rows).
    """
    if not trades:
        return None

    start_balance = trades[0]["balance"] - trades[0]["net"]
    end_balance   = trades[-1]["balance"]
    using_manual  = manual is not None and manual["asof"] > trades[-1]["dt"]
    if using_manual:
        end_balance = manual["current_balance"]
    total_return_pct = (end_balance - start_balance) / start_balance * 100 if start_balance > 0 else 0.0

    wins   = sum(1 for t in trades if t["net"] > 0)
    losses = sum(1 for t in trades if t["net"] < 0)
    win_rate = wins / len(trades) * 100 if trades else 0.0

    gross_profit = sum(t["net"] for t in trades if t["net"] > 0)
    gross_loss   = sum(t["net"] for t in trades if t["net"] < 0)
    pf = (gross_profit / abs(gross_loss)) if gross_loss < 0 else float("inf")

    today = datetime.now(timezone.utc).date()
    # ISO week boundaries
    weekday = today.weekday()                 # Mon=0
    week_start = today - timedelta(days=weekday)
    prev_week_start = week_start - timedelta(days=7)
    prev_week_end   = week_start - timedelta(days=1)

    def slice_pct(group, eb_override=None):
        if not group: return None
        sb = group[0]["balance"] - group[0]["net"]
        eb = eb_override if eb_override is not None else group[-1]["balance"]
        return (eb - sb) / sb * 100 if sb > 0 else 0.0

    this_week = [t for t in trades if t["dt"].date() >= week_start]
    last_week = [t for t in trades if prev_week_start <= t["dt"].date() <= prev_week_end]

    # If the manual override is in this-week, use it as the week's ending balance too,
    # so "Week so far" matches the headline total.
    this_week_eb = manual["current_balance"] if (using_manual and manual["asof"].date() >= week_start) else None
    this_week_pct = slice_pct(this_week, this_week_eb)
    last_week_pct = slice_pct(last_week)

    days_live = (today - LAUNCH_DATE).days + 1
    last_updated = datetime.now(timezone.utc).strftime("%b %d, %Y · %H:%M UTC")

    def pct_str(v, signed=True):
        if v is None: return "—"
        return f"{v:+.1f}%" if signed else f"{v:.1f}%"

    return {
        "total-return":  pct_str(total_return_pct),
        "trade-count":   str(len(trades)),
        "days-live":     str(days_live),
        "win-rate":      f"{win_rate:.1f}%",
        "wins":          str(wins),
        "losses":        str(losses),
        "profit-factor": f"{pf:.2f}" if pf != float("inf") else "∞",
        "this-week":     pct_str(this_week_pct) if this_week_pct is not None else "—",
        "last-week":     pct_str(last_week_pct) if last_week_pct is not None else "—",
        "last-updated":  last_updated,
        "since-label":   f"Since launch · {LAUNCH_DATE.strftime('%b %#d, %Y')}",
    }


# ----------------------------------------------------------------------
# Quote rotation + today-session + daily-post generation (Telegram-ready)
# ----------------------------------------------------------------------

def pick_quote():
    """Return (quote, author). Skips any used in the last 14 days. Persists
    history to bot_log/quote_history.json so the no-repeat rule survives runs."""
    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=QUOTE_NOREPEAT_DAYS)

    history = {"used": []}
    if QUOTE_HISTORY.exists():
        try:
            with open(QUOTE_HISTORY, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = {"used": []}

    recently_used = set()
    for e in history.get("used", []):
        try:
            if date.fromisoformat(e["date"]) >= cutoff:
                recently_used.add(int(e["index"]))
        except Exception:
            continue

    available = [i for i in range(len(QUOTES)) if i not in recently_used]
    if not available:
        available = list(range(len(QUOTES)))   # fallback if all 90 somehow used

    # Deterministic per-day pick: same date -> same quote even if rerun
    random.seed(int(today.strftime("%Y%m%d")))
    idx = random.choice(available)

    # Save history (de-dupe today's entry if rerun, prune > 60 days)
    used = [e for e in history.get("used", []) if e.get("date") != today.isoformat()]
    used.append({"index": idx, "date": today.isoformat()})
    cutoff_60 = today - timedelta(days=60)
    used = [e for e in used if date.fromisoformat(e["date"]) >= cutoff_60]
    history["used"] = used
    try:
        BOT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(QUOTE_HISTORY, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception:
        pass

    return QUOTES[idx]


def compute_today_session(trades):
    """Stats for trades closed today (UTC). Returns dict or None if no closures."""
    today = datetime.now(timezone.utc).date()
    today_trades = [t for t in trades if t["dt"].date() == today]
    if not today_trades:
        return None
    wins   = sum(1 for t in today_trades if t["net"] > 0)
    losses = sum(1 for t in today_trades if t["net"] < 0)
    sb     = today_trades[0]["balance"] - today_trades[0]["net"]
    eb     = today_trades[-1]["balance"]
    day_pct = (eb - sb) / sb * 100 if sb > 0 else 0.0
    return {
        "count":    len(today_trades),
        "wins":     wins,
        "losses":   losses,
        "win_rate": wins / len(today_trades) * 100,
        "day_pct":  day_pct,
    }


def pick_commentary(session):
    """One short paragraph matching the day's character. No forced line breaks."""
    if session is None:
        return ("No closures today — patience over forcing. Sometimes the best "
                "trade is no trade. The strategy waits for setups that meet its "
                "criteria and skips the rest.")
    wins, losses, day_pct = session["wins"], session["losses"], session["day_pct"]
    if losses == 0:
        return ("A clean session. Every entry hit profit. Selectivity over volume "
                "— quality over quantity. Exactly the rhythm the strategy is built for.")
    if wins == 0:
        return ("A tough session — losses are priced into the strategy by design. "
                "The discipline is in sticking to the plan when drawdowns hit, not "
                "in dodging every loss.")
    if day_pct >= 0:
        return ("A balanced session — wins and losses both reported. The strategy "
                "is built for this rhythm: not every trade wins, but the math works "
                "out when you stay disciplined.")
    return ("A mixed session, finishing slightly red. The strategy doesn't dodge "
            "volatility — it manages through it. Tomorrow's setups will speak for "
            "themselves.")


def generate_daily_post(stats, session, quote):
    """Return the complete Telegram-ready post as a string with all emojis."""
    today = datetime.now(timezone.utc)
    try:
        date_str = today.strftime("%b %#d")   # Windows: no leading zero
    except Exception:
        date_str = today.strftime("%b %d")    # POSIX fallback

    if session is None:
        session_block = ("🕯️ Today's session\n"
                         "• 0 trades closed\n"
                         "• Day: 0.00%")
    else:
        s = session
        session_block = (f"🕯️ Today's session\n"
                         f"• {s['count']} trades closed\n"
                         f"• {s['wins']} wins · {s['losses']} losses\n"
                         f"• Win rate: {s['win_rate']:.0f}%\n"
                         f"• Day: {s['day_pct']:+.2f}%")

    quote_text, quote_author = quote
    commentary = pick_commentary(session)

    return (
        f"📊 TIMETOSHINE — Daily Recap ({date_str})\n"
        f"\n"
        f"{session_block}\n"
        f"\n"
        f"{commentary}\n"
        f"\n"
        f"📅 Zoom out:\n"
        f"• Week so far: {stats['this-week']}\n"
        f"• Last week: {stats['last-week']}\n"
        f"• Since launch (Jun 1): {stats['total-return']}\n"
        f"• Overall win rate: {stats['win-rate']}\n"
        f"• Profit factor: {stats['profit-factor']}\n"
        f"\n"
        f"💬 \"{quote_text}\"\n"
        f"   — {quote_author}\n"
        f"\n"
        f"🔍 Verify everything live:\n"
        f"myfxbook.com/members/TIMETOSHINE8/timetoshine/12071554\n"
        f"\n"
        f"🌐 Full strategy & live stats:\n"
        f"timetoshineofficial.com\n"
        f"\n"
        f"📈 Copy on cTrader (free, 2 clicks):\n"
        f"ct.spotware.com/copy/strategy/117861\n"
    )


def write_daily_post(post_text):
    """Save the post (UTF-8, no BOM) so Netlify can serve it as plain text."""
    try:
        DAILY_POST_TXT.write_text(post_text, encoding="utf-8")
        print(f"  -> wrote {DAILY_POST_TXT}")
    except Exception as e:
        print(f"  [error] daily post write failed: {e}")


def send_telegram_post(post_text):
    """Push the daily post to Daniel's private Telegram chat. Silent if config
    missing; logs failures but never raises so the pipeline can't break here."""
    if not TELEGRAM_CONFIG.exists():
        return
    try:
        with open(TELEGRAM_CONFIG, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        token   = (cfg.get("bot_token") or "").strip()
        chat_id = str(cfg.get("chat_id") or "").strip()
        if not token or not chat_id:
            print("  [telegram] config exists but missing token or chat_id")
            return

        import urllib.request
        import urllib.parse
        import ssl
        # SSL: server has corporate proxy doing inspection (self-signed cert in chain).
        # api.telegram.org is a fixed trusted endpoint -> disable verification is fine here.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": post_text,
            "disable_web_page_preview": "true",
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            result = json.loads(body)
            if result.get("ok"):
                msg_id = result["result"]["message_id"]
                print(f"  -> Telegram delivered (msg_id: {msg_id})")
            else:
                print(f"  [telegram] API rejected: {body[:300]}")
    except Exception as e:
        print(f"  [telegram] send failed: {e}")


# ----------------------------------------------------------------------
# Equity-curve SVG (cumulative % growth, gold gradient)
# ----------------------------------------------------------------------

def generate_equity_svg(trades, manual=None):
    """Inline SVG: % growth from starting capital, weekly dots, big % callout. No $ shown.

    If `manual` is newer than the last trade, append a final point so the curve ends at
    the live balance (otherwise the chart endpoint would disagree with the headline %).
    """
    if not trades or len(trades) < 2:
        return '<svg viewBox="0 0 800 320" xmlns="http://www.w3.org/2000/svg"><text x="400" y="160" fill="#8b9bb0" font-size="14" text-anchor="middle">Building equity curve — needs more closed trades.</text></svg>'

    start_bal = trades[0]["balance"] - trades[0]["net"]
    if start_bal <= 0:
        return '<svg viewBox="0 0 800 320" xmlns="http://www.w3.org/2000/svg"></svg>'
    series = [(t["dt"], (t["balance"] - start_bal) / start_bal * 100) for t in trades]
    if manual is not None and manual["asof"] > trades[-1]["dt"]:
        manual_pct = (manual["current_balance"] - start_bal) / start_bal * 100
        series.append((manual["asof"], manual_pct))

    # SVG geometry
    W, H = 800, 320
    L, R, T, B = 70, 30, 60, 50
    pw, ph = W - L - R, H - T - B
    t0, t1 = series[0][0], series[-1][0]
    t_range = (t1 - t0).total_seconds() or 1
    def x_at(dt):  return L + (dt - t0).total_seconds() / t_range * pw
    pcts = [p for _, p in series]
    y_max = max(pcts) * 1.10 if max(pcts) > 0 else 5.0
    y_min = min(0.0, min(pcts) * 1.10)
    y_range = (y_max - y_min) or 1.0
    def y_at(p):   return T + (1 - (p - y_min) / y_range) * ph

    # Paths
    pts = [(x_at(dt), y_at(p)) for dt, p in series]
    line_d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area_d = line_d + f" L {pts[-1][0]:.1f},{y_at(0):.1f} L {pts[0][0]:.1f},{y_at(0):.1f} Z"

    # Weekly markers — one dot per ISO week
    seen, week_dots = set(), []
    for (dt, p), (x, y) in zip(series, pts):
        wk = (dt.isocalendar().year, dt.isocalendar().week)
        if wk in seen: continue
        seen.add(wk); week_dots.append((x, y))

    # Y-axis grid
    step = 20 if max(pcts) > 40 else (10 if max(pcts) > 20 else 5)
    grid_lines, grid_labels = [], []
    v = 0
    while v <= y_max + step:
        y = y_at(v)
        if T - 5 < y < (T + ph + 5):
            grid_lines.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W-R}" y2="{y:.1f}" stroke="rgba(255,255,255,0.05)" stroke-dasharray="2,3"/>')
            grid_labels.append(f'<text x="{L-8}" y="{y+4:.1f}" fill="#8b9bb0" font-size="11" text-anchor="end">+{v}%</text>')
        v += step

    cur_pct = series[-1][1]
    fx, fy = pts[-1]

    # Callout (top-left of plot area)
    cx, cy = L + 12, T - 2
    parts = [
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet">',
        '<defs><linearGradient id="eqFill" x1="0%" y1="0%" x2="0%" y2="100%">',
        '<stop offset="0%" stop-color="#d4af37" stop-opacity="0.35"/>',
        '<stop offset="100%" stop-color="#d4af37" stop-opacity="0"/></linearGradient></defs>',
        *grid_lines, *grid_labels,
        f'<path d="{area_d}" fill="url(#eqFill)"/>',
        f'<path d="{line_d}" stroke="#d4af37" stroke-width="2.5" fill="none" stroke-linejoin="round" stroke-linecap="round"/>',
    ]
    for x, y in week_dots[1:-1]:
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#0a0e14" stroke="#d4af37" stroke-width="2"/>')
    parts.append(f'<circle cx="{fx:.1f}" cy="{fy:.1f}" r="14" fill="#d4af37" fill-opacity="0.18"/>')
    parts.append(f'<circle cx="{fx:.1f}" cy="{fy:.1f}" r="6" fill="#d4af37"/>')

    parts.append(f'<text x="{cx}" y="{cy}" fill="#8b9bb0" font-size="11" font-weight="700" letter-spacing="2.5">TOTAL GROWTH</text>')
    parts.append(f'<text x="{cx}" y="{cy+44}" fill="#d4af37" font-size="42" font-weight="900" letter-spacing="-1">{cur_pct:+.2f}%</text>')
    try:
        since = t0.strftime("%b %#d, %Y")
    except Exception:
        since = t0.strftime("%b %d, %Y")
    parts.append(f'<text x="{cx}" y="{cy+62}" fill="#8b9bb0" font-size="11">since {since}</text>')

    # X-axis edge labels
    parts.append(f'<text x="{L}" y="{H-18}" fill="#8b9bb0" font-size="10">{t0.strftime("%b %#d" if hasattr(t0, "strftime") else "%b %d")}</text>')
    parts.append(f'<text x="{W-R}" y="{H-18}" fill="#8b9bb0" font-size="10" text-anchor="end">{t1.strftime("%b %#d" if hasattr(t1, "strftime") else "%b %d")}</text>')

    parts.append('</svg>')
    return "".join(parts)


# ----------------------------------------------------------------------
# FTP upload to Afrihost (deploys the site to timetoshineofficial.com)
# ----------------------------------------------------------------------

def ftp_deploy(files):
    """Upload given local paths to /public_html on the Afrihost FTP server.
    Silent failure-tolerant — never raises so the pipeline can't break here."""
    if not FTP_CONFIG.exists():
        print("  [ftp] no config; skipping upload")
        return False
    try:
        with open(FTP_CONFIG, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        host = cfg.get("host") or cfg.get("ftp_host")
        user = cfg.get("user") or cfg.get("ftp_user")
        pwd  = cfg.get("password") or cfg.get("ftp_password")
        root = cfg.get("web_root", "/public_html")
        if not host or not user or not pwd:
            print("  [ftp] config missing host/user/password")
            return False
        import ftplib
        ftp = ftplib.FTP(host, timeout=60)
        ftp.login(user, pwd)
        ftp.cwd(root)
        for local_path in files:
            local_path = Path(local_path)
            if not local_path.exists():
                print(f"  [ftp] skip (missing): {local_path}")
                continue
            with open(local_path, "rb") as fh:
                ftp.storbinary(f"STOR {local_path.name}", fh)
            print(f"  -> FTP: {local_path.name} ({local_path.stat().st_size} bytes)")
        ftp.quit()
        return True
    except Exception as e:
        print(f"  [ftp] deploy failed: {e}")
        return False


# ----------------------------------------------------------------------
# HTML rewrite
# ----------------------------------------------------------------------

def rewrite_html(stats, trades=None, manual=None):
    html = INDEX_HTML.read_text(encoding="utf-8")

    for key, value in stats.items():
        # Replace any <... data-stat="key">OLD_CONTENT</...> with the new value
        pattern = re.compile(
            r'(<[^>]*\bdata-stat="' + re.escape(key) + r'"[^>]*>)[^<]*(</[^>]+>)'
        )
        new_html, n = pattern.subn(lambda m: m.group(1) + value + m.group(2), html)
        if n == 0:
            print(f"  [warn] no element matched data-stat=\"{key}\"")
        html = new_html

    # Inject the equity curve SVG between the markers
    if trades:
        svg = generate_equity_svg(trades, manual=manual)
        svg_pattern = re.compile(r'<!--EQUITY_SVG_START-->.*?<!--EQUITY_SVG_END-->', re.DOTALL)
        replacement = f'<!--EQUITY_SVG_START-->{svg}<!--EQUITY_SVG_END-->'
        new_html, n = svg_pattern.subn(replacement, html)
        if n == 0:
            print("  [warn] EQUITY_SVG markers not found in HTML")
        else:
            html = new_html
            print(f"  -> equity SVG injected ({len(svg)} bytes)")

    INDEX_HTML.write_text(html, encoding="utf-8")
    print(f"  -> wrote {INDEX_HTML}")


# ----------------------------------------------------------------------
# Optional: git auto-deploy
# ----------------------------------------------------------------------

def git_push():
    import subprocess
    import shutil
    # git isn't always on PATH on this server; fall back to the known install location
    git_exe = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"
    if not Path(git_exe).exists():
        print(f"  [warn] git not found (tried PATH and {git_exe}); skipping push")
        return
    try:
        subprocess.run([git_exe, "-C", str(HERE), "add", "index.html", "daily_post.txt"], check=True)
        msg = f"auto: stats refresh {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        # Only commit if there's actually something staged
        diff = subprocess.run([git_exe, "-C", str(HERE), "diff", "--cached", "--quiet"])
        if diff.returncode == 0:
            print("  -> no changes to commit")
            return
        subprocess.run([git_exe, "-C", str(HERE), "commit", "-m", msg], check=True)
        subprocess.run([git_exe, "-C", str(HERE), "push"], check=True)
        print("  -> pushed to GitHub (Netlify will redeploy)")
    except subprocess.CalledProcessError as e:
        print(f"  [error] git push failed: {e}")


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():
    print(f"[{datetime.now(timezone.utc).isoformat()}] updating promo stats")

    closed = load_from_closed_csv()
    xlsx   = load_from_xlsx()
    trades = merge_sources(closed, xlsx)

    if not trades:
        print("  [error] no trade data found in either source")
        sys.exit(1)

    print(f"  loaded {len(trades)} trades ({'closed_csv: '+str(len(closed))}, xlsx: {len(xlsx)})")

    manual = load_manual_balance()
    if manual:
        last_dt = trades[-1]["dt"]
        if manual["asof"] > last_dt:
            ago = datetime.now(timezone.utc) - manual["asof"]
            hrs = ago.total_seconds() / 3600
            print(f"  manual balance OVERRIDE active: ${manual['current_balance']:,.2f} "
                  f"(set {hrs:.1f}h ago, after last bot trade)")
        else:
            print(f"  manual balance file present but older than last bot trade — ignored")
            manual = None
    else:
        print("  no manual balance override")

    stats = compute_stats(trades, manual=manual)
    if not stats:
        print("  [error] stats compute returned nothing")
        sys.exit(1)

    print("  computed:")
    for k, v in stats.items():
        print(f"    {k:14} = {v}")

    rewrite_html(stats, trades=trades, manual=manual)

    # Regenerate the OG image daily with current stats baked in
    try:
        from build_assets import build_og_image
        build_og_image(stats)
    except Exception as e:
        print(f"  [og] regen failed: {e}")

    # Cache-bust og:image / twitter:image across all pages so Telegram/iMessage
    # actually re-fetch the freshly regenerated PNG (they cache aggressively by URL).
    today_stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    og_pages = [INDEX_HTML, HERE/"about.html", HERE/"how-to-copy.html",
                HERE/"faq.html", HERE/"contact.html", HERE/"404.html"]
    og_url_pattern = re.compile(
        r'(content="https://timetoshineofficial\.com/og-image\.png)(\?[^"]*)?(")'
    )
    n_total = 0
    for page in og_pages:
        if not page.exists(): continue
        h = page.read_text(encoding="utf-8")
        new_h, n = og_url_pattern.subn(rf'\1?v={today_stamp}\3', h)
        if n > 0:
            page.write_text(new_h, encoding="utf-8")
            n_total += n
    print(f"  -> og:image cache-busted in {n_total} tag(s) (?v={today_stamp})")

    # Telegram-ready daily post: rotating quote + today's session + zoom-out + CTAs.
    quote   = pick_quote()
    session = compute_today_session(trades)
    post    = generate_daily_post(stats, session, quote)
    write_daily_post(post)
    print(f"  -> quote used: \"{quote[0][:50]}...\" — {quote[1]}")
    send_telegram_post(post)

    # Deploy to Afrihost via FTP (the live host for timetoshineofficial.com)
    print("  Deploying to Afrihost...")
    ftp_deploy([
        INDEX_HTML,
        HERE / "about.html",
        HERE / "how-to-copy.html",
        HERE / "faq.html",
        HERE / "contact.html",
        HERE / "404.html",
        DAILY_POST_TXT,
        HERE / "TIMETOSHINE_logo.svg",
        HERE / "favicon-16x16.png",
        HERE / "favicon-32x32.png",
        HERE / "apple-touch-icon.png",
        HERE / "icon-512.png",
        HERE / "og-image.png",
        HERE / "manifest.json",
        HERE / "sitemap.xml",
        HERE / "robots.txt",
        HERE / ".htaccess",
    ])

    if GIT_AUTO_PUSH:
        git_push()

    print("done.")


if __name__ == "__main__":
    main()
