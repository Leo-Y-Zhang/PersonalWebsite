"""Refresh the embedded price snapshot (src/data.js) with the latest daily closes.

Run by .github/workflows/prices.yml every weekday evening, where the network is open; the
container sessions cannot reach price sites. It keeps every security already in the data, adds
the IPS funds and the stocks the team is likely to research, and downloads the whole history
again so the split and dividend adjustments stay consistent:

  - every security already in src/data.js (names, sectors and market caps are kept);
  - the S&P 500, MidCap 400 and SmallCap 600 (GICS sectors from their Wikipedia lists);
  - the funds the model uses (VEA, VGSH, VCSH and the other IPS-bucket and stand-in funds);
  - large U.S.-listed foreign companies (ADRs such as TSM, ASML, NVO), by region.

Prices are Yahoo Finance daily closes adjusted for splits and dividends (yfinance). A security
whose download fails keeps its previous history; the run lists them and fails if the core funds
or the market index are missing. WInS fills market orders at the live price, so the share counts
use the price the team types on the day; these closes drive the risk and return figures.

  python3 tools/refresh_prices.py                 # refresh src/data.js in place
  python3 tools/refresh_prices.py --selftest      # decode and re-encode src/data.js (no network)
"""
import argparse, datetime as dt, io, pathlib, sys, time

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from make_data import ETF, LONG, START, decode_snapshot, encode_snapshot, long_history  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Funds beyond make_data.ETF: name, class, region, effective duration (bond funds).
FUNDS = {
    # IPS buckets (IPS §8.3) and the order ticket
    "VEA": ("Vanguard FTSE Developed Markets ETF", "ETF-EQ", "Intl Developed", None),
    "VGSH": ("Vanguard Short-Term Treasury ETF", "ETF-FI", "US", 1.9),
    "VCSH": ("Vanguard Short-Term Corporate Bond ETF", "ETF-FI", "US", 2.6),
    "VTIP": ("Vanguard Short-Term Inflation-Protected Securities ETF", "ETF-FI", "US", 2.5),
    "STIP": ("iShares 0-5 Year TIPS Bond ETF", "ETF-FI", "US", 2.5),
    "SCHP": ("Schwab U.S. TIPS ETF", "ETF-FI", "US", 6.6),
    "SCHO": ("Schwab Short-Term U.S. Treasury ETF", "ETF-FI", "US", 1.9),
    "SPTS": ("SPDR Portfolio Short Term Treasury ETF", "ETF-FI", "US", 1.9),
    "IGSB": ("iShares 1-5 Year Investment Grade Corporate Bond ETF", "ETF-FI", "US", 2.6),
    "BSV": ("Vanguard Short-Term Bond ETF", "ETF-FI", "US", 2.6),
    "SPSB": ("SPDR Portfolio Short Term Corporate Bond ETF", "ETF-FI", "US", 1.9),
    "JPST": ("JPMorgan Ultra-Short Income ETF", "ETF-FI", "US", 0.4),
    "BIL": ("SPDR Bloomberg 1-3 Month T-Bill ETF", "ETF-FI", "US", 0.1),
    "SHV": ("iShares 0-1 Year Treasury Bond ETF", "ETF-FI", "US", 0.3),
    "SGOV": ("iShares 0-3 Month Treasury Bond ETF", "ETF-FI", "US", 0.1),
    "USFR": ("WisdomTree Floating Rate Treasury Fund", "ETF-FI", "US", 0.0),
    # other bond funds
    "BND": ("Vanguard Total Bond Market ETF", "ETF-FI", "US", 5.8),
    "MBB": ("iShares MBS ETF", "ETF-FI", "US", 5.9),
    "VGIT": ("Vanguard Intermediate-Term Treasury ETF", "ETF-FI", "US", 5.1),
    "SCHR": ("Schwab Intermediate-Term U.S. Treasury ETF", "ETF-FI", "US", 5.1),
    "IEI": ("iShares 3-7 Year Treasury Bond ETF", "ETF-FI", "US", 4.8),
    "GOVT": ("iShares U.S. Treasury Bond ETF", "ETF-FI", "US", 5.8),
    "TLH": ("iShares 10-20 Year Treasury Bond ETF", "ETF-FI", "US", 11.8),
    "VGLT": ("Vanguard Long-Term Treasury ETF", "ETF-FI", "US", 15.2),
    "SPTL": ("SPDR Portfolio Long Term Treasury ETF", "ETF-FI", "US", 15.2),
    "VCIT": ("Vanguard Intermediate-Term Corporate Bond ETF", "ETF-FI", "US", 6.0),
    "JNK": ("SPDR Bloomberg High Yield Bond ETF", "ETF-FI", "US", 3.2),
    "BNDX": ("Vanguard Total International Bond ETF", "ETF-FI", "Intl Developed", 7.0),
    "EMB": ("iShares J.P. Morgan USD Emerging Markets Bond ETF", "ETF-FI", "Emerging", 7.0),
    "MUB": ("iShares National Muni Bond ETF", "ETF-FI", "US", 6.0),
    # equity funds
    "IEFA": ("iShares Core MSCI EAFE ETF", "ETF-EQ", "Intl Developed", None),
    "ESGD": ("iShares ESG Aware MSCI EAFE ETF", "ETF-EQ", "Intl Developed", None),
    "VGK": ("Vanguard FTSE Europe ETF", "ETF-EQ", "Intl Developed", None),
    "SCHF": ("Schwab International Equity ETF", "ETF-EQ", "Intl Developed", None),
    "BBCA": ("JPMorgan BetaBuilders Canada ETF", "ETF-EQ", "Intl Developed", None),
    "EWL": ("iShares MSCI Switzerland ETF", "ETF-EQ", "Intl Developed", None),
    "EWQ": ("iShares MSCI France ETF", "ETF-EQ", "Intl Developed", None),
    "EWP": ("iShares MSCI Spain ETF", "ETF-EQ", "Intl Developed", None),
    "EWI": ("iShares MSCI Italy ETF", "ETF-EQ", "Intl Developed", None),
    "EWN": ("iShares MSCI Netherlands ETF", "ETF-EQ", "Intl Developed", None),
    "EWD": ("iShares MSCI Sweden ETF", "ETF-EQ", "Intl Developed", None),
    "VXUS": ("Vanguard Total International Stock ETF", "ETF-EQ", "Intl", None),
    "IXUS": ("iShares Core MSCI Total International Stock ETF", "ETF-EQ", "Intl", None),
    "IEMG": ("iShares Core MSCI Emerging Markets ETF", "ETF-EQ", "Emerging", None),
    "ESGE": ("iShares ESG Aware MSCI EM ETF", "ETF-EQ", "Emerging", None),
    "SCHE": ("Schwab Emerging Markets Equity ETF", "ETF-EQ", "Emerging", None),
    "INDA": ("iShares MSCI India ETF", "ETF-EQ", "Emerging", None),
    "MCHI": ("iShares MSCI China ETF", "ETF-EQ", "Emerging", None),
    "FXI": ("iShares China Large-Cap ETF", "ETF-EQ", "Emerging", None),
    "EWW": ("iShares MSCI Mexico ETF", "ETF-EQ", "Emerging", None),
    "ECH": ("iShares MSCI Chile ETF", "ETF-EQ", "Emerging", None),
    "EIDO": ("iShares MSCI Indonesia ETF", "ETF-EQ", "Emerging", None),
    "THD": ("iShares MSCI Thailand ETF", "ETF-EQ", "Emerging", None),
    "EWM": ("iShares MSCI Malaysia ETF", "ETF-EQ", "Emerging", None),
    "EZA": ("iShares MSCI South Africa ETF", "ETF-EQ", "Emerging", None),
    "VNM": ("VanEck Vietnam ETF", "ETF-EQ", "Emerging", None),
    "VT": ("Vanguard Total World Stock ETF", "ETF-EQ", "Global", None),
    "ACWI": ("iShares MSCI ACWI ETF", "ETF-EQ", "Global", None),
    "SPYM": ("SPDR Portfolio S&P 500 ETF (formerly SPLG)", "ETF-EQ", "US", None),
    "ESGU": ("iShares ESG Aware MSCI USA ETF", "ETF-EQ", "US", None),
    "ESGV": ("Vanguard ESG U.S. Stock ETF", "ETF-EQ", "US", None),
    "SCHB": ("Schwab U.S. Broad Market ETF", "ETF-EQ", "US", None),
    "SCHX": ("Schwab U.S. Large-Cap ETF", "ETF-EQ", "US", None),
    "SCHG": ("Schwab U.S. Large-Cap Growth ETF", "ETF-EQ", "US", None),
    "SCHA": ("Schwab U.S. Small-Cap ETF", "ETF-EQ", "US", None),
    "ITOT": ("iShares Core S&P Total U.S. Stock Market ETF", "ETF-EQ", "US", None),
    "VV": ("Vanguard Large-Cap ETF", "ETF-EQ", "US", None),
    "VTV": ("Vanguard Value ETF", "ETF-EQ", "US", None),
    "VUG": ("Vanguard Growth ETF", "ETF-EQ", "US", None),
    "VO": ("Vanguard Mid-Cap ETF", "ETF-EQ", "US", None),
    "VB": ("Vanguard Small-Cap ETF", "ETF-EQ", "US", None),
    "AVUV": ("Avantis U.S. Small Cap Value ETF", "ETF-EQ", "US", None),
    "VYM": ("Vanguard High Dividend Yield ETF", "ETF-EQ", "US", None),
    "SCHD": ("Schwab U.S. Dividend Equity ETF", "ETF-EQ", "US", None),
    "VIG": ("Vanguard Dividend Appreciation ETF", "ETF-EQ", "US", None),
    "NOBL": ("ProShares S&P 500 Dividend Aristocrats ETF", "ETF-EQ", "US", None),
    "USMV": ("iShares MSCI USA Min Vol Factor ETF", "ETF-EQ", "US", None),
    "QUAL": ("iShares MSCI USA Quality Factor ETF", "ETF-EQ", "US", None),
    "MTUM": ("iShares MSCI USA Momentum Factor ETF", "ETF-EQ", "US", None),
    "VGT": ("Vanguard Information Technology ETF", "ETF-EQ", "US", None),
    "VHT": ("Vanguard Health Care ETF", "ETF-EQ", "US", None),
    "VFH": ("Vanguard Financials ETF", "ETF-EQ", "US", None),
    "VDE": ("Vanguard Energy ETF", "ETF-EQ", "US", None),
    "VIS": ("Vanguard Industrials ETF", "ETF-EQ", "US", None),
    "VDC": ("Vanguard Consumer Staples ETF", "ETF-EQ", "US", None),
    "VCR": ("Vanguard Consumer Discretionary ETF", "ETF-EQ", "US", None),
    "VPU": ("Vanguard Utilities ETF", "ETF-EQ", "US", None),
    "SMH": ("VanEck Semiconductor ETF", "ETF-EQ", "US", None),
    "XBI": ("SPDR S&P Biotech ETF", "ETF-EQ", "US", None),
    "KRE": ("SPDR S&P Regional Banking ETF", "ETF-EQ", "US", None),
    "XHB": ("SPDR S&P Homebuilders ETF", "ETF-EQ", "US", None),
    "XRT": ("SPDR S&P Retail ETF", "ETF-EQ", "US", None),
    "XOP": ("SPDR S&P Oil & Gas Exploration & Production ETF", "ETF-EQ", "US", None),
    "TAN": ("Invesco Solar ETF", "ETF-EQ", "Global", None),
    "SCHH": ("Schwab U.S. REIT ETF", "ETF-RE", "US", None),
    "VNQI": ("Vanguard Global ex-U.S. Real Estate ETF", "ETF-RE", "Intl", None),
    "IAU": ("iShares Gold Trust", "ETF-CMD", "Global", None),
    "GDX": ("VanEck Gold Miners ETF", "ETF-EQ", "Global", None),
    "DBC": ("Invesco DB Commodity Index Tracking Fund", "ETF-CMD", "Global", None),
}

# Large U.S.-listed foreign companies (ADRs and foreign ordinary shares): GICS sector and region.
# Their bucket follows the region: Intl Developed counts in the international share, Emerging in the EM share.
FOREIGN = {
    "TSM": ("Taiwan Semiconductor Manufacturing", "Information Technology", "Emerging"),
    "ASML": ("ASML Holding", "Information Technology", "Intl Developed"),
    "SAP": ("SAP", "Information Technology", "Intl Developed"),
    "SONY": ("Sony Group", "Consumer Discretionary", "Intl Developed"),
    "TM": ("Toyota Motor", "Consumer Discretionary", "Intl Developed"),
    "NVO": ("Novo Nordisk", "Health Care", "Intl Developed"),
    "NVS": ("Novartis", "Health Care", "Intl Developed"),
    "AZN": ("AstraZeneca", "Health Care", "Intl Developed"),
    "GSK": ("GSK", "Health Care", "Intl Developed"),
    "SNY": ("Sanofi", "Health Care", "Intl Developed"),
    "SHEL": ("Shell", "Energy", "Intl Developed"),
    "BP": ("BP", "Energy", "Intl Developed"),
    "TTE": ("TotalEnergies", "Energy", "Intl Developed"),
    "HSBC": ("HSBC Holdings", "Financials", "Intl Developed"),
    "UBS": ("UBS Group", "Financials", "Intl Developed"),
    "MUFG": ("Mitsubishi UFJ Financial Group", "Financials", "Intl Developed"),
    "RY": ("Royal Bank of Canada", "Financials", "Intl Developed"),
    "TD": ("Toronto-Dominion Bank", "Financials", "Intl Developed"),
    "BN": ("Brookfield Corporation", "Financials", "Intl Developed"),
    "UL": ("Unilever", "Consumer Staples", "Intl Developed"),
    "DEO": ("Diageo", "Consumer Staples", "Intl Developed"),
    "BTI": ("British American Tobacco", "Consumer Staples", "Intl Developed"),
    "BUD": ("Anheuser-Busch InBev", "Consumer Staples", "Intl Developed"),
    "RIO": ("Rio Tinto", "Materials", "Intl Developed"),
    "BHP": ("BHP Group", "Materials", "Intl Developed"),
    "ENB": ("Enbridge", "Energy", "Intl Developed"),
    "CNQ": ("Canadian Natural Resources", "Energy", "Intl Developed"),
    "CNI": ("Canadian National Railway", "Industrials", "Intl Developed"),
    "CP": ("Canadian Pacific Kansas City", "Industrials", "Intl Developed"),
    "SHOP": ("Shopify", "Information Technology", "Intl Developed"),
    "SPOT": ("Spotify Technology", "Communication Services", "Intl Developed"),
    "ARM": ("Arm Holdings", "Information Technology", "Intl Developed"),
    "SE": ("Sea Limited", "Consumer Discretionary", "Intl Developed"),
    "BABA": ("Alibaba Group", "Consumer Discretionary", "Emerging"),
    "PDD": ("PDD Holdings", "Consumer Discretionary", "Emerging"),
    "JD": ("JD.com", "Consumer Discretionary", "Emerging"),
    "BIDU": ("Baidu", "Communication Services", "Emerging"),
    "NTES": ("NetEase", "Communication Services", "Emerging"),
    "TCOM": ("Trip.com Group", "Consumer Discretionary", "Emerging"),
    "HDB": ("HDFC Bank", "Financials", "Emerging"),
    "IBN": ("ICICI Bank", "Financials", "Emerging"),
    "INFY": ("Infosys", "Information Technology", "Emerging"),
    "VALE": ("Vale", "Materials", "Emerging"),
    "PBR": ("Petrobras", "Energy", "Emerging"),
    "ITUB": ("Itaú Unibanco", "Financials", "Emerging"),
    "NU": ("Nu Holdings", "Financials", "Emerging"),
    "MELI": ("MercadoLibre", "Consumer Discretionary", "Emerging"),
    "KB": ("KB Financial Group", "Financials", "Emerging"),
    "UMC": ("United Microelectronics", "Information Technology", "Emerging"),
    "ASX": ("ASE Technology Holding", "Information Technology", "Emerging"),
}

# Without these the model cannot run its default target: fail the run rather than publish without them.
CORE = ["SPY", "VEA", "VWO", "VGSH", "TIP", "VCSH", "TSM", "SHY", "IEF", "TLT", "MSFT", "GOOGL", "JNJ", "JPM", "PG", "WM", "XOM", "NEE", "MCD", "LIN"]

WIKI = {
    "S&P 500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "S&P MidCap 400": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
    "S&P SmallCap 600": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
}
NASDAQ_SCREENER = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=25000&download=true"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36", "Accept": "application/json, text/html"}
SECTORS = {"Information Technology", "Health Care", "Financials", "Consumer Discretionary", "Consumer Staples", "Industrials",
           "Energy", "Utilities", "Materials", "Real Estate", "Communication Services"}


def index_members():
    """{ticker: (name, GICS sector)} for the S&P 1500 from Wikipedia; whatever lists can be read."""
    import requests
    out = {}
    for label, url in WIKI.items():
        try:
            html = requests.get(url, headers=UA, timeout=30).text
            for tb in pd.read_html(io.StringIO(html)):
                cols = {str(c).lower(): c for c in tb.columns}
                sym = next((cols[c] for c in cols if c in ("symbol", "ticker symbol", "ticker")), None)
                sec = next((cols[c] for c in cols if "sector" in c), None)
                nm = next((cols[c] for c in cols if c in ("security", "company")), None)
                if sym is None or sec is None or nm is None:
                    continue
                n0 = len(out)
                for _, r in tb.iterrows():
                    t = str(r[sym]).strip().replace(".", "-")
                    if t and t != "nan" and str(r[sec]) in SECTORS:
                        out.setdefault(t, (str(r[nm]).strip(), str(r[sec])))
                print(f"{label}: {len(out) - n0} new tickers")
                break
            else:
                print(f"{label}: no constituents table found")
        except Exception as e:  # a list that cannot be read only narrows the universe
            print(f"{label}: not read ({e})")
    return out


def market_caps():
    """{ticker: market cap in USD} from Nasdaq's stock screener; empty if it cannot be read."""
    import requests
    try:
        j = requests.get(NASDAQ_SCREENER, headers=UA, timeout=60).json()
        rows = (j.get("data") or {}).get("rows") or (j.get("data") or {}).get("table", {}).get("rows") or []
        out = {}
        for r in rows:
            try:
                out[r["symbol"].strip().replace("/", "-").replace(".", "-")] = float(str(r["marketCap"]).replace(",", ""))
            except (KeyError, ValueError, TypeError, AttributeError):
                pass
        print(f"market caps: {len(out)} listings")
        return out
    except Exception as e:
        print(f"market caps: not read ({e})")
        return {}


def download(tickers, start, chunk=80, tries=3):
    """Adjusted daily closes (dates x tickers) from Yahoo Finance, in chunks, retrying what fails."""
    import yfinance as yf
    frames, todo = [], list(dict.fromkeys(tickers))
    for attempt in range(tries):
        missing = []
        for i in range(0, len(todo), chunk):
            part = todo[i:i + chunk]
            try:
                df = yf.download(part, start=start, auto_adjust=True, progress=False, threads=True, group_by="column")
                close = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]].rename(columns={"Close": part[0]})
                close = close.dropna(axis=1, how="all")
            except Exception as e:
                print(f"  chunk {i // chunk + 1} failed: {e}")
                close = pd.DataFrame()
            frames.append(close)
            missing += [t for t in part if t not in close.columns]
            time.sleep(1.0)
        print(f"download pass {attempt + 1}: {len(todo) - len(missing)} of {len(todo)} series")
        if not missing:
            break
        todo = missing
        time.sleep(10 * (attempt + 1))
    px = pd.concat([f for f in frames if not f.empty], axis=1) if any(not f.empty for f in frames) else pd.DataFrame()
    px = px.loc[:, ~px.columns.duplicated()]
    px.index = pd.DatetimeIndex(px.index).tz_localize(None).normalize()
    return px.sort_index()


def settled(px, now=None):
    """Drop today's row before the U.S. close has settled (16:30 New York time): it is an intraday price."""
    now = now or pd.Timestamp.now(tz="America/New_York")
    if len(px) and px.index[-1].date() == now.date() and (now.hour, now.minute) < (16, 30):
        px = px.iloc[:-1]
    return px


def build(old_path, out_path, extra_universe=True):
    old_px, old_meta, old_long, old_asof = decode_snapshot(old_path)
    meta = {m["t"]: dict(m) for m in old_meta}
    for t, (n, c, r, d) in {**ETF, **FUNDS}.items():
        meta.setdefault(t, dict(t=t, n=n, s="ETF", c=c, r=r, d=d, mc=None))
    for t, (n, s, r) in FOREIGN.items():
        meta.setdefault(t, dict(t=t, n=n, s=s, c="EQ", r=r, d=None, mc=None))
        if meta[t]["c"] == "EQ":
            meta[t].update(s=s, r=r)
    if extra_universe:
        caps = market_caps()
        for t, (n, s) in index_members().items():
            if t in meta:
                if meta[t]["c"] == "EQ":
                    meta[t]["s"] = s  # GICS sector, kept current
            else:
                meta[t] = dict(t=t, n=n, s=s, c="EQ", r="US", d=None, mc=None)
        for t, m in meta.items():
            if m["c"] == "EQ" and t in caps and caps[t] > 0:
                m["mc"] = caps[t]

    tickers = list(meta)
    px = settled(download(tickers, start=START))
    if px.empty or "SPY" not in px:
        sys.exit("No prices downloaded (or none for SPY): the snapshot is left as it was.")
    as_of = px["SPY"].dropna().index[-1]
    px = px.loc[START:as_of]
    if as_of < old_asof:
        sys.exit(f"Downloaded prices end {as_of.date()}, before the snapshot's {old_asof.date()}: left as it was.")

    # A security not downloaded, or not traded in the last week, keeps its previous history if it has one.
    fresh = [t for t in tickers if t in px and px[t].loc[as_of - pd.Timedelta(days=7):].notna().any()]
    stale = [t for t in tickers if t not in fresh]
    kept = [t for t in stale if t in old_px]
    dropped = [t for t in stale if t not in old_px]
    missing_core = [t for t in CORE if t not in fresh]
    if missing_core:
        sys.exit(f"Core securities not downloaded: {', '.join(missing_core)}. The snapshot is left as it was.")
    dates = px.index
    cols = {t: px[t] for t in fresh}
    for t in kept:  # previous history to its last date; carried flat after it (listed below)
        cols[t] = old_px[t].reindex(dates.union(old_px.index)).loc[dates]
    w = pd.DataFrame(cols, index=dates)[[t for t in tickers if t in cols]]
    short = [t for t in w.columns if w[t].notna().sum() < 60]
    w = w.loc[:, w.notna().sum() >= 60].ffill()  # at least about three months of history
    order = [t for t in tickers if t in w.columns]
    # Guard against a bad print: a daily move beyond the encoding's range (about ±27x) is not a price.
    ok = [t for t in order if np.nanmax(np.abs(np.diff(np.log(w[t].dropna().values)))) < 3.2]
    bad = [t for t in order if t not in ok]
    w = w[ok]

    try:
        long_px = download(LONG, start="1993-01-01")
        long = long_history(settled(long_px), as_of) if all(t in long_px for t in LONG) else old_long
    except Exception as e:
        print(f"long history: kept the previous one ({e})")
        long = old_long

    js, msg = encode_snapshot(w, [meta[t] for t in ok], long, as_of)
    pathlib.Path(out_path).write_text(js, encoding="utf-8", newline="\n")
    print(msg)
    added = [t for t in ok if t not in old_px]
    print(f"as of {as_of.date()} (was {old_asof.date()}): {len(ok)} series, {len(added)} added, "
          f"{len([t for t in old_px if t not in ok])} removed")
    if added:
        print("added:", " ".join(added))
    if kept:
        print(f"not refreshed, previous history kept ({len(kept)}):", " ".join(kept))
    if dropped:
        print(f"not downloaded, not added ({len(dropped)}):", " ".join(dropped))
    if short:
        print(f"under 60 days of history, left out ({len(short)}):", " ".join(short))
    if bad:
        print(f"a daily move beyond ±27x (a bad print or a symbol change), left out ({len(bad)}):", " ".join(bad))
    return as_of


def selftest(path):
    w, meta, long, as_of = decode_snapshot(path)
    js, msg = encode_snapshot(w, meta, long, as_of)
    same = js == pathlib.Path(path).read_text(encoding="utf-8")
    print(f"{msg}\nround trip {'identical' if same else 'DIFFERS'}")
    now = pd.Timestamp("2026-10-07 15:00", tz="America/New_York")
    px = pd.DataFrame({"X": [1.0, 2.0]}, index=pd.DatetimeIndex(["2026-10-06", "2026-10-07"]))
    assert len(settled(px, now)) == 1 and len(settled(px, now + pd.Timedelta(hours=2))) == 2, "settled()"
    return same


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "src/data.js"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-index-lists", action="store_true", help="only refresh what is in the data plus the listed funds and ADRs")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(0 if selftest(a.data) else 1)
    build(a.data, a.out or a.data, extra_universe=not a.no_index_lists)
    print(f"finished {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC")
