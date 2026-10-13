"""Minimaler Alpaca-REST-Adapter (ohne Fremdpakete). Standard ist PAPER.
Live nur mit TBOT_MODE=live UND exakter Bestätigung in TBOT_LIVE_CONFIRM."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

PAPER = "https://paper-api.alpaca.markets"
LIVE = "https://api.alpaca.markets"
LIVE_CONFIRM = "ich-akzeptiere-echtgeld"


class BrokerError(RuntimeError):
    pass


def mode_from_env() -> str:
    mode = os.environ.get("TBOT_MODE", "paper")
    if mode == "live" and os.environ.get("TBOT_LIVE_CONFIRM") != LIVE_CONFIRM:
        raise BrokerError("Live-Modus verlangt TBOT_LIVE_CONFIRM – abgebrochen.")
    if mode not in ("paper", "live"):
        raise BrokerError(f"Unbekannter Modus {mode!r}")
    return mode


class Alpaca:
    def __init__(self, mode: str | None = None):
        self.mode = mode or mode_from_env()
        self.base = LIVE if self.mode == "live" else PAPER
        self.key = os.environ.get("ALPACA_KEY_ID", "")
        self.secret = os.environ.get("ALPACA_SECRET_KEY", "")
        if not self.key or not self.secret:
            raise BrokerError("ALPACA_KEY_ID / ALPACA_SECRET_KEY fehlen")

    def _req(self, method: str, path: str, body: dict | None = None, query: dict | None = None):
        url = self.base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raise BrokerError(f"{method} {path}: HTTP {e.code} {e.read()[:300]!r}") from None

    def account(self) -> dict:
        return self._req("GET", "/v2/account")

    def positions(self) -> dict[str, dict]:
        return {p["symbol"]: p for p in self._req("GET", "/v2/positions")}

    def clock(self) -> dict:
        return self._req("GET", "/v2/clock")

    def calendar(self, start: str, end: str) -> list[dict]:
        return self._req("GET", "/v2/calendar", query={"start": start, "end": end})

    def market_order(self, symbol: str, side: str, notional: float, client_id: str) -> dict:
        return self._req("POST", "/v2/orders", {"symbol": symbol, "side": side, "type": "market",
                                                "time_in_force": "day", "notional": f"{notional:.2f}",
                                                "client_order_id": client_id})

    def close_position(self, symbol: str) -> dict:
        return self._req("DELETE", f"/v2/positions/{urllib.parse.quote(symbol)}")

    def order(self, order_id: str) -> dict:
        return self._req("GET", f"/v2/orders/{order_id}")

    def wait_filled(self, order_ids: list[str], timeout: float = 90) -> dict[str, dict]:
        end, out = time.time() + timeout, {}
        while time.time() < end:
            out = {i: self.order(i) for i in order_ids}
            if all(o["status"] in ("filled", "canceled", "rejected", "expired") for o in out.values()):
                break
            time.sleep(3)
        return out
