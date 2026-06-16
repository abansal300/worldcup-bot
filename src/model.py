import json
import re
from pathlib import Path

_ELO: dict[str, float] | None = None

TEAM_ALIASES: dict[str, str] = {
    "usa": "United States",
    "united states": "United States",
    "us": "United States",
    "south korea": "South Korea",
    "republic of korea": "South Korea",
    "korea": "South Korea",
    "uae": "United Arab Emirates",
    "ivory coast": "Cote d'Ivoire",
    "côte d'ivoire": "Cote d'Ivoire",
}


def load_elo() -> dict[str, float]:
    global _ELO
    if _ELO is None:
        path = Path(__file__).parent.parent / "data" / "teams.json"
        with open(path) as f:
            _ELO = json.load(f)
    return _ELO


def normalize(name: str) -> str:
    return TEAM_ALIASES.get(name.lower().strip(), name.strip())


def elo_for(team: str) -> float | None:
    elo = load_elo()
    norm = normalize(team)
    return elo.get(norm) or elo.get(norm.title())


def predict_match(team_a: str, team_b: str) -> tuple[float, float, float]:
    """
    Returns (p_a_wins, p_draw, p_b_wins) using ELO + draw model.
    Raises ValueError if either team is unknown.
    """
    elo_a = elo_for(team_a)
    elo_b = elo_for(team_b)
    if elo_a is None:
        raise ValueError(f"Unknown team: {team_a}")
    if elo_b is None:
        raise ValueError(f"Unknown team: {team_b}")

    # ELO expected score (1=win, 0.5=draw, 0=loss) — encodes draw probability
    e_a = 1.0 / (1.0 + 10 ** (-(elo_a - elo_b) / 400.0))

    # Draw probability decreases as ELO gap widens
    diff = abs(elo_a - elo_b)
    draw_prob = max(0.10, 0.28 - diff * 0.0003)

    # Decompose expected score into win/draw/loss
    # e_a = p_win_a + 0.5 * draw_prob  →  p_win_a = e_a - 0.5 * draw_prob
    p_win_a = max(0.0, e_a - 0.5 * draw_prob)
    p_win_b = max(0.0, (1.0 - e_a) - 0.5 * draw_prob)

    # Renormalize to sum to 1
    total = p_win_a + draw_prob + p_win_b
    return p_win_a / total, draw_prob / total, p_win_b / total


# --- Market title parsing ---

# Match known team names against market title text
def _all_team_names() -> list[str]:
    elo = load_elo()
    names = list(elo.keys())
    for alias, canonical in TEAM_ALIASES.items():
        names.append(alias)
    return names


def parse_teams_from_title(title: str) -> tuple[str, str] | None:
    """
    Attempt to extract two team names from a market title.
    Example titles:
      "Will Spain beat Croatia?"
      "Spain vs Croatia - match winner"
      "2026 World Cup: Spain/Croatia"
    Returns (team_a, team_b) with canonical names, or None if not found.
    """
    title_lower = title.lower()
    found = []
    for name in _all_team_names():
        if re.search(r"\b" + re.escape(name.lower()) + r"\b", title_lower):
            canonical = normalize(name) if name.lower() in TEAM_ALIASES else name
            if canonical not in found:
                found.append(canonical)
    if len(found) >= 2:
        return found[0], found[1]
    return None
