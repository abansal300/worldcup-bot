from dataclasses import dataclass
from model import parse_teams_from_title, predict_match

WORLD_CUP_KEYWORDS = ["world cup", "worldcup", "fifa", "kxmenworldcup"]
WORLD_CUP_SERIES = "KXMENWORLDCUP"


@dataclass
class Signal:
    ticker: str
    title: str
    team_a: str
    team_b: str
    side: str           # "yes" or "no"
    limit_price: float  # dollars
    contracts: int
    model_prob: float
    market_prob: float
    edge: float


def is_world_cup_match_market(market: dict) -> bool:
    title = market.get("title", "").lower()
    ticker = market.get("ticker", "").lower()
    text = title + " " + ticker
    return any(kw in text for kw in WORLD_CUP_KEYWORDS)


def kelly_contracts(
    model_prob: float,
    price: float,           # price of the contract (dollars)
    kelly_fraction: float,
    bankroll: float,        # actual account balance — Kelly base
    max_dollars: float,     # hard cap per position
) -> tuple[int, float]:
    """
    Returns (contract_count, dollar_spent).
    Kelly criterion for binary prediction market:
      f* = (model_prob - price) / (1 - price)
      dollar_bet = min(f* * kelly_fraction * bankroll, max_dollars)
    """
    if price <= 0 or price >= 1:
        return 0, 0.0
    f = (model_prob - price) / (1.0 - price)
    if f <= 0:
        return 0, 0.0
    dollar_bet = min(f * kelly_fraction * bankroll, max_dollars)
    contracts = max(1, int(dollar_bet / price))
    actual_spend = contracts * price
    return contracts, actual_spend


def evaluate_market(
    market: dict,
    edge_threshold: float,
    kelly_fraction: float,
    bankroll: float,
    max_position_dollars: float,
) -> Signal | None:
    """
    Returns a Signal to act on, or None if no edge.
    """
    if not is_world_cup_match_market(market):
        return None

    title = market.get("title", "")
    teams = parse_teams_from_title(title)
    if teams is None:
        return None

    team_a, team_b = teams

    try:
        p_win_a, _p_draw, p_win_b = predict_match(team_a, team_b)
    except ValueError:
        return None

    # yes_ask = price to buy YES; no_ask = price to buy NO (in dollars)
    yes_ask = market.get("yes_ask")
    no_ask = market.get("no_ask")

    if yes_ask is None or no_ask is None:
        return None

    # Convert from cents to dollars if needed (Kalshi v2 post-March 2026 uses dollars)
    if yes_ask > 1:
        yes_ask /= 100
        no_ask /= 100

    # Determine which team the YES side refers to.
    # Market title usually names the favored/featured team first.
    # We assume YES = team_a wins for "Will [team_a] win?" style markets.
    # For "vs" style, YES typically = first-named team.
    yes_model_prob = p_win_a

    yes_edge = yes_model_prob - yes_ask
    no_edge = (1.0 - yes_model_prob) - no_ask  # model prob for NO outcome

    if yes_edge > edge_threshold:
        contracts, _ = kelly_contracts(yes_model_prob, yes_ask, kelly_fraction, bankroll, max_position_dollars)
        if contracts < 1:
            return None
        return Signal(
            ticker=market["ticker"],
            title=title,
            team_a=team_a,
            team_b=team_b,
            side="yes",
            limit_price=yes_ask,
            contracts=contracts,
            model_prob=yes_model_prob,
            market_prob=yes_ask,
            edge=yes_edge,
        )
    elif no_edge > edge_threshold:
        contracts, _ = kelly_contracts(1.0 - yes_model_prob, no_ask, kelly_fraction, bankroll, max_position_dollars)
        if contracts < 1:
            return None
        return Signal(
            ticker=market["ticker"],
            title=title,
            team_a=team_a,
            team_b=team_b,
            side="no",
            limit_price=no_ask,
            contracts=contracts,
            model_prob=1.0 - yes_model_prob,
            market_prob=no_ask,
            edge=no_edge,
        )

    return None
