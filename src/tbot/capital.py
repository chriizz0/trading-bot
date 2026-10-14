"""Capital.com-REST-Client (ohne Fremdpakete). NUR DEMO – eine Echtgeld-URL gibt es hier nicht.

Zugangsdaten aus .env (CAPITAL_API_KEY, CAPITAL_IDENTIFIER, CAPITAL_PASSWORD), ersatzweise
aus der Umgebung. Sitzung (CST / X-SECURITY-TOKEN) läuft nach 10 Min Inaktivität ab:
Der Client loggt vorher neu ein und versucht es nach HTTP 401 genau einmal erneut.
Rate-Limits: max. 10 Anfragen/s (≥ 0,1 s Abstand, gilt damit auch für Orders), Login ≤ 1/s."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEMO = "https://demo-api-capital.backend-capital.com"
ENV_KEYS = ("CAPITAL_API_KEY", "CAPITAL_IDENTIFIER", "CAPITAL_PASSWORD")
SESSION_TTL = 10 * 60
RELOGIN_AFTER = 9 * 60          # Puffer vor dem Ablauf
MIN_INTERVAL = 0.1              # 10 Req/s; Orders ≥ 0,1 s Abstand
LOGIN_INTERVAL = 1.0            # POST /session: 1 Req/s


class CapitalError(RuntimeError):
    pass


def load_env(path: str | Path = ".env") -> dict[str, str]:
    """Liest CAPITAL_*-Werte aus .env; fehlende Werte aus os.environ. Gibt nie Werte aus."""
    vals: dict[str, str] = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.removeprefix("export ").split("=", 1)
            vals[k.strip()] = v.strip().strip("'\"")
    out = {k: vals.get(k) or os.environ.get(k, "") for k in ENV_KEYS}
    missing = [k for k, v in out.items() if not v]
    if missing:
        raise CapitalError(f"Zugangsdaten fehlen: {', '.join(missing)} (in .env eintragen)")
    return out


def _urllib_send(method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()


class Capital:
    def __init__(self, creds: dict[str, str] | None = None, send=None,
                 clock=time.monotonic, sleep=time.sleep):
        self.base = DEMO
        self._creds = creds or load_env()
        self._send = send or _urllib_send
        self._clock, self._sleep = clock, sleep
        self._cst = self._token = None
        self._last_used = self._last_req = self._last_login = None

    def __repr__(self) -> str:  # nie Zugangsdaten oder Tokens zeigen
        return f"Capital(base={self.base!r}, session={'aktiv' if self._cst else 'keine'})"

    # --- Rate-Limit und Sitzung -------------------------------------------------------------
    def _wait(self, last: float | None, interval: float) -> None:
        if last is not None:
            gap = interval - (self._clock() - last)
            if gap > 0:
                self._sleep(gap)

    def _raw(self, method: str, path: str, headers: dict, body: dict | None):
        self._wait(self._last_req, MIN_INTERVAL)
        data = json.dumps(body).encode() if body is not None else None
        status, rh, raw = self._send(method, self.base + path, headers, data)
        self._last_req = self._clock()
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = {"raw": raw[:300].decode(errors="replace")}
        return status, {k.lower(): v for k, v in rh.items()}, payload

    def login(self) -> None:
        self._wait(self._last_login, LOGIN_INTERVAL)
        self._last_login = self._clock()
        status, rh, payload = self._raw("POST", "/api/v1/session",
                                        {"X-CAP-API-KEY": self._creds["CAPITAL_API_KEY"],
                                         "Content-Type": "application/json"},
                                        {"identifier": self._creds["CAPITAL_IDENTIFIER"],
                                         "password": self._creds["CAPITAL_PASSWORD"],
                                         "encryptedPassword": False})
        if status != 200 or "cst" not in rh or "x-security-token" not in rh:
            self._cst = self._token = None
            raise CapitalError(f"Login fehlgeschlagen: HTTP {status} {_err(payload)}")
        self._cst, self._token = rh["cst"], rh["x-security-token"]
        self._last_used = self._clock()

    def _session_ok(self) -> bool:
        return self._cst is not None and self._clock() - self._last_used < RELOGIN_AFTER

    def _req(self, method: str, path: str, body: dict | None = None, query: dict | None = None):
        if query:
            path += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        for attempt in (0, 1):
            if not self._session_ok():
                self.login()
            status, _, payload = self._raw(method, path, {"CST": self._cst, "X-SECURITY-TOKEN": self._token,
                                                          "Content-Type": "application/json"}, body)
            if status == 401 and attempt == 0:   # Sitzung serverseitig abgelaufen → einmal neu
                self._cst = None
                continue
            self._last_used = self._clock()
            if status >= 400:
                raise CapitalError(f"{method} {path.split('?')[0]}: HTTP {status} {_err(payload)}")
            return payload
        raise CapitalError(f"{method} {path}: Sitzung abgelehnt")

    # --- Lesen --------------------------------------------------------------------------------
    def accounts(self) -> list[dict]:
        return self._req("GET", "/api/v1/accounts")["accounts"]

    def positions(self) -> list[dict]:
        return self._req("GET", "/api/v1/positions")["positions"]

    def search_markets(self, term: str) -> list[dict]:
        return self._req("GET", "/api/v1/markets", query={"searchTerm": term})["markets"]

    def market(self, epic: str) -> dict:
        return self._req("GET", f"/api/v1/markets/{urllib.parse.quote(epic)}")

    def prices(self, epic: str, resolution: str = "MINUTE_30", max_bars: int = 1000,
               start: str | None = None, end: str | None = None) -> list[dict]:
        """resolution: MINUTE, MINUTE_5, MINUTE_15, MINUTE_30, HOUR, HOUR_4, DAY, WEEK.
        start/end: 'YYYY-MM-DDTHH:MM:SS' (UTC)."""
        return self._req("GET", f"/api/v1/prices/{urllib.parse.quote(epic)}",
                         query={"resolution": resolution, "max": max_bars, "from": start, "to": end})["prices"]

    def confirm(self, deal_reference: str) -> dict:
        return self._req("GET", f"/api/v1/confirms/{urllib.parse.quote(deal_reference)}")

    # --- Handeln (nur Demo) -------------------------------------------------------------------
    def open_position(self, epic: str, direction: str, size: float, *, stop_level: float | None = None,
                      stop_distance: float | None = None, profit_level: float | None = None) -> dict:
        """Marktposition MIT Stop eröffnen; liefert die Bestätigung (/confirms)."""
        if direction not in ("BUY", "SELL"):
            raise CapitalError(f"Richtung {direction!r} ungültig")
        if (stop_level is None) == (stop_distance is None):
            raise CapitalError("Genau eines von stop_level / stop_distance angeben – ohne Stop keine Order")
        body = {"epic": epic, "direction": direction, "size": size, "guaranteedStop": False}
        if stop_level is not None:
            body["stopLevel"] = stop_level
        else:
            body["stopDistance"] = stop_distance
        if profit_level is not None:
            body["profitLevel"] = profit_level
        ref = self._req("POST", "/api/v1/positions", body)["dealReference"]
        return self.confirm(ref)

    def close_position(self, deal_id: str) -> dict:
        ref = self._req("DELETE", f"/api/v1/positions/{urllib.parse.quote(deal_id)}")["dealReference"]
        return self.confirm(ref)


def position_deal_id(confirm: dict) -> str:
    """dealId der eröffneten Position aus einer Bestätigung."""
    for d in confirm.get("affectedDeals") or []:
        if d.get("status") == "OPENED":
            return d["dealId"]
    return confirm["dealId"]


def prices_to_frame(prices: list[dict]):
    """Kurshistorie → DataFrame (Mittelkurs, UTC-Index) wie die Backtest-Kerzen."""
    import pandas as pd
    rows = {}
    for p in prices:
        ts = pd.Timestamp(p.get("snapshotTimeUTC") or p["snapshotTime"], tz="UTC")
        rows[ts] = {k: (p[f"{k}Price"]["bid"] + p[f"{k}Price"]["ask"]) / 2 for k in ("open", "high", "low", "close")}
    return pd.DataFrame.from_dict(rows, orient="index").sort_index()


def _err(payload) -> str:
    if isinstance(payload, dict):
        return str(payload.get("errorCode") or payload.get("raw") or "")[:300]
    return ""
