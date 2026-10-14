import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tbot import capital  # noqa: E402
from tbot.capital import Capital, CapitalError, load_env, position_deal_id, prices_to_frame  # noqa: E402

CREDS = {"CAPITAL_API_KEY": "k-geheim", "CAPITAL_IDENTIFIER": "ich@example.org", "CAPITAL_PASSWORD": "pw-geheim"}


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


class FakeServer:
    """Antwortet je (Methode, Pfad ohne Query) aus einer Tabelle; Login liefert Tokens."""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls = []
        self.logins = 0

    def __call__(self, method, url, headers, body):
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "body": json.loads(body) if body else None})
        path = url.removeprefix(capital.DEMO).split("?")[0]
        if (method, path) == ("POST", "/api/v1/session"):
            self.logins += 1
            return 200, {"CST": f"cst{self.logins}", "X-SECURITY-TOKEN": f"tok{self.logins}"}, b'{"currentAccountId":"x"}'
        resp = self.routes[(method, path)]
        if isinstance(resp, list):
            resp = resp.pop(0)
        status, payload = resp
        return status, {}, json.dumps(payload).encode()


def client(routes=None):
    srv, clk = FakeServer(routes), FakeClock()
    return Capital(CREDS, send=srv, clock=clk, sleep=clk.sleep), srv, clk


class TestCapitalSession(unittest.TestCase):
    def test_only_demo_url(self):
        c, srv, _ = client({("GET", "/api/v1/accounts"): (200, {"accounts": []})})
        c.accounts()
        self.assertTrue(all(x["url"].startswith("https://demo-api-capital.backend-capital.com/") for x in srv.calls))
        self.assertNotIn("://api-capital", Path(capital.__file__).read_text())  # keine Echtgeld-URL

    def test_login_headers_and_tokens(self):
        c, srv, _ = client({("GET", "/api/v1/positions"): (200, {"positions": []})})
        c.positions()
        login, call = srv.calls
        self.assertEqual(login["headers"]["X-CAP-API-KEY"], "k-geheim")
        self.assertEqual(login["body"], {"identifier": "ich@example.org", "password": "pw-geheim",
                                         "encryptedPassword": False})
        self.assertEqual(call["headers"]["CST"], "cst1")
        self.assertEqual(call["headers"]["X-SECURITY-TOKEN"], "tok1")
        self.assertNotIn("X-CAP-API-KEY", call["headers"])

    def test_relogin_after_inactivity(self):
        c, srv, clk = client({("GET", "/api/v1/positions"): (200, {"positions": []})})
        c.positions()
        clk.t += 5 * 60
        c.positions()
        self.assertEqual(srv.logins, 1)
        clk.t += 9 * 60 + 1
        c.positions()
        self.assertEqual(srv.logins, 2)
        self.assertEqual(srv.calls[-1]["headers"]["CST"], "cst2")

    def test_relogin_once_on_401(self):
        c, srv, _ = client({("GET", "/api/v1/positions"): [(401, {"errorCode": "error.invalid.session.token"}),
                                                           (200, {"positions": [{"x": 1}]})]})
        self.assertEqual(c.positions(), [{"x": 1}])
        self.assertEqual(srv.logins, 2)

    def test_persistent_401_raises(self):
        c, _, _ = client({("GET", "/api/v1/positions"): [(401, {"errorCode": "a"}), (401, {"errorCode": "b"})]})
        with self.assertRaises(CapitalError):
            c.positions()

    def test_login_failure_hides_secrets(self):
        def send(method, url, headers, body):
            return 401, {}, b'{"errorCode":"error.invalid.details"}'
        clk = FakeClock()
        c = Capital(CREDS, send=send, clock=clk, sleep=clk.sleep)
        with self.assertRaises(CapitalError) as cm:
            c.accounts()
        msg = str(cm.exception) + repr(c)
        self.assertIn("error.invalid.details", msg)
        for secret in CREDS.values():
            self.assertNotIn(secret, msg)

    def test_rate_limit_spacing(self):
        c, srv, clk = client({("GET", "/api/v1/positions"): (200, {"positions": []})})
        for _ in range(3):
            c.positions()
        # Login + 3 Abrufe ohne Zeitfortschritt → jede Folgeanfrage wartet 0,1 s
        self.assertEqual(len(srv.calls), 4)
        self.assertEqual([round(s, 3) for s in clk.slept], [0.1, 0.1, 0.1])

    def test_http_error_raises_with_code(self):
        c, _, _ = client({("GET", "/api/v1/markets/XX"): (404, {"errorCode": "error.not-found.epic"})})
        with self.assertRaisesRegex(CapitalError, "error.not-found.epic"):
            c.market("XX")


class TestCapitalCalls(unittest.TestCase):
    def test_search_and_prices_query(self):
        c, srv, _ = client({("GET", "/api/v1/markets"): (200, {"markets": [{"epic": "US500"}]}),
                            ("GET", "/api/v1/prices/US500"): (200, {"prices": []})})
        self.assertEqual(c.search_markets("US500")[0]["epic"], "US500")
        c.prices("US500", "HOUR", 10, start="2026-10-01T00:00:00")
        self.assertIn("searchTerm=US500", srv.calls[1]["url"])
        url = srv.calls[2]["url"]
        self.assertIn("resolution=HOUR", url)
        self.assertIn("max=10", url)
        self.assertIn("from=2026-10-01T00%3A00%3A00", url)
        self.assertNotIn("to=", url)

    def test_open_requires_stop(self):
        c, srv, _ = client()
        with self.assertRaises(CapitalError):
            c.open_position("US500", "BUY", 1)
        with self.assertRaises(CapitalError):
            c.open_position("US500", "BUY", 1, stop_level=1, stop_distance=2)
        with self.assertRaises(CapitalError):
            c.open_position("US500", "LONG", 1, stop_level=1)
        self.assertEqual(srv.calls, [])

    def test_open_and_close_position(self):
        c, srv, _ = client({
            ("POST", "/api/v1/positions"): (200, {"dealReference": "o_ref1"}),
            ("DELETE", "/api/v1/positions/pos-1"): (200, {"dealReference": "c_ref2"}),
            ("GET", "/api/v1/confirms/o_ref1"): (200, {"dealStatus": "ACCEPTED", "dealId": "ord-1",
                                                     "affectedDeals": [{"dealId": "pos-1", "status": "OPENED"}]}),
            ("GET", "/api/v1/confirms/c_ref2"): (200, {"dealStatus": "ACCEPTED", "dealId": "pos-1",
                                                     "affectedDeals": [{"dealId": "pos-1", "status": "FULLY_CLOSED"}]}),
        })
        conf = c.open_position("US500", "BUY", 0.1, stop_level=5000.5)
        self.assertEqual(srv.calls[1]["body"], {"epic": "US500", "direction": "BUY", "size": 0.1,
                                                "guaranteedStop": False, "stopLevel": 5000.5})
        self.assertEqual(position_deal_id(conf), "pos-1")
        closed = c.close_position("pos-1")
        self.assertEqual(closed["affectedDeals"][0]["status"], "FULLY_CLOSED")
        self.assertEqual(srv.calls[3]["method"], "DELETE")

    def test_prices_to_frame_mid(self):
        p = [{"snapshotTimeUTC": "2026-10-14T13:30:00", "openPrice": {"bid": 99, "ask": 101},
              "highPrice": {"bid": 104, "ask": 106}, "lowPrice": {"bid": 97, "ask": 99},
              "closePrice": {"bid": 101, "ask": 103}}]
        df = prices_to_frame(p)
        self.assertEqual(list(df.iloc[0]), [100, 105, 98, 102])
        self.assertEqual(str(df.index.tz), "UTC")


class TestLoadEnv(unittest.TestCase):
    def test_reads_env_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("# Kommentar\nCAPITAL_API_KEY=abc\nexport CAPITAL_IDENTIFIER='a@b.c'\nCAPITAL_PASSWORD=\"p=w\"\n")
            with mock.patch.dict("os.environ", {}, clear=True):
                self.assertEqual(load_env(p), {"CAPITAL_API_KEY": "abc", "CAPITAL_IDENTIFIER": "a@b.c",
                                               "CAPITAL_PASSWORD": "p=w"})

    def test_missing_names_keys_not_values(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("CAPITAL_API_KEY=abc\n")
            with mock.patch.dict("os.environ", {}, clear=True):
                with self.assertRaises(CapitalError) as cm:
                    load_env(p)
        self.assertIn("CAPITAL_PASSWORD", str(cm.exception))
        self.assertNotIn("abc", str(cm.exception))

    def test_env_in_gitignore(self):
        lines = (Path(__file__).resolve().parents[1] / ".gitignore").read_text().split()
        self.assertIn(".env", lines)


MARKET = {"instrument": {"epic": "US500", "name": "US 500", "type": "INDICES", "currency": "USD", "lotSize": 1,
                         "marginFactor": 5, "marginFactorUnit": "PERCENTAGE",
                         "overnightFee": {"longRate": -0.02, "shortRate": -0.005},
                         "openingHours": {"mon": ["00:00 - 21:00"], "zone": "UTC"}},
          "dealingRules": {"minDealSize": {"unit": "POINTS", "value": 0.1},
                           "minStopOrProfitDistance": {"unit": "POINTS", "value": 5}},
          "snapshot": {"marketStatus": "TRADEABLE", "bid": 5000.0, "offer": 5000.4}}


class TestMarketsScript(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import capital_markets
        self.mod = capital_markets

    def routes(self):
        return {("GET", "/api/v1/markets"): (200, {"markets": [{"epic": "US500_X", "instrumentType": "SHARES"},
                                                              {"epic": "US500", "instrumentType": "INDICES"}]}),
                ("GET", "/api/v1/markets/US500"): (200, MARKET)}

    def test_describe(self):
        c, _, _ = client(self.routes())
        m = self.mod.describe(c, "US500")
        self.assertEqual(m["epic"], "US500")
        self.assertEqual(m["min_deal_size"]["value"], 0.1)
        self.assertAlmostEqual(m["spread"]["points"], 0.4)
        self.assertEqual(m["margin_factor"], 5)
        self.assertEqual(m["financing"]["longRate"], -0.02)
        self.assertNotIn("account", json.dumps(m).lower())

    def test_test_order_closes_with_stop(self):
        r = self.routes()
        r.update({("POST", "/api/v1/positions"): (200, {"dealReference": "o1"}),
                  ("GET", "/api/v1/confirms/o1"): (200, {"dealStatus": "ACCEPTED", "dealId": "ord",
                                                       "affectedDeals": [{"dealId": "p1", "status": "OPENED"}]}),
                  ("GET", "/api/v1/positions"): [(200, {"positions": [{"position": {"dealId": "p1", "stopLevel": 4950}}]}),
                                                 (200, {"positions": []})],
                  ("DELETE", "/api/v1/positions/p1"): (200, {"dealReference": "c1"}),
                  ("GET", "/api/v1/confirms/c1"): (200, {"dealStatus": "ACCEPTED"})})
        c, srv, _ = client(r)
        m = self.mod.describe(c, "US500")
        with mock.patch.object(self.mod.time, "sleep"):
            log = self.mod.test_order(c, m)
        order = next(x for x in srv.calls if x["method"] == "POST" and x["url"].endswith("/positions"))
        self.assertEqual(order["body"]["size"], 0.1)
        self.assertEqual(order["body"]["stopLevel"], 4950.0)   # 1 % unter Geld (> 2 × Mindestabstand)
        self.assertEqual([s["step"] for s in log["steps"]], ["eröffnet", "offen", "geschlossen", "kontrolle"])
        self.assertFalse(log["steps"][-1]["noch_offen"])

    def test_test_order_skips_closed_market(self):
        c, srv, _ = client(self.routes())
        m = self.mod.describe(c, "US500")
        m["spread"]["market_status"] = "CLOSED"
        log = self.mod.test_order(c, m)
        self.assertEqual(log["steps"][0]["step"], "abbruch")
        self.assertFalse(any(x["method"] == "POST" and "positions" in x["url"] for x in srv.calls))


if __name__ == "__main__":
    unittest.main()
