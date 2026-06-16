import requests

ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"


def get_live_wc_matches() -> list[dict]:
    """
    Fetches live World Cup matches from ESPN's public scoreboard API.
    Returns a list of match dicts with keys:
      match_id, home_team, away_team, home_score, away_score,
      minute, status, total_goals
    """
    resp = requests.get(ESPN_URL, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    matches = []
    for event in data.get("events", []):
        comp = event.get("competitions", [{}])[0]
        status = comp.get("status", {})
        state = status.get("type", {}).get("name", "")

        if state not in ("STATUS_IN_PROGRESS",):
            continue

        clock = status.get("clock", 0)         # seconds elapsed (ESPN)
        display_clock = status.get("displayClock", "0:00")
        minute = _parse_minute(display_clock, clock)

        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue

        # ESPN lists home team first (homeAway == "home")
        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

        home_score = int(home.get("score", 0))
        away_score = int(away.get("score", 0))

        matches.append({
            "match_id": event.get("id"),
            "home_team": home["team"]["displayName"],
            "away_team": away["team"]["displayName"],
            "home_score": home_score,
            "away_score": away_score,
            "total_goals": home_score + away_score,
            "minute": minute,
            "status": state,
        })

    return matches


def _parse_minute(display_clock: str, clock_seconds: float) -> int:
    """Convert ESPN clock to match minute."""
    # display_clock is often "75:00" or "90:00+5"
    try:
        base = display_clock.split("+")[0].split(":")[0]
        return int(base)
    except (ValueError, IndexError):
        return int(clock_seconds // 60)
