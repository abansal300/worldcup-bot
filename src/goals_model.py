import math

# 2026 World Cup average: ~2.6 goals per 90 min
WC_GOALS_PER_MINUTE = 2.6 / 90

# Calibrated from WC 2026 first 16 matches: 22 goals scored after minute 75
# across 16 matches (~19 min each) vs the model's expected 8.8. Empirical λ≈1.16
# for 19 min vs model's 0.55 → multiplier ≈ 2.1. Late-game teams press harder,
# defensive shape opens up, and fatigue sets in.
LATE_GAME_MINUTE = 75
LATE_GAME_MULTIPLIER = 2.1


def effective_rate(current_minute: int) -> float:
    """Goals per minute — elevated after LATE_GAME_MINUTE."""
    if current_minute >= LATE_GAME_MINUTE:
        return WC_GOALS_PER_MINUTE * LATE_GAME_MULTIPLIER
    return WC_GOALS_PER_MINUTE


def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam**k * math.exp(-lam)) / math.factorial(k)


def poisson_cdf(k: int, lam: float) -> float:
    """P(X <= k) for Poisson(lam)"""
    return sum(poisson_pmf(i, lam) for i in range(k + 1))


def prob_over(
    current_total: int,
    line: float,
    minutes_remaining: float,
    current_minute: int = 0,
) -> float:
    """P(final total goals > line) given current score and time left."""
    if current_total > line:
        return 1.0
    needed = math.ceil(line + 1) - current_total
    lam = effective_rate(current_minute) * minutes_remaining
    return 1.0 - poisson_cdf(needed - 1, lam)


def prob_under(
    current_total: int,
    line: float,
    minutes_remaining: float,
    current_minute: int = 0,
) -> float:
    """P(final total goals < line) given current score and time left."""
    if current_total >= line:
        return 0.0
    allowed = math.floor(line) - current_total
    lam = effective_rate(current_minute) * minutes_remaining
    return poisson_cdf(allowed, lam)


def extract_line(title: str) -> float | None:
    """
    Parse goal line from market title.
    Handles: "over 2.5 goals", "more than 2 goals", "at least 3 goals", "under 2.5"
    Returns the numeric line, or None if not found.
    """
    import re
    m = re.search(r"(\d+\.?\d*)\s*goals?", title, re.IGNORECASE)
    if m:
        return float(m.group(1))
    m = re.search(r"over\s+(\d+\.?\d*)", title, re.IGNORECASE)
    if m:
        return float(m.group(1))
    m = re.search(r"under\s+(\d+\.?\d*)", title, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


def is_over_market(title: str) -> bool | None:
    """Returns True for 'over', False for 'under', None if ambiguous."""
    title_lower = title.lower()
    has_over = any(w in title_lower for w in ("over", "more than", "at least", "exceed"))
    has_under = any(w in title_lower for w in ("under", "less than", "fewer"))
    if has_over and not has_under:
        return True
    if has_under and not has_over:
        return False
    return None
