"""Refresh the prices inside wharton/index.html, the team's copy of the Wharton portfolio model.

The page is a self-contained build of PortfolioModel.html from the (private) WhartonInvestmentChallenge
repository, with the price history embedded as `window.PRT_DATA={...};`. This script swaps in the
latest daily closes without touching anything else on the page, so the team's link stays current
without a token for the private repository. It is run by .github/workflows/wharton-prices.yml.

make_data.py and refresh_prices.py next to this file are copies of portfolio-model/tools/ in that
repository; keep them in step when they change there.

  python3 tools/wharton/update_page.py                 # refresh wharton/index.html in place
  python3 tools/wharton/update_page.py --selftest      # extract and re-insert the data (no network)
  python3 tools/wharton/update_page.py --check-only    # load the page in Chromium and check it renders
"""
import argparse, pathlib, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
PAGE = HERE.parent.parent / "wharton" / "index.html"
MARK = "window.PRT_DATA="


def split(html):
    """(before, data.js text, after): the embedded snapshot exactly as build.py inlined it."""
    i = html.index(MARK)
    if html.count(MARK) != 1:
        raise SystemExit("wharton/index.html holds more than one price snapshot")
    j = html.index(";\n", i) + 2  # the JSON has no raw newline, so its first ";\n" is the end
    return html[:i], html[i:j], html[j:]


def as_of(data_js):
    import json
    return json.loads(data_js[len(MARK):].rstrip().rstrip(";"))["asOf"]


def check_page(path):
    """Load the page in headless Chromium: it must render, decode its data and report no errors."""
    from playwright.sync_api import sync_playwright
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(pathlib.Path(path).resolve().as_uri())
        pg.wait_for_selector(".ph h1", timeout=30000)
        info = pg.evaluate("() => ({ asOf: PRT.D.asOf, n: PRT.D.meta.size, title: document.querySelector('.ph h1').textContent })")
        pg.fill("#cmd", "MSFT")
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(2500)
        sized = pg.evaluate("() => /Position sizer/.test(document.querySelector('#view').innerText) && /Risk score of MSFT/.test(document.querySelector('#view').innerText)")
        b.close()
    if errors or not sized:
        raise SystemExit(f"the page did not work: {'; '.join(errors) or 'the Position sizer did not size MSFT'}")
    print(f"page renders: {info['title']}, prices to {info['asOf']}, {info['n']} securities; the sizer works")
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default=str(PAGE))
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--check-only", action="store_true")
    a = ap.parse_args()
    page = pathlib.Path(a.page)
    html = page.read_text(encoding="utf-8")
    before, data_js, after = split(html)
    if a.check_only:
        check_page(page)
        return
    if a.selftest:
        import make_data as M
        with tempfile.TemporaryDirectory() as tmp:
            src = pathlib.Path(tmp) / "data.js"
            src.write_text(data_js, encoding="utf-8")
            w, meta, long, asof = M.decode_snapshot(str(src))
            js, msg = M.encode_snapshot(w, meta, long, asof)
        same = before + js + after == html
        print(f"{msg}\npage round trip {'identical' if same else 'DIFFERS'}")
        sys.exit(0 if same else 1)

    import refresh_prices as RP
    old = as_of(data_js)
    with tempfile.TemporaryDirectory() as tmp:
        src = pathlib.Path(tmp) / "data.js"
        src.write_text(data_js, encoding="utf-8")
        # Only what the page already holds (plus the model's funds and ADRs): the universe changes with the model.
        RP.build(str(src), str(src), extra_universe=False)
        new_js = src.read_text(encoding="utf-8")
    if as_of(new_js) < old:
        raise SystemExit(f"the new prices end {as_of(new_js)}, before the page's {old}: the page is left as it was")
    out = page.with_name("index.check.html")  # an .html name, so Chromium opens it as a page
    out.write_text(before + new_js + after, encoding="utf-8", newline="\n")
    try:
        check_page(out)
    except SystemExit:
        out.unlink()
        raise
    out.replace(page)
    print(f"wharton/index.html: prices {old} -> {as_of(new_js)}")


if __name__ == "__main__":
    main()
