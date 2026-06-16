import base64
import time
import uuid
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


class KalshiClient:
    BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
    SIGN_PATH_PREFIX = "/trade-api/v2"

    def __init__(self, api_key_id: str, private_key_pem: str):
        self.api_key_id = api_key_id
        self.private_key = serialization.load_pem_private_key(
            private_key_pem.encode(), password=None
        )
        self.session = requests.Session()

    def _sign_path(self, path: str) -> str:
        path = path.split("?")[0]
        if not path.startswith(self.SIGN_PATH_PREFIX):
            path = self.SIGN_PATH_PREFIX + path
        return path

    def _sign(self, timestamp_ms: int, method: str, path: str) -> str:
        sign_path = self._sign_path(path)
        message = f"{timestamp_ms}{method.upper()}{sign_path}".encode()
        sig = self.private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(sig).decode()

    def _request(self, method: str, path: str, **kwargs) -> dict:
        timestamp_ms = int(time.time() * 1000)
        signature = self._sign(timestamp_ms, method, path)
        headers = {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": str(timestamp_ms),
            "Content-Type": "application/json",
        }
        url = self.BASE_URL + path
        resp = self.session.request(method, url, headers=headers, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def get_balance(self) -> float:
        data = self._request("GET", "/portfolio/balance")
        return data["balance"] / 100

    def get_markets(self, **params) -> list[dict]:
        results = []
        cursor = None
        while True:
            if cursor:
                params["cursor"] = cursor
            data = self._request("GET", "/markets", params=params)
            results.extend(data.get("markets", []))
            cursor = data.get("cursor")
            if not cursor or len(data.get("markets", [])) == 0:
                break
        return results

    def get_market(self, ticker: str) -> dict:
        return self._request("GET", f"/markets/{ticker}")["market"]

    def get_orderbook(self, ticker: str) -> dict:
        return self._request("GET", f"/markets/{ticker}/orderbook")["orderbook"]

    def get_positions(self) -> list[dict]:
        data = self._request("GET", "/portfolio/positions")
        return data.get("market_positions", [])

    def create_order(
        self,
        ticker: str,
        side: str,      # "yes" or "no"
        count: int,     # number of contracts
        price: float,   # limit price in dollars (0.01 - 0.99)
    ) -> dict:
        body = {
            "ticker": ticker,
            "action": "buy",
            "side": side,
            "type": "limit",
            "count": count,
            f"{side}_price": round(price, 2),
            "client_order_id": str(uuid.uuid4()),
        }
        return self._request("POST", "/portfolio/orders", json=body)
