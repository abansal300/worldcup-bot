import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from client import KalshiClient
from executor import Executor
from strategy import evaluate_market, WORLD_CUP_SERIES
from goals_bot import run_goals_cycle

PROJECT_ROOT = Path(__file__).parent.parent


def _load_private_key() -> str:
    # Cloud deployments set KALSHI_PRIVATE_KEY_CONTENTS with the raw PEM text.
    # Local dev uses KALSHI_PRIVATE_KEY_PATH pointing to a file.
    contents = os.getenv("KALSHI_PRIVATE_KEY_CONTENTS", "").strip()
    if contents:
        return contents

    path_str = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")
    if not path_str:
        sys.exit("Set KALSHI_PRIVATE_KEY_CONTENTS (cloud) or KALSHI_PRIVATE_KEY_PATH (local)")

    key_path = Path(path_str).expanduser()
    if not key_path.is_absolute():
        key_path = PROJECT_ROOT / key_path
    if not key_path.exists():
        sys.exit(f"Private key not found: {key_path}")

    return key_path.read_text()


def load_config() -> dict:
    if not os.getenv("KALSHI_API_KEY_ID"):
        sys.exit("Missing required env var: KALSHI_API_KEY_ID")

    return {
        "api_key_id": os.environ["KALSHI_API_KEY_ID"],
        "private_key_pem": _load_private_key(),
        "edge_threshold": float(os.getenv("EDGE_THRESHOLD", "0.05")),
        "kelly_fraction": float(os.getenv("KELLY_FRACTION", "0.25")),
        "max_position_dollars": float(os.getenv("MAX_POSITION_DOLLARS", "50")),
        "max_total_exposure": float(os.getenv("MAX_TOTAL_EXPOSURE_DOLLARS", "500")),
        "dry_run": os.getenv("DRY_RUN", "true").lower() != "false",
        "poll_interval": int(os.getenv("POLL_INTERVAL_SECONDS", "60")),
    }


def run_cycle(client: KalshiClient, executor: Executor, cfg: dict) -> None:
    print("Fetching open markets...")
    markets = client.get_markets(
        status="open", limit=200, series_ticker=WORLD_CUP_SERIES
    )
    print(f"  {len(markets)} markets fetched")

    # ELO pre-match strategy
    bankroll = client.get_balance()
    signals_found = 0
    for market in markets:
        signal = evaluate_market(
            market,
            edge_threshold=cfg["edge_threshold"],
            kelly_fraction=cfg["kelly_fraction"],
            bankroll=bankroll,
            max_position_dollars=cfg["max_position_dollars"],
        )
        if signal:
            signals_found += 1
            executor.execute(signal)
    print(f"  {signals_found} ELO signal(s) found")

    # Live goals strategy (only fires when matches are in the trade window)
    print("Checking live goals markets...")
    run_goals_cycle(client, executor, cfg, markets)


def main() -> None:
    cfg = load_config()

    print("=== Kalshi World Cup Bot ===")
    print(f"  DRY_RUN     : {cfg['dry_run']}")
    print(f"  Edge thresh : {cfg['edge_threshold']:.0%}")
    print(f"  Kelly frac  : {cfg['kelly_fraction']:.0%}")
    print(f"  Max position: ${cfg['max_position_dollars']:.0f}")
    print(f"  Max exposure: ${cfg['max_total_exposure']:.0f}")
    print(f"  Poll interval: {cfg['poll_interval']}s")
    print()

    client = KalshiClient(cfg["api_key_id"], cfg["private_key_pem"])

    balance = client.get_balance()
    print(f"Account balance: ${balance:.2f}\n")

    executor = Executor(
        client,
        dry_run=cfg["dry_run"],
        max_total_exposure=cfg["max_total_exposure"],
    )

    while True:
        print(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
        try:
            run_cycle(client, executor, cfg)
        except Exception as e:
            print(f"  ERROR: {e}")
        print(f"Sleeping {cfg['poll_interval']}s...\n")
        time.sleep(cfg["poll_interval"])


if __name__ == "__main__":
    main()
