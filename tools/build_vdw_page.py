"""Generate vdw.html - the mixed van der Waerden reference page.

Generated, never typed: every value in the page's tables comes from an OEIS
snapshot (the entry's JSON as the OEIS serves it, saved as oeis_<A-number>.json
in the --snapshots directory) cross-checked against the b-files in a
MathRecords checkout. Any disagreement kills the build - a reference page whose
two sources differ must not exist.

Each term is credited as its OEIS entry credits it: the entry's author for its
original terms, and an EXTENSIONS line for each term added later. The tables
are dated by the day the page is built, so build it from snapshots fetched
that day.

Usage:
    python tools/build_vdw_page.py --mathrecords <MathRecords checkout> \
        --snapshots <dir with oeis_A2170xx.json> --out vdw.html
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import re
import sys
from pathlib import Path

#: The name the OEIS credits for the terms this page holds evidence for.
OWNER = "Leo Y. Zhang"

FAMILIES = [
    # (sequence, index of the term the OEIS credits to OWNER, witness
    #  certificate path in MathRecords)
    ("A217058", 12, "vdw/cert_n56.txt"),
    ("A217005", 19, "vdw/cert_A217005_n51_witness.txt"),
    ("A217007", 7, "vdw/cert_A217007_a7_n67_witness.txt"),
    ("A217236", 4, "vdw/cert_A217236_a4_n83.txt"),
    ("A217059", 9, "vdw/cert_A217059_a9_n73.txt"),
]

# An OEIS credit, "_Name_, Mon DD YYYY", and an EXTENSIONS line that names the
# terms it adds, such as "a(20)-a(33) from _Name_, Oct 16 2026".
_CREDIT = r"_([^_]+)_, ([A-Z][a-z]{2}) \d{1,2} (\d{4})"
_EXTENSION = re.compile(r"a\((\d+)\)(?:-a\((\d+)\))? (?:from|added by) " + _CREDIT)

#: Families whose headline refutation is reduced to checked proof objects
#: (paper, sec. DRAT): per-cube DRAT proofs each replayed to "s VERIFIED" + a
#: checked cube-exhaustiveness proof. All five since MathRecords 3e6ff70, 23,851
#: per-cube proofs in total; a family missing here is labelled a solver verdict.
DRAT_CHECKED = {"A217058", "A217005", "A217007", "A217236", "A217059"}

GH = "https://github.com/Leo-Y-Zhang/MathRecords/blob/main/"


def term_credits(seq: str, rec: dict, offset: int, count: int) -> list[tuple[str, str]]:
    """(name, "Mon YYYY") for each term, as the OEIS entry credits it.

    The entry's author is credited with every term no EXTENSIONS line names.
    EXTENSIONS lines that name no terms (edits, corrections) change no credit.
    A line that adds terms without saying which, a term credited twice, or a
    credit for a term the data lacks kills the build: the page could then not
    say who added what.
    """
    author = re.fullmatch(_CREDIT, rec.get("author", ""))
    if not author:
        sys.exit(f"REFUSING: {seq} author line {rec.get('author')!r} is not a "
                 f"dated OEIS credit")
    credits = [(author.group(1), f"{author.group(2)} {author.group(3)}")] * count
    last = offset + count - 1
    credited = set()
    for line in rec.get("ext", []):
        m = _EXTENSION.fullmatch(line)
        if not m:
            if re.search(r"\bterms?\b", line, re.IGNORECASE):
                sys.exit(f"REFUSING: {seq} EXTENSIONS line {line!r} does not say "
                         f"which terms it adds")
            continue
        lo = int(m.group(1))
        for j in range(lo, int(m.group(2) or lo) + 1):
            if not offset <= j <= last:
                sys.exit(f"REFUSING: {seq} EXTENSIONS line {line!r} credits a({j}), "
                         f"but the OEIS data is a({offset})..a({last})")
            if j in credited:
                sys.exit(f"REFUSING: {seq} a({j}) is credited twice in its "
                         f"EXTENSIONS lines")
            credited.add(j)
            credits[j - offset] = (m.group(3), f"{m.group(4)} {m.group(5)}")
    return credits


def load_family(seq: str, snapshots: Path, mathrecords: Path) -> dict:
    raw = json.loads((snapshots / f"oeis_{seq}.json").read_text(encoding="utf-8"))
    rec = raw["results"][0] if isinstance(raw, dict) else raw[0]
    oeis_values = [int(x) for x in rec["data"].split(",")]
    offset = int(str(rec["offset"]).split(",")[0])

    bfile = mathrecords / f"b{seq[1:]}.txt"
    b_values = []
    for line in bfile.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        idx, val = line.split()
        b_values.append((int(idx), int(val)))

    for i, (idx, val) in enumerate(b_values):
        want = oeis_values[i] if i < len(oeis_values) else None
        if idx != offset + i or val != want:
            sys.exit(f"REFUSING: {seq} b-file row {idx}={val} disagrees with the "
                     f"OEIS snapshot ({want}) - resolve before publishing")
    if len(b_values) != len(oeis_values):
        sys.exit(f"REFUSING: {seq} term-count mismatch (b-file {len(b_values)}, "
                 f"OEIS {len(oeis_values)})")
    credits = term_credits(seq, rec, offset, len(oeis_values))
    return {"seq": seq, "name": rec["name"], "offset": offset, "values": oeis_values,
            "credits": credits}


def family_html(fam: dict, owner_idx: int, cert: str, mathrecords: Path,
                as_of: str) -> str:
    seq, offset = fam["seq"], fam["offset"]
    cert_file = mathrecords / cert
    if not cert_file.is_file():
        sys.exit(f"REFUSING: witness certificate {cert} not found in MathRecords")
    last = offset + len(fam["values"]) - 1
    if not offset <= owner_idx <= last:
        sys.exit(f"REFUSING: {seq} a({owner_idx}) is the term with evidence here, "
                 f"but the OEIS snapshot only has a({offset})..a({last}) - the page "
                 f"would show no certified term and no certificate")
    credited_to = fam["credits"][owner_idx - offset][0]
    if credited_to != OWNER:
        sys.exit(f"REFUSING: {seq} a({owner_idx}) is credited to {credited_to} by "
                 f"the OEIS, not {OWNER} - the page would attach {OWNER}'s "
                 f"evidence to someone else's term")
    drat = seq in DRAT_CHECKED

    rows = []
    for i, val in enumerate(fam["values"]):
        j = offset + i
        who, when = fam["credits"][i]
        credit = f"{html.escape(who, quote=False)}, {when}"
        if j == owner_idx:
            upper = ("upper bound reduced to checked DRAT proof objects"
                     if drat else
                     "upper bound: cross-checked solver verdict, stated as such")
            rows.append(
                f'      <tr>\n'
                f'        <th scope="row" class="m">a({j})</th>\n'
                f'        <td class="m"><strong>{val}</strong></td>\n'
                f'        <td>{credit}; <a href="{GH}{cert}">witness colouring</a>'
                f' for the lower bound; {upper}</td>\n'
                f'      </tr>')
        else:
            rows.append(
                f'      <tr>\n'
                f'        <th scope="row" class="m">a({j})</th>\n'
                f'        <td class="m">{val}</td>\n'
                f'        <td>{credit}</td>\n'
                f'      </tr>')
    name = html.escape(fam["name"], quote=False).replace("...", "&hellip;")
    # The OEIS name arrives in ASCII maths; render the subscripts properly.
    name = re.sub(r"t_\{([^}]+)\}", lambda m: "t<sub>" + m.group(1) + "</sub>", name)
    name = re.sub(r"t_([0-9]+)", lambda m: "t<sub>" + m.group(1) + "</sub>", name)
    name = name.replace("w(", '<span class="m">w(</span>').replace(') with', '<span class="m">)</span> with')
    return f'''
  <h3><a href="https://oeis.org/{seq}">{seq}</a></h3>
  <p class="seqdef">{name}</p>
  <div class="table-scroll" role="region" aria-label="{seq} values" tabindex="0">
  <table class="seqs">
    <caption>Terms and credits as recorded by the OEIS on {as_of}.</caption>
    <thead>
      <tr><th scope="col">Term</th><th scope="col">Value</th><th scope="col">Provenance</th></tr>
    </thead>
    <tbody>
{chr(10).join(rows)}
    </tbody>
  </table>
  </div>'''


def build(mathrecords: Path, snapshots: Path, out: Path) -> None:
    today = _dt.date.today().strftime("%-d %B %Y") if sys.platform != "win32" \
        else _dt.date.today().strftime("%#d %B %Y")
    sections = []
    for seq, owner_idx, cert in FAMILIES:
        fam = load_family(seq, snapshots, mathrecords)
        sections.append(family_html(fam, owner_idx, cert, mathrecords, today))

    page = f'''<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Van der Waerden numbers · Leo Y. Zhang</title>
<meta name="description" content="Known terms, colourings and checked upper bounds for five mixed van der Waerden families.">
<link rel="canonical" href="https://leo-y-zhang.github.io/PersonalWebsite/vdw.html">
<meta name="theme-color" content="#F4F6F8" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0E1420" media="(prefers-color-scheme: dark)">
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="avatar.png">
<link rel="stylesheet" href="style.css">
<meta property="og:title" content="Van der Waerden numbers · Leo Y. Zhang">
<meta property="og:description" content="Known terms, colourings and checked upper bounds for five mixed van der Waerden families.">
<meta property="og:type" content="website">
<meta property="og:url" content="https://leo-y-zhang.github.io/PersonalWebsite/vdw.html">
<meta property="og:image" content="https://leo-y-zhang.github.io/PersonalWebsite/assets/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Leo Y. Zhang: combinatorics, game engines and software">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Van der Waerden numbers · Leo Y. Zhang">
<meta name="twitter:description" content="Known terms, colourings and checked upper bounds for five mixed van der Waerden families.">
<meta name="twitter:image" content="https://leo-y-zhang.github.io/PersonalWebsite/assets/og.png">
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <a class="identity" href="./"><img class="mark" src="favicon.svg" width="40" height="40" alt=""><span>Leo Y. Zhang</span></a>
  <nav aria-label="Main navigation">
    <a href="index.html#work">Work</a> <a href="index.html#mathematics">Mathematics</a> <a href="index.html#try-it">Try it</a> <a href="index.html#index">Index</a> <a href="security.html">Security</a> <a href="index.html#about">About</a> <a href="index.html#contact">Contact</a> <a href="vdw.html">vdW numbers</a>
  </nav>
</header>
<main id="main">
<div class="page-intro"><h1>Van der Waerden numbers</h1><p class="deck">A reference for five mixed families, with certificates and proof provenance.</p></div>


<section class="catalogue-section" id="about-page" aria-labelledby="aboutp-h"><h2 id="aboutp-h">What this page is</h2><div class="section-content">
  <p>For years the community’s reference tables for van der Waerden data were
  maintained by Tanbir Ahmed, whose computations produced many of the values
  below; his pages have since gone offline. This page is a verifiable
  successor for the five mixed families I work on: <strong>every term</strong>
  the OEIS records, credited as the OEIS credits it; <strong>every term I
  added</strong> with a certificate you can check yourself; and <strong>every
  claim labelled by the kind of evidence behind it</strong>.</p>
  <ul class="halves">
    <li><strong>Lower bounds are certificates.</strong> Each term I added links a
    witness colouring; checking it needs the definition and nothing else.</li>
    <li><strong>Upper bounds are labelled by their evidence.</strong> The
    refutations behind those five terms have been reduced to formally checked
    proof objects: 23,851 per-cube DRAT proofs across the five families, each
    replayed to <samp>s&nbsp;VERIFIED</samp> by drat-trim, plus a checked proof
    for each family that its cube set is exhaustive.</li>
  </ul>
  <p>Each term is credited as its OEIS entry credits it: the entry’s author
  for its original terms, and the EXTENSIONS line for each term added later.
  None of the five terms I added was a first determination. Marek Ochocki’s
  preprint of June 2026 has four of them, and S. Karki published A217005
  a(19) = 52 in 2024. What MathRecords adds for those five is a second
  derivation by a different method, with each upper bound reduced to checked
  DRAT proofs.</p>
  <p>The tables are generated from the OEIS and cross-checked against the
  b-files in <a href="https://github.com/Leo-Y-Zhang/MathRecords">MathRecords</a>
  by <a href="{GH.replace('MathRecords/blob/main/', 'PersonalWebsite/blob/main/')}tools/build_vdw_page.py">a script that refuses to build the page
  if the two sources disagree</a>. It was last regenerated {today}.</p>
</div></section>

<section class="catalogue-section" id="tables" aria-labelledby="tables-h"><h2 id="tables-h">The five families</h2><div class="section-content">
{chr(10).join(sections)}
</div></section>

<section class="catalogue-section" id="verify" aria-labelledby="verify-h"><h2 id="verify-h">Verify it yourself</h2><div class="section-content">
  <p>The witness colourings check in milliseconds with
  <a href="{GH}vdw/verify_certificate.py">verify_certificate.py</a>. In CI,
  <code>verify_all.py</code> re-checks every claim in the repository against
  the evidence committed beside it. <a href="{GH}vdw/DRAT.md">DRAT.md</a>
  documents the DRAT machinery, including the measured cost of each proof
  and why colour symmetry had to come out of the cube set before the
  equal-target families could be certified. Terms credited to other people
  are shown as the OEIS records them; MathRecords does not re-derive them.</p>
</div></section>

<section class="catalogue-section" id="references" aria-labelledby="refs-h"><h2 id="refs-h">References</h2><div class="section-content">
  <ul class="halves">
    <li>T. Ahmed, <em>Some new van der Waerden numbers and some van der
    Waerden-type numbers</em>, Integers 9 (2009); and
    <a href="https://cs.uwaterloo.ca/journals/JIS/VOL16/Ahmed/ahmed2.html"><em>Some
    More Van der Waerden Numbers</em></a>, J. Integer Seq. 16 (2013), the
    prior work these families stood on for over a decade.</li>
    <li>T. Ahmed, <a href="https://arxiv.org/abs/1102.5433"><em>On the van der
    Waerden numbers w(2;3,t)</em></a>, arXiv:1102.5433.</li>
    <li>S. Karki, <em>A New van der Waerden Number</em>, U(t)-Mathazine 9
    (2024), 34–39.</li>
    <li>M. Ochocki, <a href="https://doi.org/10.5281/zenodo.20572598"><em>Computing
    Off-Diagonal Van der Waerden Numbers: Improved Algorithm and New Exact
    Values</em></a>, Zenodo preprint (2026).</li>
    <li>The OEIS entries linked in each table, which carry the full submission
    history of every term.</li>
    <li><em>Five mixed van der Waerden numbers, with machine-checked upper
    bounds</em>, the write-up of the five terms I added, with the encoding, the
    certificates and an explicit account of which claims rest on which kind of
    evidence:
    <a href="https://github.com/Leo-Y-Zhang/MathRecords/tree/main/paper">Write-up</a>.</li>
  </ul>
</div></section>


</main>
<footer class="site-footer">
  <p>Set in Newsreader by Production Type, with Noto Serif for Greek and IBM Plex Mono for code, all under the SIL Open Font License. No trackers, no cookies, no JavaScript. Updated {today}.</p>
  <p><a href="projects.html">Project notes</a> <a href="vdw.html">vdW numbers</a></p>
</footer>
</body>
</html>
'''
    out.write_text(page, encoding="utf-8", newline="\n")
    print(f"wrote {out} ({len(page)} bytes)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mathrecords", required=True, type=Path)
    ap.add_argument("--snapshots", required=True, type=Path)
    ap.add_argument("--out", default=Path("vdw.html"), type=Path)
    a = ap.parse_args()
    build(a.mathrecords, a.snapshots, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
