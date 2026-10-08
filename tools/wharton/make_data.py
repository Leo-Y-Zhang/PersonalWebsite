"""Build the embedded market-data snapshot (src/data.js).

Inputs (downloaded separately, not committed):
  --prices       prices.parquet  daily OHLCV + split/dividend-adjusted close
  --gics         constituents.csv  S&P 500 members with GICS sectors
  --listing      all.csv           US listing with market cap and sector
Output:
  src/data.js  (window.PRT_DATA)

Encoding: for every series the natural log of the adjusted close is rounded to
1 basis point on a cumulative basis, and the day-to-day differences are stored
as int16. Rounding the cumulative level (not each return) means the rebuilt
price is never more than 0.5 bp away from the source on any date. The int16
stream is split into low and high byte planes, deflated and base64-encoded.
"""
import argparse, base64, json, zlib
import numpy as np
import pandas as pd

START = "2020-01-01"

# name, class, region, effective duration (bond funds only)
ETF = {
    "SPY": ("SPDR S&P 500 ETF Trust", "ETF-EQ", "US", None),
    "VOO": ("Vanguard S&P 500 ETF", "ETF-EQ", "US", None),
    "IVV": ("iShares Core S&P 500 ETF", "ETF-EQ", "US", None),
    "VTI": ("Vanguard Total Stock Market ETF", "ETF-EQ", "US", None),
    "QQQ": ("Invesco QQQ Trust (Nasdaq-100)", "ETF-EQ", "US", None),
    "DIA": ("SPDR Dow Jones Industrial Average ETF", "ETF-EQ", "US", None),
    "RSP": ("Invesco S&P 500 Equal Weight ETF", "ETF-EQ", "US", None),
    "IWB": ("iShares Russell 1000 ETF", "ETF-EQ", "US", None),
    "IWV": ("iShares Russell 3000 ETF", "ETF-EQ", "US", None),
    "IWD": ("iShares Russell 1000 Value ETF", "ETF-EQ", "US", None),
    "IWF": ("iShares Russell 1000 Growth ETF", "ETF-EQ", "US", None),
    "IVE": ("iShares S&P 500 Value ETF", "ETF-EQ", "US", None),
    "IVW": ("iShares S&P 500 Growth ETF", "ETF-EQ", "US", None),
    "MDY": ("SPDR S&P MidCap 400 ETF", "ETF-EQ", "US", None),
    "IJH": ("iShares Core S&P Mid-Cap ETF", "ETF-EQ", "US", None),
    "IJJ": ("iShares S&P Mid-Cap 400 Value ETF", "ETF-EQ", "US", None),
    "IJK": ("iShares S&P Mid-Cap 400 Growth ETF", "ETF-EQ", "US", None),
    "IJR": ("iShares Core S&P Small-Cap ETF", "ETF-EQ", "US", None),
    "IJS": ("iShares S&P Small-Cap 600 Value ETF", "ETF-EQ", "US", None),
    "IJT": ("iShares S&P Small-Cap 600 Growth ETF", "ETF-EQ", "US", None),
    "IWM": ("iShares Russell 2000 ETF", "ETF-EQ", "US", None),
    "IWN": ("iShares Russell 2000 Value ETF", "ETF-EQ", "US", None),
    "IWO": ("iShares Russell 2000 Growth ETF", "ETF-EQ", "US", None),
    "DVY": ("iShares Select Dividend ETF", "ETF-EQ", "US", None),
    "DSI": ("iShares MSCI KLD 400 Social ETF", "ETF-EQ", "US", None),
    "LCTU": ("BlackRock U.S. Carbon Transition Readiness ETF", "ETF-EQ", "US", None),
    "XLB": ("Materials Select Sector SPDR", "ETF-EQ", "US", None),
    "XLC": ("Communication Services Select Sector SPDR", "ETF-EQ", "US", None),
    "XLE": ("Energy Select Sector SPDR", "ETF-EQ", "US", None),
    "XLF": ("Financial Select Sector SPDR", "ETF-EQ", "US", None),
    "XLI": ("Industrial Select Sector SPDR", "ETF-EQ", "US", None),
    "XLK": ("Technology Select Sector SPDR", "ETF-EQ", "US", None),
    "XLP": ("Consumer Staples Select Sector SPDR", "ETF-EQ", "US", None),
    "XLU": ("Utilities Select Sector SPDR", "ETF-EQ", "US", None),
    "XLV": ("Health Care Select Sector SPDR", "ETF-EQ", "US", None),
    "XLY": ("Consumer Discretionary Select Sector SPDR", "ETF-EQ", "US", None),
    "SOXX": ("iShares Semiconductor ETF", "ETF-EQ", "US", None),
    "IBB": ("iShares Biotechnology ETF", "ETF-EQ", "US", None),
    "ITA": ("iShares U.S. Aerospace & Defense ETF", "ETF-EQ", "US", None),
    "ITB": ("iShares U.S. Home Construction ETF", "ETF-EQ", "US", None),
    "IGV": ("iShares Expanded Tech-Software ETF", "ETF-EQ", "US", None),
    "IHI": ("iShares U.S. Medical Devices ETF", "ETF-EQ", "US", None),
    "IYT": ("iShares U.S. Transportation ETF", "ETF-EQ", "US", None),
    "IAT": ("iShares U.S. Regional Banks ETF", "ETF-EQ", "US", None),
    "ICLN": ("iShares Global Clean Energy ETF", "ETF-EQ", "Global", None),
    "EFA": ("iShares MSCI EAFE ETF", "ETF-EQ", "Intl Developed", None),
    "VEU": ("Vanguard FTSE All-World ex-US ETF", "ETF-EQ", "Intl", None),
    "EEM": ("iShares MSCI Emerging Markets ETF", "ETF-EQ", "Emerging", None),
    "VWO": ("Vanguard FTSE Emerging Markets ETF", "ETF-EQ", "Emerging", None),
    "EWA": ("iShares MSCI Australia ETF", "ETF-EQ", "Intl Developed", None),
    "EWC": ("iShares MSCI Canada ETF", "ETF-EQ", "Intl Developed", None),
    "EWG": ("iShares MSCI Germany ETF", "ETF-EQ", "Intl Developed", None),
    "EWH": ("iShares MSCI Hong Kong ETF", "ETF-EQ", "Intl Developed", None),
    "EWJ": ("iShares MSCI Japan ETF", "ETF-EQ", "Intl Developed", None),
    "EWS": ("iShares MSCI Singapore ETF", "ETF-EQ", "Intl Developed", None),
    "EWT": ("iShares MSCI Taiwan ETF", "ETF-EQ", "Emerging", None),
    "EWU": ("iShares MSCI United Kingdom ETF", "ETF-EQ", "Intl Developed", None),
    "EWY": ("iShares MSCI South Korea ETF", "ETF-EQ", "Emerging", None),
    "EWZ": ("iShares MSCI Brazil ETF", "ETF-EQ", "Emerging", None),
    "VNQ": ("Vanguard Real Estate ETF", "ETF-RE", "US", None),
    "IYR": ("iShares U.S. Real Estate ETF", "ETF-RE", "US", None),
    "XLRE": ("Real Estate Select Sector SPDR", "ETF-RE", "US", None),
    "AGG": ("iShares Core U.S. Aggregate Bond ETF", "ETF-FI", "US", 6.0),
    "SHY": ("iShares 1-3 Year Treasury Bond ETF", "ETF-FI", "US", 1.9),
    "IEF": ("iShares 7-10 Year Treasury Bond ETF", "ETF-FI", "US", 7.1),
    "TLT": ("iShares 20+ Year Treasury Bond ETF", "ETF-FI", "US", 15.9),
    "TIP": ("iShares TIPS Bond ETF", "ETF-FI", "US", 6.6),
    "LQD": ("iShares iBoxx $ Investment Grade Corporate Bond ETF", "ETF-FI", "US", 8.3),
    "HYG": ("iShares iBoxx $ High Yield Corporate Bond ETF", "ETF-FI", "US", 3.1),
    "GLD": ("SPDR Gold Shares", "ETF-CMD", "Global", None),
    "SLV": ("iShares Silver Trust", "ETF-CMD", "Global", None),
}

NASDAQ_TO_GICS = {
    "Technology": "Information Technology", "Finance": "Financials",
    "Health Care": "Health Care", "Consumer Discretionary": "Consumer Discretionary",
    "Industrials": "Industrials", "Real Estate": "Real Estate", "Utilities": "Utilities",
    "Energy": "Energy", "Consumer Staples": "Consumer Staples",
    "Telecommunications": "Communication Services", "Basic Materials": "Materials",
}

LONG = ["SPY", "EFA", "EEM", "AGG", "SHY", "IEF", "TLT", "TIP", "LQD", "GLD", "VNQ"]


def clean_name(n):
    for suf in [" Common Stock", " Class A Common Stock", " Class A", " Ordinary Shares",
                " Common Shares", " Class B Common Stock"]:
        if n.endswith(suf):
            n = n[: -len(suf)]
    return n.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices", required=True)
    ap.add_argument("--gics", required=True)
    ap.add_argument("--listing", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    px = pd.read_parquet(a.prices, columns=["date", "ticker", "adj_close"])
    wide_all = px.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    as_of = wide_all.index.max()
    wide = wide_all.loc[START:]
    wide = wide.loc[:, wide.iloc[-1].notna()]

    gics = pd.read_csv(a.gics)
    gics["Symbol"] = gics["Symbol"].str.replace(".", "-", regex=False)
    gics = gics.set_index("Symbol")
    lst = pd.read_csv(a.listing)
    lst["symbol"] = lst["symbol"].str.replace("/", "-", regex=False).str.replace(".", "-", regex=False)
    lst = lst.drop_duplicates("symbol").set_index("symbol")

    meta = []
    for t in wide.columns:
        last = float(wide[t].iloc[-1])
        if t in ETF:
            n, cls, region, dur = ETF[t]
            meta.append(dict(t=t, n=n, s="ETF", c=cls, r=region, d=dur, mc=None))
            continue
        if t in gics.index:
            sector = gics.loc[t, "GICS Sector"]
            name = gics.loc[t, "Security"]
            mc = float(lst.loc[t, "marketCap"]) if t in lst.index and pd.notna(lst.loc[t, "marketCap"]) else None
        elif t in lst.index:
            row = lst.loc[t]
            if pd.isna(row["marketCap"]) or row["marketCap"] < 1e9:
                continue
            # guard against recycled symbols: the listing price must match the series
            if not (0.97 < float(row["price"]) / last < 1.03):
                continue
            sector = NASDAQ_TO_GICS.get(row["industry"])
            if sector is None:
                continue
            name, mc = clean_name(str(row["name"])), float(row["marketCap"])
        else:
            continue
        meta.append(dict(t=t, n=name, s=sector, c="EQ", r="US", d=None, mc=mc))

    w = wide[[m["t"] for m in meta]].ffill()
    js, msg = encode_snapshot(w, meta, long_history(wide_all, as_of), as_of)
    open(a.out, "w").write(js)
    print(msg)


def long_history(wide_all, as_of):
    """Month-end log returns in basis points for the long-horizon calibration set, to the last full month."""
    long = {}
    for t in LONG:
        s = wide_all[t].dropna()
        me = s.resample("ME").last()
        me = me[me.index < pd.Timestamp(as_of.year, as_of.month, 1)]
        r = np.round(np.diff(np.log(me.values)) * 10000).astype(int)
        long[t] = {"m0": me.index[1].strftime("%Y-%m"), "r": r.tolist()}
    return long


def encode_snapshot(w, meta, long, as_of):
    """Encode prices (dates x tickers in meta order, forward-filled) as window.PRT_DATA. Returns (js, summary)."""
    dates = w.index
    N = len(dates)
    L = np.log(w.values)
    streams, rows = [], []
    for k, m in enumerate(meta):
        col = L[:, k]
        i0 = int(np.argmax(~np.isnan(col)))
        seg = col[i0:]
        q = np.round((seg - seg[-1]) * 10000.0)  # anchored at the last price
        d = np.diff(q).astype(np.int64)
        assert np.abs(d).max(initial=0) < 32767, m["t"]
        streams.append(d.astype(np.int16))
        rows.append([m["t"], m["n"], m["s"], m["c"], m["r"], m["d"],
                     None if m["mc"] is None else round(m["mc"] / 1e6),
                     i0, round(float(w[m["t"]].iloc[-1]), 4)])
    allv = np.concatenate(streams).astype(np.int16)
    u = allv.view(np.uint16)
    planes = np.concatenate([(u & 0xFF).astype(np.uint8), (u >> 8).astype(np.uint8)])
    blob = base64.b64encode(zlib.compress(planes.tobytes(), 9)).decode()

    day0 = dates[0]
    gaps = np.diff(np.concatenate([[0], (dates - day0).days.values]))

    out = {
        "asOf": as_of.strftime("%Y-%m-%d"),
        "d0": day0.strftime("%Y-%m-%d"),
        "gaps": "".join(chr(48 + int(g)) for g in gaps),
        "cols": ["t", "n", "s", "c", "r", "d", "mcap_musd", "i0", "last"],
        "rows": rows,
        "enc": "deflate(int16 lo-plane|hi-plane), cumulative 1bp log-price differences",
        "blob": blob,
        "long": long,
    }
    js = "window.PRT_DATA=" + json.dumps(out, separators=(",", ":")) + ";\n"
    return js, (f"{len(rows)} series, {N} days {dates[0].date()}..{dates[-1].date()}, "
                f"{len(allv)} values, blob {len(blob)/1e6:.2f} MB, file {len(js)/1e6:.2f} MB")


def decode_snapshot(path):
    """Read a data.js written by encode_snapshot back into (prices, meta, long, as_of): the inverse, to 1 bp."""
    txt = open(path, encoding="utf-8").read().strip()
    j = json.loads(txt[txt.index("=") + 1:].rstrip(";"))
    planes = np.frombuffer(zlib.decompress(base64.b64decode(j["blob"])), np.uint8)
    half = len(planes) // 2
    vals = (planes[:half].astype(np.uint16) | (planes[half:].astype(np.uint16) << 8)).view(np.int16).astype(np.int64)
    days = np.cumsum([ord(c) - 48 for c in j["gaps"]])
    dates = pd.DatetimeIndex(pd.Timestamp(j["d0"]) + pd.to_timedelta(days, unit="D"))
    N, off, cols, meta = len(dates), 0, {}, []
    for t, n, s, c, r, d, mc, i0, last in j["rows"]:
        k = N - 1 - i0
        dd = vals[off:off + k]
        off += k
        q = np.concatenate([-np.cumsum(dd[::-1])[::-1], [0]])  # q[-1] = 0, q[i] = q[i+1] - d[i]
        col = np.full(N, np.nan)
        col[i0:] = last * np.exp(q / 10000.0)
        cols[t] = col
        meta.append(dict(t=t, n=n, s=s, c=c, r=r, d=d, mc=None if mc is None else mc * 1e6))
    return pd.DataFrame(cols, index=dates), meta, j["long"], pd.Timestamp(j["asOf"])

if __name__ == "__main__":
    main()
