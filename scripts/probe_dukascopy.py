"""Misst Antwortzeiten/Statuscodes des Dukascopy-bi5-Feeds (Diagnose)."""
import sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
sys.path.insert(0, "scripts")
from fetch_dukascopy import UA, url

def one(d):
    req = urllib.request.Request(url("USA500IDXUSD", d, "bid"), headers={"User-Agent": UA, "Referer": "https://www.dukascopy.com/"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            n = len(r.read()); code = r.status
    except urllib.error.HTTPError as e:
        n, code = 0, e.code
    except Exception as e:
        n, code = 0, type(e).__name__
    return f"{d} {code} {n}B {time.time()-t:.1f}s"

days = [date(2019, 3, 4) + timedelta(n) for n in range(40) if (date(2019, 3, 4) + timedelta(n)).weekday() < 5]
print("sequenziell:"); t = time.time()
for d in days[:10]: print(" ", one(d), flush=True)
print(f"  gesamt {time.time()-t:.1f}s")
for w in (4, 16):
    t = time.time()
    with ThreadPoolExecutor(w) as ex: res = list(ex.map(one, days[10:26]))
    print(f"parallel {w}: {time.time()-t:.1f}s"); [print(" ", r) for r in res]
