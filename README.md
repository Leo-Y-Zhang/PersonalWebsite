# PersonalWebsite

### ▶ **[leo-y-zhang.github.io/PersonalWebsite](https://leo-y-zhang.github.io/PersonalWebsite/)**

Personal site. Hand-written HTML and CSS, no build step, no JavaScript,
no tracking. The strip on the front page is the real lower-bound certificate
for OEIS A217058 a(12) = 57 — the cells are the published colouring, not
decoration.

The one page not written by hand is `vdw.html`: `tools/build_vdw_page.py`
generates it from an OEIS snapshot and the b-files in a MathRecords checkout,
and refuses to write it if the two disagree. `tools/verify_certificate.py`
re-derives the front-page certificate from `index.html` itself. CI runs the
verifier and the tests on every push; locally they need Python and nothing
else:

```sh
python tools/verify_certificate.py
python -m unittest discover -s tests -v
```

### Security write-ups

`tools/build_security_page.py` generates `security.html` from Markdown
write-ups in platform subfolders. Like the reference page, its output is
kept in the repository once published. It needs only the standard library:

```sh
python3 tools/build_security_page.py --writeups writeups --out security.html
```

Each file starts with `---` front matter containing `title`, `platform`,
`level` (an integer), `date` (YYYY-MM-DD) and comma-separated `skills`, then
four non-empty sections in order: `## What the level asked`,
`## What I tried`, `## What worked` and `## What it teaches`. `README.md`
and `TEMPLATE.md` are ignored.

The page stays unpublished until there are 10 valid write-ups. Below that,
the tool exits with code 3 and writes nothing; `--min` changes the threshold
for local previews. No passwords: describe how the level was solved without
giving its password. Password assignments, private key headers and runs of
32 or more letters or digits are refused, including inside code blocks
(only a fence's language tag is exempt from the long-token check).

The intro contains an owner comment to replace with one or two sentences
in your own words. When ready to publish, `--link` also adds Security to the
front-page navigation and `security.html` to the sitemap; repeated runs add
no duplicates. Without it, only the output file changes.

Fonts are self-hosted in `fonts/`: IBM Plex Mono, under the SIL Open Font
License 1.1.

Served by GitHub Pages from the repository root, so a push to `main` is a
deploy. The live address is the one at the top; it is also on the repository's
About panel, on the right of this page.
