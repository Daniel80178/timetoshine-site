"""
TIMETOSHINE — manual balance override helper.

Usage:
    python set_balance.py <balance>             # write override + deploy site
    python set_balance.py <balance> --no-deploy # write override only
    python set_balance.py --clear               # remove override (revert to bot CSV)

Examples:
    python set_balance.py 19100        # set current balance to $19,100 + refresh website
    python set_balance.py 19100.50     # decimals are fine
    python set_balance.py --clear      # delete the override file

The override file (bot_log/manual_balance.json) is checked by update_stats.py on every
run. When its `asof` timestamp is newer than the most recent CSV trade, the website's
total-return % is computed from the manual balance instead of the (potentially stale)
last bot trade.
"""

from __future__ import annotations
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE   = Path(__file__).resolve().parent
TARGET = Path(r"C:\TradingBots\TIMETOSHINE\bot_log\manual_balance.json")


def usage_and_exit(code=1):
    print(__doc__.strip())
    sys.exit(code)


def write_override(balance: float, note: str = ""):
    payload = {
        "current_balance": round(balance, 2),
        "asof":            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note":            note or "Manual entry via set_balance.py",
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with open(TARGET, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"wrote manual balance: ${payload['current_balance']:,.2f}  asof {payload['asof']}")
    print(f"  -> {TARGET}")


def clear_override():
    if TARGET.exists():
        TARGET.unlink()
        print(f"cleared override: {TARGET}")
    else:
        print("no override file to clear")


def run_update():
    print()
    print("=" * 60)
    print("refreshing website (update_stats.py)...")
    print("=" * 60)
    rc = subprocess.run([sys.executable, str(HERE / "update_stats.py")]).returncode
    if rc != 0:
        print(f"\n[warn] update_stats.py exited with code {rc}")
    sys.exit(rc)


def main():
    args = sys.argv[1:]
    if not args:
        usage_and_exit()

    if args[0] in ("-h", "--help"):
        usage_and_exit(0)

    if args[0] == "--clear":
        clear_override()
        if "--no-deploy" not in args:
            run_update()
        return

    # Parse balance
    try:
        balance = float(args[0])
    except ValueError:
        print(f"error: '{args[0]}' is not a valid number")
        usage_and_exit()

    if balance <= 0:
        print(f"error: balance must be positive (got {balance})")
        sys.exit(1)

    note = ""
    if "--note" in args:
        i = args.index("--note")
        if i + 1 < len(args):
            note = args[i + 1]

    write_override(balance, note=note)

    if "--no-deploy" not in args:
        run_update()


if __name__ == "__main__":
    main()
