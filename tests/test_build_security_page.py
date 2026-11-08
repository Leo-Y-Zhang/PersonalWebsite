"""Temporary-input tests for the gated security page and its safe Markdown.

Standard library only: python3 -m unittest discover -s tests -v
"""

import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("build_security_page", ROOT / "tools/build_security_page.py")
bsp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bsp)


def writeup(level=0, platform="Bandit", date="2026-11-10"):
    return (f"---\ntitle: Level {level}\nplatform: {platform}\nlevel: {level}\n"
            f"date: {date}\nskills: ssh, reading files\n---\n"
            "## What the level asked\nRead a file.\n\n"
            "## What I tried\nList the directory.\n\n"
            "## What worked\nUse `cat` to read it.\n\n"
            "## What it teaches\nCheck file names carefully.\n")


class SecurityPage(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.site = self.root / "site"
        (self.site / "tools").mkdir(parents=True)
        # --link is exercised only in this disposable copy of the site.
        for name in ("index.html", "vdw.html", "sitemap.xml", "tools/build_security_page.py"):
            shutil.copyfile(ROOT / name, self.site / name)
        self.writeups = self.root / "writeups"
        self.writeups.mkdir()
        self.out = self.site / "security.html"

    def fixtures(self, count=10):
        paths = []
        for level in range(count):
            platform = "Bandit" if level < 5 else "Other platform"
            folder = self.writeups / ("bandit" if level < 5 else "other")
            folder.mkdir(exist_ok=True)
            path = folder / f"level-{level:02}.md"
            path.write_text(writeup(level, platform), encoding="utf-8")
            paths.append(path)
        return paths

    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, str(self.site / "tools/build_security_page.py"),
             "--writeups", str(self.writeups), "--out", str(self.out), *args],
            cwd=self.root, capture_output=True, text=True)

    def mutate(self, old, new):
        paths = self.fixtures()
        path = paths[0]
        path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
        return path

    def assert_refused(self, path, line, message):
        result = self.run_tool()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"{path}:{line}:", result.stderr)
        self.assertIn(message, result.stderr)
        self.assertFalse(self.out.exists())

    def test_ten_builds_summary_shell_and_articles(self):
        self.fixtures()
        before = {name: (self.site / name).read_bytes() for name in ("index.html", "sitemap.xml")}
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        page = self.out.read_text(encoding="utf-8")
        self.assertEqual(page.count("<article>"), 10)
        self.assertIn("10 write-ups across 2 platforms, latest 10 November 2026", page)
        self.assertIn("<!-- OWNER: one or two sentences in your own words -->", page)
        self.assertIn('<body class="security-page">', page)
        self.assertIn("<title>Security write-ups</title>", page)
        index = (self.site / "index.html").read_text(encoding="utf-8")
        # Same navigation and footer; home-page anchors resolve back to index,
        # following the existing vdw.html convention.
        nav_pattern = r'<nav aria-label="Main navigation">.*?</nav>'
        self.assertEqual(re.search(nav_pattern, page, re.S).group(),
                         re.search(nav_pattern, index, re.S).group().replace('href="#', 'href="index.html#'))
        footer_pattern = r'<footer class="site-footer">.*?</footer>'
        self.assertEqual(re.search(footer_pattern, page, re.S).group(),
                         re.search(footer_pattern, index, re.S).group())
        reference = (self.site / "vdw.html").read_text(encoding="utf-8")
        for tag in re.findall(r'<(?:meta|link)\b[^>]*>', reference):
            if any(marker in tag for marker in ('description', 'canonical', 'og:title', 'og:url', 'twitter:title')):
                continue
            self.assertIn(tag, page)
        for name, content in before.items():
            self.assertEqual((self.site / name).read_bytes(), content)

    def test_nine_is_gated_and_writes_nothing(self):
        self.fixtures(9)
        before = {p: p.read_bytes() for p in self.site.rglob("*") if p.is_file()}
        result = self.run_tool("--link")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stderr.strip(), "9 write-ups; the page is published at 10")
        self.assertFalse(self.out.exists())
        self.assertEqual(before, {p: p.read_bytes() for p in self.site.rglob("*") if p.is_file()})

    def test_gate_preserves_existing_output(self):
        self.fixtures(9)
        self.out.write_text("existing page", encoding="utf-8")
        self.assertEqual(self.run_tool().returncode, 3)
        self.assertEqual(self.out.read_text(encoding="utf-8"), "existing page")

    def test_minimum_is_configurable(self):
        self.fixtures(1)
        result = self.run_tool("--min", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 write-ups across 1 platform", self.out.read_text(encoding="utf-8"))

    def test_missing_heading(self):
        path = self.mutate("## What it teaches\nCheck file names carefully.\n", "")
        self.assert_refused(path, 17, "missing heading ## What it teaches")

    def test_heading_order(self):
        path = self.mutate("## What I tried", "## What worked")
        self.assert_refused(path, 11, "expected heading ## What I tried")

    def test_empty_section(self):
        path = self.mutate("Read a file.", "")
        self.assert_refused(path, 8, "section must be non-empty")

    def test_empty_code_block_is_not_section_content(self):
        path = self.mutate("Read a file.", "```sh\n```")
        self.assert_refused(path, 8, "section must be non-empty")

    def test_missing_key(self):
        path = self.mutate("skills: ssh, reading files\n", "")
        self.assert_refused(path, 6, "missing front-matter key skills")

    def test_integer_level(self):
        path = self.mutate("level: 0", "level: zero")
        self.assert_refused(path, 4, "level must be an integer")

    def test_bad_date(self):
        path = self.mutate("2026-11-10", "2026-02-30")
        self.assert_refused(path, 5, "valid ISO date")

    def test_non_iso_date(self):
        path = self.mutate("2026-11-10", "20261110")
        self.assert_refused(path, 5, "valid ISO date")

    def test_long_token(self):
        path = self.mutate("Read a file.", "a" * 32)
        self.assert_refused(path, 9, "32 or more consecutive")

    def test_password(self):
        path = self.mutate("Read a file.", "PaSsWoRd = ab-cd-ef-gh")
        self.assert_refused(path, 9, "password assignment")

    def test_private_key(self):
        path = self.mutate("Read a file.", "-----BEGIN OPENSSH PRIVATE KEY-----")
        self.assert_refused(path, 9, "private key header")

    def test_secrets_in_code_still_refused(self):
        path = self.mutate("Read a file.", "```sh\n" + "a" * 32 + "\n```")
        self.assert_refused(path, 10, "32 or more consecutive")

    def test_language_tag_is_exempt(self):
        self.mutate("Read a file.", "```" + "a" * 40 + "\nprintf safe\n```")
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("<pre><code>printf safe</code></pre>", self.out.read_text(encoding="utf-8"))

    def test_additional_fence_info_is_not_exempt(self):
        path = self.mutate("Read a file.", "```sh " + "a" * 32 + "\nsafe\n```")
        self.assert_refused(path, 9, "32 or more consecutive")

    def test_unclosed_fence(self):
        path = self.mutate("Check file names carefully.", "```sh\ncat notes")
        self.assert_refused(path, 18, "unclosed fenced code block")

    def test_headings_inside_code_are_not_sections(self):
        self.mutate("Read a file.", "```sh\n## What worked\n```")
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("<pre><code>## What worked</code></pre>", self.out.read_text(encoding="utf-8"))

    def test_script_and_unsafe_links_are_text(self):
        self.mutate("Read a file.", '<script>alert("x")</script> [unsafe](javascript:alert) '
                    '[file](file:///tmp/test) [safe](https://example.test/?a=1&b=2)')
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        page = self.out.read_text(encoding="utf-8")
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;", page)
        self.assertIn("[unsafe](javascript:alert)", page)
        self.assertIn("[file](file:///tmp/test)", page)
        self.assertNotIn('href="javascript:', page)
        self.assertIn('<a href="https://example.test/?a=1&amp;b=2">safe</a>', page)

    def test_markdown_blocks_and_inline(self):
        self.mutate("Read a file.", 'A **bold** and *italic* paragraph with `<tag>`.'
                    ' Also __strong__ and _emphasis_.'
                    '\n\n### Detail\n- One\n- Two\n\n1. First\n2. Second'
                    '\n\n~~~sh\ncat <notes> & more\n~~~')
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        page = self.out.read_text(encoding="utf-8")
        for expected in ('<strong>bold</strong>', '<em>italic</em>', '<code>&lt;tag&gt;</code>',
                         '<strong>strong</strong>', '<em>emphasis</em>',
                         '<h5>Detail</h5>', '<ul><li>One</li><li>Two</li></ul>',
                         '<ol><li>First</li><li>Second</li></ol>',
                         '<pre><code>cat &lt;notes&gt; &amp; more</code></pre>'):
            self.assertIn(expected, page)

    def test_metadata_is_escaped(self):
        self.mutate("title: Level 0", 'title: <img src=x onerror="alert(1)">')
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        page = self.out.read_text(encoding="utf-8")
        self.assertIn('<h3>&lt;img src=x onerror=&quot;alert(1)&quot;&gt;</h3>', page)

    def test_ignored_files(self):
        self.fixtures()
        for name in ("README.md", "TEMPLATE.md"):
            (self.writeups / "bandit" / name).write_text("not a write-up", encoding="utf-8")
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_link_twice_is_idempotent(self):
        self.fixtures()
        for _ in range(2):
            result = self.run_tool("--link")
            self.assertEqual(result.returncode, 0, result.stderr)
            if _ == 0:
                before = {name: (self.site / name).read_bytes() for name in
                          ("index.html", "sitemap.xml", "security.html")}
        self.assertEqual(before, {name: (self.site / name).read_bytes() for name in before})
        index = (self.site / "index.html").read_text(encoding="utf-8")
        nav = re.search(r'<nav.*?</nav>', index, re.S).group()
        self.assertEqual(nav.count('<a href="security.html">Security</a>'), 1)
        self.assertLess(nav.index('>Index</a>'), nav.index('>Security</a>'))
        self.assertLess(nav.index('>Security</a>'), nav.index('>About</a>'))
        tree = ET.parse(self.site / "sitemap.xml")
        locations = [node.text for node in tree.iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
        self.assertEqual(sum(url.endswith("/security.html") for url in locations), 1)

    def test_platforms_ordered_by_first_date(self):
        paths = self.fixtures()
        paths[-1].write_text(writeup(9, "Other platform", "2026-11-01"), encoding="utf-8")
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        page = self.out.read_text(encoding="utf-8")
        self.assertLess(page.index('>Other platform</h2>'), page.index('>Bandit</h2>'))
        self.assertIn("latest 10 November 2026", page)

    def test_output_is_deterministic(self):
        self.fixtures()
        self.assertEqual(self.run_tool().returncode, 0)
        before = self.out.read_bytes()
        self.assertEqual(self.run_tool().returncode, 0)
        self.assertEqual(before, self.out.read_bytes())


if __name__ == "__main__":
    unittest.main()
