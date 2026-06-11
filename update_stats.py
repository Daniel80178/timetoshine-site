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
import re
import sys
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

HERE          = Path(__file__).resolve().parent
INDEX_HTML    = HERE / "index.html"
BOT_LOG_DIR   = Path(r"C:\TradingBots\TIMETOSHINE\bot_log")
CLOSED_CSV    = BOT_LOG_DIR / "closed_trades.csv"
XLSX_DIR      = Path(r"C:\TradingBots\TIMETOSHINE_DEPLOY\myfxbook")

LAUNCH_DATE   = date(2026, 6, 1)

GIT_AUTO_PUSH = False  # flip to True once the GitHub repo is set up


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

def compute_stats(trades):
    """Return a dict of stat strings ready for HTML substitution."""
    if not trades:
        return None

    start_balance = trades[0]["balance"] - trades[0]["net"]
    end_balance   = trades[-1]["balance"]
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

    def slice_pct(group):
        if not group: return None
        sb = group[0]["balance"] - group[0]["net"]
        eb = group[-1]["balance"]
        return (eb - sb) / sb * 100 if sb > 0 else 0.0

    this_week = [t for t in trades if t["dt"].date() >= week_start]
    last_week = [t for t in trades if prev_week_start <= t["dt"].date() <= prev_week_end]

    this_week_pct = slice_pct(this_week)
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
# HTML rewrite
# ----------------------------------------------------------------------

def rewrite_html(stats):
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

    INDEX_HTML.write_text(html, encoding="utf-8")
    print(f"  -> wrote {INDEX_HTML}")


# ----------------------------------------------------------------------
# Optional: git auto-deploy
# ----------------------------------------------------------------------

def git_push():
    import subprocess
    try:
        subprocess.run(["git", "-C", str(HERE), "add", "index.html"], check=True)
        msg = f"auto: stats refresh {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        # Only commit if there's actually something staged
        diff = subprocess.run(["git", "-C", str(HERE), "diff", "--cached", "--quiet"])
        if diff.returncode == 0:
            print("  -> no changes to commit")
            return
        subprocess.run(["git", "-C", str(HERE), "commit", "-m", msg], check=True)
        subprocess.run(["git", "-C", str(HERE), "push"], check=True)
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

    stats = compute_stats(trades)
    if not stats:
        print("  [error] stats compute returned nothing")
        sys.exit(1)

    print("  computed:")
    for k, v in stats.items():
        print(f"    {k:14} = {v}")

    rewrite_html(stats)

    if GIT_AUTO_PUSH:
        git_push()

    print("done.")


if __name__ == "__main__":
    main()
