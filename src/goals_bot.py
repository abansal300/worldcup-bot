"""
Live total-goals strategy: trade Kalshi total-goals markets at ~75 min
based on current score + Poisson model for remaining time.
"""
import re
import time
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from client import KalshiClient
from executor import Executor
from live_scores import get_live_wc_matches
from goals_model import prob_over, prob_under, extract_line, is_over_market

# Trade in the final 15 minutes: enter at 75 min, stay active through final whistle
TRADE_WINDOW_MIN = int(os.getenv("GOALS_TRADE_MIN", "75"))
TRADE_WINDOW_MAX = int(os.getenv("GOALS_TRADE_MAX", "95"))  # covers extra time

# Estimated added time to account for injury time
ADDED_TIME_ESTIMATE = float(os.getenv("ADDED_TIME_ESTIMATE", "4"))

GOALS_EDGE_THRESHOLD = float(os.getenv("GOALS_EDGE_THRESHOLD", "0.05"))

# Minimum model probability required to place a bet (the "secure" threshold).
# At 75 min, ~0.43 goals are expected in remaining time, so UNDER bets on
# lines above the current score tend to hit 65-93% of the time.
MIN_MODEL_PROB = float(os.getenv("GOALS_MIN_PROB", "0.65"))


def minutes_remaining(current_minute: int) -> float:
    return max(0, 90 + ADDED_TIME_ESTIMATE - current_minute)


def team_in_title(title: str, team: str) -> bool:
    return team.lower() in title.lower()


def find_goals_markets(
    markets: list[dict], home_team: str, away_team: str
) -> list[dict]:
    """Find Kalshi total goals markets for a given match."""
    results = []
    for m in markets:
        title = m.get("title", "").lower()
        ticker = m.get("ticker", "").lower()
        text = title + " " + ticker

        # Must mention total goals
        is_goals = any(
            kw in text
            for kw in ("goal", "score", "total")
        )
        # Must mention both teams or have WC ticker
        mentions_teams = team_in_title(title, home_team) and team_in_title(title, away_team)
        is_wc_ticker = any(kw in ticker for kw in ("worldcup", "kxmen", "soccer", "fifa"))

        if is_goals and (mentions_teams or is_wc_ticker):
            results.append(m)

    return results


def evaluate_goals_market(
    market: dict,
    current_total: int,
    mins_remaining: float,
    edge_threshold: float,
    min_model_prob: float = 0.65,
    current_minute: int = 75,
) -> dict | None:
    """
    Returns a signal dict if there's edge AND the model confidence clears
    min_model_prob (the "secure bet" floor). None otherwise.
    Signal: {side, limit_price, model_prob, market_prob, edge, line, direction}
    """
    title = market.get("title", "")
    line = extract_line(title)
    if line is None:
        return None

    is_over = is_over_market(title)
    if is_over is None:
        return None

    yes_ask = market.get("yes_ask")
    no_ask = market.get("no_ask")
    if yes_ask is None or no_ask is None:
        return None

    if yes_ask > 1:
        yes_ask /= 100
        no_ask /= 100

    if is_over:
        model_yes_prob = prob_over(current_total, line, mins_remaining, current_minute)
    else:
        model_yes_prob = prob_under(current_total, line, mins_remaining, current_minute)

    yes_edge = model_yes_prob - yes_ask
    no_edge = (1.0 - model_yes_prob) - no_ask

    if yes_edge > edge_threshold and model_yes_prob >= min_model_prob:
        return {
            "side": "yes",
            "limit_price": yes_ask,
            "model_prob": model_yes_prob,
            "market_prob": yes_ask,
            "edge": yes_edge,
            "line": line,
            "direction": "over" if is_over else "under",
        }
    elif no_edge > edge_threshold and (1.0 - model_yes_prob) >= min_model_prob:
        return {
            "side": "no",
            "limit_price": no_ask,
            "model_prob": 1.0 - model_yes_prob,
            "market_prob": no_ask,
            "edge": no_edge,
            "line": line,
            "direction": "under" if is_over else "over",
        }

    return None


def kelly_contracts(
    model_prob: float,
    price: float,
    kelly_fraction: float,
    bankroll: float,
    max_dollars: float,
) -> int:
    if price <= 0 or price >= 1:
        return 0
    f = (model_prob - price) / (1.0 - price)
    if f <= 0:
        return 0
    dollar_bet = min(f * kelly_fraction * bankroll, max_dollars)
    return max(1, int(dollar_bet / price))


def run_goals_cycle(
    client: KalshiClient,
    executor: Executor,
    cfg: dict,
    all_markets: list[dict],
) -> None:
    matches = get_live_wc_matches()
    if not matches:
        print("  No live WC matches right now")
        return

    bankroll = client.get_balance()
    print(f"  Balance: ${bankroll:.2f}")

    for match in matches:
        minute = match["minute"]
        home = match["home_team"]
        away = match["away_team"]
        total = match["total_goals"]

        print(
            f"  Live: {home} {match['home_score']}-{match['away_score']} {away}  [{minute}']"
        )

        if not (TRADE_WINDOW_MIN <= minute <= TRADE_WINDOW_MAX):
            continue

        mins_left = minutes_remaining(minute)
        print(f"    In trade window! {mins_left:.0f} min remaining (incl. est. added time)")

        goals_markets = find_goals_markets(all_markets, home, away)
        if not goals_markets:
            print(f"    No total goals markets found on Kalshi for this match")
            continue

        for market in goals_markets:
            signal = evaluate_goals_market(
                market, total, mins_left, GOALS_EDGE_THRESHOLD,
                MIN_MODEL_PROB, minute,
            )
            if signal is None:
                continue

            contracts = kelly_contracts(
                signal["model_prob"],
                signal["limit_price"],
                cfg["kelly_fraction"],
                bankroll,
                cfg["max_position_dollars"],
            )
            if contracts < 1:
                continue

            print(f"    {total} goals at {minute}', {mins_left:.0f} min left")
            executor.execute_goals(market["ticker"], signal, contracts)


# --- Standalone entry point ---

def main() -> None:
    from main import load_config

    cfg = load_config()
    cfg["goals_edge"] = GOALS_EDGE_THRESHOLD

    print("=== Kalshi World Cup Goals Bot ===")
    print(f"  DRY_RUN       : {cfg['dry_run']}")
    print(f"  Trade window  : min {TRADE_WINDOW_MIN}-{TRADE_WINDOW_MAX}")
    print(f"  Added time est: +{ADDED_TIME_ESTIMATE} min")
    print(f"  Edge threshold: {GOALS_EDGE_THRESHOLD:.0%}")
    print()

    client = KalshiClient(cfg["api_key_id"], cfg["private_key_pem"])
    executor = Executor(client, dry_run=cfg["dry_run"], max_total_exposure=cfg["max_total_exposure"])

    print(f"Balance: ${client.get_balance():.2f}\n")

    poll = cfg["poll_interval"]

    while True:
        print(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
        try:
            all_markets = client.get_markets(status="open", limit=200)
            run_goals_cycle(client, executor, cfg, all_markets)
        except Exception as e:
            print(f"  ERROR: {e}")
        print(f"Sleeping {poll}s...\n")
        time.sleep(poll)


if __name__ == "__main__":
    main()
