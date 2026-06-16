"""
Backtest: at minute 75, bet UNDER (current_total + 2.5) goals.

One bet per match. At 75 min the calibrated model gives ~89% probability
that fewer than 3 more goals are scored — based on the 2.1× late-game
Poisson rate fitted to the first 16 WC 2026 matches.

We sweep market prices from 50¢ to 85¢ so you can see at what price the
strategy is still profitable.
"""

import sys
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from goals_model import prob_under, LATE_GAME_MULTIPLIER

TRADE_MINUTE   = 75
ADDED_TIME     = 4.0
BET_DOLLARS    = 10.0
BUFFER         = 2.5   # "under current_total + 2.5" — needs 3+ more goals to lose

ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={}"
ESPN_BOARD   = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates={}"
WC_DATES     = ["20260611", "20260612", "20260613", "20260614", "20260615"]

PRICE_SCENARIOS = [0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def fetch_all_matches() -> list[dict]:
    matches = []
    for date in WC_DATES:
        data = requests.get(ESPN_BOARD.format(date), timeout=10).json()
        for event in data.get("events", []):
            comp = event["competitions"][0]
            if comp["status"]["type"]["name"] != "STATUS_FULL_TIME":
                continue
            home_c = next(c for c in comp["competitors"] if c.get("homeAway") == "home")
            away_c = next(c for c in comp["competitors"] if c.get("homeAway") == "away")
            matches.append({
                "id": event["id"],
                "date": date,
                "home": home_c["team"]["displayName"],
                "away": away_c["team"]["displayName"],
                "final_total": int(home_c.get("score", 0)) + int(away_c.get("score", 0)),
            })
    return matches


def fetch_goal_minutes(event_id: str) -> list[int]:
    data = requests.get(ESPN_SUMMARY.format(event_id), timeout=10).json()
    mins = []
    for item in data.get("commentary", []):
        play = item.get("play", {})
        if play.get("type", {}).get("type", "") in ("goal", "own-goal"):
            disp = play.get("clock", {}).get("displayValue", "")
            secs = play.get("clock", {}).get("value", 0)
            try:
                mins.append(int(disp.replace("'", "").split("+")[0].strip()))
            except (ValueError, AttributeError):
                mins.append(int(secs // 60))
    return sorted(mins)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    mins_left   = 90 + ADDED_TIME - TRADE_MINUTE   # 19 min
    model_prob  = prob_under(0, BUFFER, mins_left, current_minute=TRADE_MINUTE)
    # model_prob is the same regardless of current_total because we always bet
    # current_total + 2.5 — the BUFFER above means we need 3+ more goals to lose,
    # so current_total cancels out and the prob is purely a function of mins_left.

    print(f"Strategy : UNDER (score_at_75 + {BUFFER}) goals")
    print(f"Trigger  : minute {TRADE_MINUTE}, {mins_left:.0f} min remaining (incl. +{ADDED_TIME:.0f} added)")
    print(f"Model    : Poisson ×{LATE_GAME_MULTIPLIER} late-game rate  →  {model_prob:.1%} to win")
    print(f"Bet size : ${BET_DOLLARS:.0f} flat per match\n")

    print("Fetching match data...")
    matches = fetch_all_matches()
    print(f"  {len(matches)} completed matches\n")

    results = []
    for m in matches:
        try:
            goals = fetch_goal_minutes(m["id"])
        except Exception as e:
            print(f"  SKIP {m['home']} vs {m['away']}: {e}")
            continue

        total_at_75  = sum(1 for g in goals if g <= TRADE_MINUTE)
        line         = total_at_75 + BUFFER
        goals_after  = m["final_total"] - total_at_75
        won          = m["final_total"] < line   # final must stay under total_at_75 + 2.5

        results.append({
            "match":       f"{m['home']} vs {m['away']}",
            "at_75":       total_at_75,
            "final":       m["final_total"],
            "goals_after": goals_after,
            "line":        line,
            "won":         won,
        })

    # ------------------------------------------------------------------
    # Per-match table
    # ------------------------------------------------------------------
    print(f"{'Match':<35} {'At 75':>6} {'Final':>6} {'+Goals':>7} {'Line':>6} {'Result':>7}")
    print("-" * 72)
    for r in results:
        outcome = "WIN" if r["won"] else "LOSS"
        print(
            f"{r['match']:<35} {r['at_75']:>6} {r['final']:>6} "
            f"{r['goals_after']:>7} {'<'+str(r['line']):>6} {outcome:>7}"
        )

    wins   = sum(1 for r in results if r["won"])
    losses = len(results) - wins
    print(f"\n{'':35} {'':6} {'':6} {'':7} {'TOTAL':>6} {wins}W/{losses}L  ({wins/len(results):.0%})\n")

    # ------------------------------------------------------------------
    # P&L sweep across market prices
    # ------------------------------------------------------------------
    print(f"{'Market price':>14} {'Payout (win)':>13} {'EV/bet':>9} {'Total P&L':>11}  {'Verdict':}")
    print("-" * 62)
    for price in PRICE_SCENARIOS:
        payout_win  =  BET_DOLLARS / price * (1 - price)   # profit on a win
        payout_loss = -BET_DOLLARS
        total_pnl   = wins * payout_win + losses * payout_loss
        ev_per_bet  = model_prob * payout_win + (1 - model_prob) * payout_loss
        verdict     = "PROFITABLE" if total_pnl > 0 else "losing"
        print(
            f"  ${price:.2f} (buy at)  "
            f"  +${payout_win:>5.2f}/win   "
            f"  {ev_per_bet:>+.2f}   "
            f"  ${total_pnl:>+7.2f}    "
            f"  {verdict}"
        )

    # Break-even price
    # wins * (B/p)(1-p) = losses * B  →  (1-p)/p = losses/wins  →  p = wins/(wins+losses)
    be_price = wins / len(results)
    print(f"\n  Break-even market price: ${be_price:.2f}  (buy under this → strategy profitable)")
    print(f"  Actual win rate        : {wins}/{len(results)} = {wins/len(results):.1%}")
    print(f"  Model prediction       : {model_prob:.1%}")
    print(f"  Calibration gap        : {wins/len(results) - model_prob:+.1%}\n")

    # ------------------------------------------------------------------
    # Losses breakdown
    # ------------------------------------------------------------------
    losses_list = [r for r in results if not r["won"]]
    if losses_list:
        print("Losses (3+ goals scored after minute 75):")
        for r in losses_list:
            print(f"  {r['match']}: +{r['goals_after']} goals  ({r['at_75']} → {r['final']})")


if __name__ == "__main__":
    main()
