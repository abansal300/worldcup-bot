from client import KalshiClient
from strategy import Signal


class Executor:
    def __init__(
        self,
        client: KalshiClient,
        dry_run: bool = True,
        max_total_exposure: float = 500.0,
    ):
        self.client = client
        self.dry_run = dry_run
        self.max_total_exposure = max_total_exposure
        self._placed: set[str] = set()  # tickers traded this session

    def current_exposure(self) -> float:
        positions = self.client.get_positions()
        total = 0.0
        for pos in positions:
            # market_exposure = contracts held * current price (approximate cost basis)
            contracts = pos.get("position", 0)
            market_value = pos.get("market_exposure", 0)
            total += abs(market_value) / 100 if market_value > 1 else abs(market_value)
        return total

    def execute(self, signal: Signal) -> None:
        if signal.ticker in self._placed:
            print(f"  [SKIP] Already traded {signal.ticker} this session")
            return

        exposure = self.current_exposure()
        cost = signal.contracts * signal.limit_price
        if exposure + cost > self.max_total_exposure:
            print(
                f"  [SKIP] {signal.ticker}: exposure limit reached "
                f"(${exposure:.2f} + ${cost:.2f} > ${self.max_total_exposure:.2f})"
            )
            return

        print(
            f"  {'[DRY RUN] ' if self.dry_run else ''}ORDER: "
            f"BUY {signal.contracts}x {signal.side.upper()} on {signal.ticker!r} "
            f"@ ${signal.limit_price:.2f} | "
            f"model={signal.model_prob:.1%} market={signal.market_prob:.1%} "
            f"edge={signal.edge:.1%} | "
            f"teams: {signal.team_a} vs {signal.team_b}"
        )

        if not self.dry_run:
            result = self.client.create_order(
                ticker=signal.ticker,
                side=signal.side,
                count=signal.contracts,
                price=signal.limit_price,
            )
            print(f"  Order placed: {result}")
            self._placed.add(signal.ticker)
        else:
            self._placed.add(signal.ticker)
