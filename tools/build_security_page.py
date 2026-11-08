"""Build a gated security write-ups page using only the Python standard library.

Usage:
    python tools/build_security_page.py --writeups <folder> --out security.html

Nothing is written until every write-up passes validation and the minimum is
met. --link also updates the site's index navigation and sitemap.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
HEADINGS = ("What the level asked", "What I tried", "What worked", "What it teaches")
KEYS = ("title", "platform", "level", "date", "skills")
MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
TOKEN = re.compile(r"[A-Za-z0-9]{32,}")
PASSWORD = re.compile(r"password\s*[:=]\s*\S{8,}", re.I)
PRIVATE_KEY = re.compile(r"-{2,}\s*BEGIN\b[^\r\n]*\bPRIVATE\s+KEY\b", re.I)


def refuse(path: Path, line: int, message: str) -> None:
    raise ValueError(f"{path}:{line}: {message}")


def fence_end(line: str, fence: str) -> bool:
    return bool(re.fullmatch(r" {0,3}" + re.escape(fence[0]) +
                             "{" + str(len(fence)) + r",}\s*", line))


def scan_lines(path: Path, lines: list[str]) -> set[int]:
    """Check secrets everywhere and return the lines inside/on code fences."""
    fenced = set()
    fence = None
    start = 0
    for number, line in enumerate(lines, 1):
        check = line
        opening = FENCE.match(line) if fence is None else None
        if opening:
            fence, info = opening.groups()
            start = number
            # Only the first word (the language tag) is exempt, not code or
            # any additional info on the opening line.
            check = re.sub(r"^\s*\S+", "", info, count=1)
        if PASSWORD.search(line):
            refuse(path, number, "password assignment; describe the solution without passwords")
        if PRIVATE_KEY.search(line):
            refuse(path, number, "private key header is forbidden")
        if TOKEN.search(check):
            refuse(path, number, "possible secret: 32 or more consecutive alphanumeric characters")
        if fence is not None:
            fenced.add(number)
            if not opening and fence_end(line, fence):
                fence = None
    if fence is not None:
        refuse(path, start, "unclosed fenced code block")
    return fenced


def load_writeup(path: Path) -> dict:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        refuse(path, 1, f"cannot read UTF-8 write-up: {exc}")
    fenced = scan_lines(path, lines)
    if not lines or lines[0] != "---":
        refuse(path, 1, "expected opening front-matter ---")
    try:
        end = lines.index("---", 1)
    except ValueError:
        refuse(path, 1, "missing closing front-matter ---")
    meta, locations = {}, {}
    for i in range(1, end):
        key, separator, value = lines[i].partition(":")
        if not separator or key not in KEYS:
            refuse(path, i + 1, "expected a front-matter key: " + ", ".join(KEYS))
        if key in meta:
            refuse(path, i + 1, f"duplicate front-matter key {key}")
        if not value.strip():
            refuse(path, i + 1, f"empty front-matter key {key}")
        meta[key], locations[key] = value.strip(), i + 1
    for key in KEYS:
        if key not in meta:
            refuse(path, end + 1, f"missing front-matter key {key}")
    if not re.fullmatch(r"[+-]?[0-9]+", meta["level"]):
        refuse(path, locations["level"], "level must be an integer")
    try:
        meta["level"] = int(meta["level"])
    except ValueError:
        refuse(path, locations["level"], "level must be an integer")
    try:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", meta["date"]):
            raise ValueError
        meta["date"] = dt.date.fromisoformat(meta["date"])
    except ValueError:
        refuse(path, locations["date"], "date must be a valid ISO date (YYYY-MM-DD)")

    sections, current, heading_line = [], [], None

    def finish_section():
        if not any(line.strip() and number not in fenced and
                   not line.startswith("### ") for number, line in current) and not any(
                       line.strip() and not FENCE.match(line)
                       for number, line in current if number in fenced):
            refuse(path, heading_line, "section must be non-empty")
        sections.append("\n".join(line for _, line in current))

    for i in range(end + 1, len(lines)):
        number, line = i + 1, lines[i]
        if number not in fenced and line.startswith("## "):
            if heading_line is not None:
                finish_section()
            expected = HEADINGS[len(sections)] if len(sections) < len(HEADINGS) else None
            if line != f"## {expected}" or expected is None:
                refuse(path, number, f"expected heading ## {expected}" if expected else
                       "only the four required level headings are allowed")
            heading_line, current = number, []
        elif heading_line is None:
            # Before the first required heading, only blank lines are allowed.
            if line.strip():
                refuse(path, number, f"expected heading ## {HEADINGS[0]}")
        else:
            current.append((number, line))
    if heading_line is not None:
        finish_section()
    if len(sections) != len(HEADINGS):
        refuse(path, len(lines) + 1, f"missing heading ## {HEADINGS[len(sections)]}")
    meta["sections"], meta["path"] = sections, path
    return meta


def inline(text: str, links: bool = True) -> str:
    """Render a small inline grammar; all unmatched input is escaped."""
    pattern = (r"(?P<ticks>`+)(?P<code>.+?)(?P=ticks)|"
               r"(?P<strong>\*\*|__)(?P<bold>.+?)(?P=strong)|"
               r"(?P<em>\*(?!\*)|_(?!_))(?P<italic>.+?)(?P=em)")
    if links:
        pattern += r"|\[(?P<label>[^\]\n]+)\]\((?P<url>[^\s)]*)\)"
    result, start = [], 0
    for match in re.finditer(pattern, text):
        result.append(html.escape(text[start:match.start()]))
        code, bold, italic = match.group("code", "bold", "italic")
        if code is not None:
            result.append("<code>" + html.escape(code) + "</code>")
        elif bold is not None:
            result.append("<strong>" + inline(bold, links=False) + "</strong>")
        elif italic is not None:
            result.append("<em>" + inline(italic, links=False) + "</em>")
        else:
            label, url = match.group("label", "url")
            try:
                parts = urlsplit(url)
                safe = parts.scheme.lower() in ("http", "https") and bool(parts.netloc)
                safe = safe and not any(ord(c) < 32 or ord(c) == 127 for c in url)
            except ValueError:
                safe = False
            result.append('<a href="' + html.escape(url, quote=True) + '">' +
                          inline(label, links=False) + "</a>" if safe else
                          html.escape(match.group()))
        start = match.end()
    result.append(html.escape(text[start:]))
    return "".join(result)


def markdown(text: str) -> str:
    lines, result, i = text.splitlines(), [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        opening = FENCE.match(line)
        if opening:
            code, fence = [], opening.group(1)
            i += 1
            while i < len(lines) and not fence_end(lines[i], fence):
                code.append(lines[i])
                i += 1
            result.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
            i += 1
        elif line.startswith("### "):
            result.append("<h5>" + inline(line[4:]) + "</h5>")
            i += 1
        elif re.match(r"^\s*(?:[-+*]|[0-9]+[.)])\s+", line):
            ordered = bool(re.match(r"^\s*[0-9]+[.)]\s+", line))
            tag = "ol" if ordered else "ul"
            pattern = r"^\s*[0-9]+[.)]\s+(.+)" if ordered else r"^\s*[-+*]\s+(.+)"
            items = []
            while i < len(lines):
                item = re.match(pattern, lines[i])
                if not item:
                    break
                items.append("<li>" + inline(item.group(1)) + "</li>")
                i += 1
            result.append(f"<{tag}>" + "".join(items) + f"</{tag}>")
        else:
            paragraph = [line]
            i += 1
            while i < len(lines) and lines[i].strip() and not (
                    FENCE.match(lines[i]) or lines[i].startswith("### ") or
                    re.match(r"^\s*(?:[-+*]|[0-9]+[.)])\s+", lines[i])):
                paragraph.append(lines[i])
                i += 1
            result.append("<p>" + inline("\n".join(paragraph)) + "</p>")
    return "\n".join(result)


def display_date(day: dt.date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}"


def block(page: str, pattern: str) -> str:
    match = re.search(pattern, page, re.S)
    if not match:
        raise ValueError("site shell is missing " + pattern)
    return match.group()


def render(writeups: list[dict], index: str, reference: str) -> str:
    head = block(reference, r"<!doctype html>.*?</head>")
    old_title = re.search(r"<title>(.*?)</title>", head).group(1)
    description = re.search(r'<meta name="description" content="(.*?)">', head).group(1)
    head = head.replace(old_title, "Security write-ups")
    head = head.replace(description, "Security wargame and CTF level write-ups.")
    head = head.replace("/vdw.html", "/security.html")
    header = block(index, r'<header class="site-header">.*?</header>')
    header = header.replace('href="#', 'href="index.html#')
    footer = block(index, r'<footer class="site-footer">.*?</footer>')
    platforms = {}
    for entry in writeups:
        platforms.setdefault(entry["platform"], []).append(entry)
    latest = max(entry["date"] for entry in writeups)
    summary = (f"{len(writeups)} write-ups across {len(platforms)} "
               f"{'platform' if len(platforms) == 1 else 'platforms'}, latest {display_date(latest)}")
    body = [head, '<body class="security-page">',
            '<a class="skip-link" href="#main">Skip to content</a>', header,
            '<main id="main">', '<div class="page-intro"><h1>Security write-ups</h1>',
            '<p class="deck"><!-- OWNER: one or two sentences in your own words --></p>',
            f'<p>{summary}</p></div>']
    ordered = sorted(platforms, key=lambda p: (min(e["date"] for e in platforms[p]), p))
    for number, platform in enumerate(ordered, 1):
        body.append(f'<section class="catalogue-section" aria-labelledby="platform-{number}">'
                    f'<h2 id="platform-{number}">{html.escape(platform)}</h2>'
                    '<div class="section-content">')
        entries = sorted(platforms[platform], key=lambda e: (e["date"], e["level"],
                                                           e["title"], e["path"].as_posix()))
        for entry in entries:
            body.append('<article><h3>' + html.escape(entry["title"]) + '</h3>')
            body.append(f'<p class="writeup-meta"><time datetime="{entry["date"].isoformat()}">'
                        f'{display_date(entry["date"])}</time> · Skills: '
                        f'{html.escape(entry["skills"])}</p>')
            for heading, text in zip(HEADINGS, entry["sections"]):
                body.append(f'<h4>{heading}</h4>\n{markdown(text)}')
            body.append('</article>')
        body.append('</div></section>')
    body.extend(['</main>', footer, '</body>', '</html>', ''])
    return "\n".join(body)


def publication_links(index: str, sitemap: str) -> tuple[str, str]:
    nav = block(index, r'<nav aria-label="Main navigation">.*?</nav>')
    if not re.search(r'<a\b[^>]*href=[\'"]security\.html[\'"]', nav):
        updated, count = re.subn(r'(<a href="#index">Index</a>)',
                                 r'\1 <a href="security.html">Security</a>', nav, count=1)
        if count != 1:
            raise ValueError("index.html:1: cannot find Index navigation link")
        index = index.replace(nav, updated, 1)
    tree = ET.fromstring(sitemap)
    namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    locations = [node.text for node in tree.iter(namespace + "loc")]
    canonical = re.search(r'<link rel="canonical" href="([^"]+)">', index)
    if not canonical:
        raise ValueError("index.html:1: missing canonical URL")
    url = canonical.group(1).rstrip("/") + "/security.html"
    if url not in locations:
        if '</urlset>' not in sitemap:
            raise ValueError("sitemap.xml:1: missing closing urlset")
        sitemap = sitemap.replace('</urlset>',
                                  f'  <url><loc>{html.escape(url)}</loc></url>\n</urlset>', 1)
    return index, sitemap


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--writeups", required=True, type=Path)
    ap.add_argument("--out", default=Path("security.html"), type=Path)
    ap.add_argument("--min", default=10, type=int, dest="minimum")
    ap.add_argument("--link", action="store_true")
    args = ap.parse_args()
    if args.minimum < 1:
        ap.error("--min must be at least 1")
    try:
        if not args.writeups.is_dir():
            refuse(args.writeups, 1, "write-ups folder does not exist")
        paths = sorted(p for p in args.writeups.rglob("*") if p.is_file() and
                       p.suffix.lower() == ".md" and p.name.lower() not in
                       ("readme.md", "template.md"))
        writeups = [load_writeup(path) for path in paths]
        if len(writeups) < args.minimum:
            print(f"{len(writeups)} write-ups; the page is published at {args.minimum}", file=sys.stderr)
            return 3
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        reference = (ROOT / "vdw.html").read_text(encoding="utf-8")
        if args.link:
            sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
            index, sitemap = publication_links(index, sitemap)
        page = render(writeups, index, reference)
        args.out.write_text(page, encoding="utf-8", newline="\n")
        if args.link:
            # Retain the site's original line endings when updating its files.
            for name, content in (("index.html", index), ("sitemap.xml", sitemap)):
                path = ROOT / name
                newline = "\r\n" if b"\r\n" in path.read_bytes() else "\n"
                if path.read_text(encoding="utf-8") != content:
                    path.write_text(content, encoding="utf-8", newline=newline)
        print(f"wrote {args.out} ({len(page.encode('utf-8'))} bytes)")
        return 0
    except (ValueError, OSError, ET.ParseError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
