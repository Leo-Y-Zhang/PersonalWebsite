"""Generate vdw.html - the mixed van der Waerden reference page.

Generated, never typed: every value in the page's tables comes from an OEIS
snapshot (the entry's JSON as the OEIS serves it, saved as oeis_<A-number>.json
in the --snapshots directory) cross-checked against the b-files in a
MathRecords checkout. Any disagreement kills the build - a reference page whose
two sources differ must not exist.

Usage:
    python tools/build_vdw_page.py --mathrecords <MathRecords checkout> \
        --snapshots <dir with oeis_A2170xx.json> --out vdw.html
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import sys
from pathlib import Path

FAMILIES = [
    # (sequence, new-term index, credited date, witness certificate path in MathRecords)
    ("A217058", 12, "30 July 2026", "vdw/cert_n56.txt"),
    ("A217005", 19, "7 August 2026", "vdw/cert_A217005_n51_witness.txt"),
    ("A217007", 7, "7 August 2026", "vdw/cert_A217007_a7_n67_witness.txt"),
    ("A217236", 4, "7 August 2026", "vdw/cert_A217236_a4_n83.txt"),
    ("A217059", 9, "13 August 2026", "vdw/cert_A217059_a9_n73.txt"),
]

#: Families whose headline refutation is reduced to checked proof objects
#: (paper, sec. DRAT): per-cube DRAT proofs each replayed to "s VERIFIED" + a
#: checked cube-exhaustiveness proof. All five since MathRecords 3e6ff70, 23,851
#: per-cube proofs in total; a family missing here is labelled a solver verdict.
DRAT_CHECKED = {"A217058", "A217005", "A217007", "A217236", "A217059"}

GH = "https://github.com/Leo-Y-Zhang/MathRecords/blob/main/"


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
    return {"seq": seq, "name": rec["name"], "offset": offset, "values": oeis_values}


def family_html(fam: dict, new_idx: int, credited: str, cert: str,
                mathrecords: Path) -> str:
    seq, offset = fam["seq"], fam["offset"]
    cert_file = mathrecords / cert
    if not cert_file.is_file():
        sys.exit(f"REFUSING: witness certificate {cert} not found in MathRecords")
    last = offset + len(fam["values"]) - 1
    if not offset <= new_idx <= last:
        sys.exit(f"REFUSING: {seq} a({new_idx}) is the new term, but the OEIS "
                 f"snapshot only has a({offset})..a({last}) - the page would show "
                 f"no new term and no certificate")
    drat = seq in DRAT_CHECKED

    rows = []
    for i, val in enumerate(fam["values"]):
        j = offset + i
        if j == new_idx:
            upper = ("upper bound reduced to checked DRAT proof objects"
                     if drat else
                     "upper bound: cross-checked solver verdict, stated as such")
            rows.append(
                f'      <tr>\n'
                f'        <th scope="row" class="m">a({j})</th>\n'
                f'        <td class="m"><strong>{val}</strong></td>\n'
                f'        <td><span class="ok">new</span> &mdash; published by the OEIS,'
                f' credited {credited}; <a href="{GH}{cert}">witness colouring</a>'
                f' for the lower bound; {upper}</td>\n'
                f'      </tr>')
        else:
            rows.append(
                f'      <tr>\n'
                f'        <th scope="row" class="m">a({j})</th>\n'
                f'        <td class="m">{val}</td>\n'
                f'        <td>previously known &mdash; as recorded by the OEIS</td>\n'
                f'      </tr>')
    import re as _re
    name = html.escape(fam["name"], quote=False).replace("...", "&hellip;")
    # The OEIS name arrives in ASCII maths; render the subscripts properly.
    name = _re.sub(r"t_\{([^}]+)\}", lambda m: "t<sub>" + m.group(1) + "</sub>", name)
    name = _re.sub(r"t_([0-9]+)", lambda m: "t<sub>" + m.group(1) + "</sub>", name)
    name = name.replace("w(", '<span class="m">w(</span>').replace(') with', '<span class="m">)</span> with')
    return f'''
  <h3><a href="https://oeis.org/{seq}">{seq}</a></h3>
  <p class="seqdef">{name}</p>
  <table class="seqs">
    <caption>All known terms, as recorded by the OEIS.</caption>
    <thead>
      <tr><th scope="col">Term</th><th scope="col">Value</th><th scope="col">Provenance</th></tr>
    </thead>
    <tbody>
{chr(10).join(rows)}
    </tbody>
  </table>'''


def build(mathrecords: Path, snapshots: Path, out: Path) -> None:
    today = _dt.date.today().strftime("%-d %B %Y") if sys.platform != "win32" \
        else _dt.date.today().strftime("%#d %B %Y")
    sections = []
    for seq, new_idx, credited, cert in FAMILIES:
        fam = load_family(seq, snapshots, mathrecords)
        sections.append(family_html(fam, new_idx, credited, cert, mathrecords))

    page = f'''<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Leo Y. Zhang &mdash; Van der Waerden numbers</title>
<meta name="description" content="A maintained, verifiable reference for five mixed van der Waerden families: every known term, every new term with its certificate, every claim labelled by its kind of evidence.">
<meta property="og:title" content="Leo Y. Zhang &mdash; Van der Waerden numbers">
<meta property="og:description" content="A maintained, verifiable reference for five mixed van der Waerden families.">
<meta property="og:type" content="website">
<meta property="og:url" content="https://leo-y-zhang.github.io/PersonalWebsite/vdw.html">
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="style.css">
<style>
  .seqdef {{ font-style: italic; margin: 0.2em 0 0.6em; }}
</style>
</head>
<body>

<header class="mast">
  <svg class="portrait" viewBox="0 0 64 64" role="img" aria-label="Monogram: L dot Z">
    <rect width="64" height="64" rx="8" fill="#0b57a4"/>
    <text x="32" y="42" font-family="Georgia, serif" font-size="26" font-weight="bold" fill="#fdfdfb" text-anchor="middle">L&#183;Z</text>
  </svg>
  <div class="ident">
    <h1>Leo Y. Zhang</h1>
    <p class="role">Mixed van der Waerden numbers &mdash; a maintained reference</p>
    <p class="affil">Sixth-form student, United Kingdom</p>
  </div>
</header>

<nav aria-label="Sections">
  <a href="index.html">Home</a>
  <a href="projects.html">Projects</a>
  <a href="#tables">Tables</a>
  <a href="#verify">Verify it</a>
  <a href="#references">References</a>
</nav>

<main>

<section id="about-page" aria-labelledby="aboutp-h">
  <h2 id="aboutp-h">What this page is</h2>
  <p>For years the community's reference tables for van der Waerden data were
  maintained by Tanbir Ahmed, whose computations produced many of the values
  below; his pages have since gone offline. This page keeps a maintained,
  verifiable successor for the five mixed families I work on: <strong>every
  known term</strong> as the OEIS records it, <strong>every new term</strong>
  with a certificate you can check yourself, and <strong>every claim labelled
  by the kind of evidence behind it</strong>.</p>
  <ul class="halves">
    <li><strong>Lower bounds are certificates.</strong> Each new term links a
    witness colouring; checking it needs the definition and nothing else.</li>
    <li><strong>Upper bounds are labelled honestly.</strong> All five new
    refutations have been reduced to formally checked proof objects:
    23,851 per-cube DRAT proofs across the five families, each replayed to
    <span class="m">s&nbsp;VERIFIED</span> by drat-trim, plus a checked proof
    for each family that its cube set is exhaustive. The tables label every
    upper bound by the evidence behind it rather than dressing a verdict as a
    proof.</li>
  </ul>
  <p>The tables are generated from the OEIS and cross-checked against the
  b-files in <a href="https://github.com/Leo-Y-Zhang/MathRecords">MathRecords</a>
  by <a href="{GH.replace('MathRecords/blob/main/', 'PersonalWebsite/blob/main/')}tools/build_vdw_page.py">a script that refuses to build the page
  if the two sources disagree</a> &mdash; last regenerated {today}.</p>
</section>

<section id="tables" aria-labelledby="tables-h">
  <h2 id="tables-h">The five families</h2>
{chr(10).join(sections)}
</section>

<section id="verify" aria-labelledby="verify-h">
  <h2 id="verify-h">Verify it yourself</h2>
  <p>No claim on this page asks for trust. The witness colourings check in
  milliseconds with
  <a href="{GH}vdw/verify_certificate.py">verify_certificate.py</a>; the whole
  repository re-derives every published value from scratch under
  <span class="m">verify_all.py</span>, in CI; and the DRAT machinery &mdash;
  including the measured cost of each proof and why colour symmetry had to
  come out of the cube set before the equal-target families could be
  certified &mdash; is documented in <a href="{GH}vdw/DRAT.md">DRAT.md</a>.</p>
</section>

<section id="references" aria-labelledby="refs-h">
  <h2 id="refs-h">References</h2>
  <ul class="halves">
    <li>T. Ahmed, <em>Some new van der Waerden numbers and some van der
    Waerden-type numbers</em>, Integers 9 (2009); and
    <a href="https://cs.uwaterloo.ca/journals/JIS/VOL16/Ahmed/ahmed2.html"><em>Some
    More Van der Waerden Numbers</em></a>, J. Integer Seq. 16 (2013) &mdash; the
    prior work these families stood on for over a decade.</li>
    <li>T. Ahmed, <a href="https://arxiv.org/abs/1102.5433"><em>On the van der
    Waerden numbers w(2;3,t)</em></a>, arXiv:1102.5433.</li>
    <li>The OEIS entries linked in each table, which carry the full submission
    history of every term.</li>
    <li><em>Five new mixed van der Waerden numbers</em> &mdash; the write-up of
    the 2026 terms, with the encoding, the certificates and an explicit account
    of which claims rest on which kind of evidence:
    <a href="https://github.com/Leo-Y-Zhang/MathRecords/tree/main/paper">MathRecords/paper</a>.</li>
  </ul>
</section>

</main>

<footer>
  <p>Leo Y. Zhang &middot; generated {today} from the OEIS and the MathRecords
  b-files by a build that fails if its sources disagree.</p>
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
