"""Tests for tools/build_vdw_page.py.

The builder's promise is that it refuses to write vdw.html when its sources
disagree or when the page would say less than it claims. Each refusal is
exercised here against small synthetic inputs. The last test holds the
committed vdw.html to the builder: rendering the page's own data again must
give back the page byte for byte, so a hand edit to either one shows up.

Standard library only:  python -m unittest discover -s tests -v
"""

import contextlib
import datetime
import html
import importlib.util
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bvp = load_tool("build_vdw_page")

NAME = ("Van der Waerden numbers w(j+2; t_0,t_1,...,t_{j-1}, 3, 4) "
        "with t_0 = t_1 = ... = t_{j-1} = 2.")


def pinned_date(day):
    """Stand-in for the datetime module whose date.today() is `day`."""
    class PinnedDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(day.year, day.month, day.day)
    return mock.Mock(date=PinnedDate)


class Sources:
    """A MathRecords checkout and an OEIS snapshot directory, in a temp dir."""

    def __init__(self, root):
        self.mathrecords = root / "mathrecords"
        self.snapshots = root / "snapshots"
        (self.mathrecords / "vdw").mkdir(parents=True)
        self.snapshots.mkdir()

    def add(self, seq, values, offset=0, name=NAME, bfile=None, shape="list",
            cert=True):
        record = {"number": int(seq[1:]), "name": name,
                  "offset": "%d,1" % offset,
                  "data": ",".join(str(v) for v in values)}
        raw = [record] if shape == "list" else {"results": [record]}
        (self.snapshots / ("oeis_%s.json" % seq)).write_text(json.dumps(raw), encoding="utf-8")
        rows = bfile if bfile is not None else [
            (offset + i, v) for i, v in enumerate(values)]
        (self.mathrecords / ("b%s.txt" % seq[1:])).write_text(
            "# b-file for %s\n" % seq + "".join("%d %d\n" % r for r in rows),
            encoding="utf-8")
        if cert:
            for fseq, _, _, path in bvp.FAMILIES:
                if fseq == seq:
                    (self.mathrecords / path).write_text("certificate\n", encoding="utf-8")


class LoadAndRender(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.src = Sources(Path(tmp.name))

    def load(self, seq="A217058"):
        return bvp.load_family(seq, self.src.snapshots, self.src.mathrecords)

    def render(self, seq, new_idx):
        fam = self.load(seq)
        return bvp.family_html(fam, new_idx, "30 July 2026", "vdw/cert_n56.txt",
                               self.src.mathrecords)

    def assertRefuses(self, call, message):
        with self.assertRaises(SystemExit) as cm:
            call()
        self.assertRegex(str(cm.exception.code), r"^REFUSING: " + message)

    def test_agreeing_sources_load(self):
        self.src.add("A217058", [18, 21, 25])
        fam = self.load()
        self.assertEqual((fam["offset"], fam["values"], fam["name"]), (0, [18, 21, 25], NAME))

    def test_both_snapshot_shapes_load(self):
        self.src.add("A217058", [18, 21, 25], shape="results")
        self.assertEqual(self.load()["values"], [18, 21, 25])

    def test_value_disagreement_is_refused(self):
        self.src.add("A217058", [18, 21, 25], bfile=[(0, 18), (1, 22), (2, 25)])
        self.assertRefuses(self.load, r"A217058 b-file row 1=22 disagrees")

    def test_index_disagreement_is_refused(self):
        self.src.add("A217058", [18, 21, 25], bfile=[(1, 18), (2, 21), (3, 25)])
        self.assertRefuses(self.load, r"A217058 b-file row 1=18 disagrees")

    def test_shorter_bfile_is_refused(self):
        self.src.add("A217058", [18, 21, 25], bfile=[(0, 18), (1, 21)])
        self.assertRefuses(self.load, r"A217058 term-count mismatch")

    def test_longer_bfile_is_refused(self):
        self.src.add("A217058", [18, 21], bfile=[(0, 18), (1, 21), (2, 25)])
        self.assertRefuses(self.load, r"A217058 b-file row 2=25 disagrees")

    def test_missing_certificate_is_refused(self):
        self.src.add("A217058", [18, 21, 25], cert=False)
        self.assertRefuses(lambda: self.render("A217058", 2),
                           r"witness certificate vdw/cert_n56.txt not found")

    def test_new_term_is_marked_and_linked(self):
        self.src.add("A217058", [18, 21, 25])
        page = self.render("A217058", 2)
        self.assertIn('<td class="m"><strong>25</strong></td>', page)
        self.assertIn(bvp.GH + "vdw/cert_n56.txt", page)
        self.assertEqual(page.count("previously known"), 2)

    def test_new_term_missing_from_the_snapshot_is_refused(self):
        # A snapshot that stops before the new term would otherwise render a
        # table with no new row and no certificate link, and say nothing.
        self.src.add("A217058", [18, 21, 25])
        self.assertRefuses(lambda: self.render("A217058", 3),
                           r"A217058 a\(3\) is the new term, but the OEIS snapshot")

    def test_name_is_escaped(self):
        self.src.add("A217058", [18, 21, 25], name="w(j+2; 3, 4) with a < b & b > c")
        page = self.render("A217058", 2)
        self.assertIn("a &lt; b &amp; b &gt; c", page)
        self.assertNotIn("& b", page)


# --- the committed page against the builder ----------------------------------

def page_sources(page, src):
    """Recover each family's OEIS name and terms from a rendered vdw.html."""
    blocks = re.split(r'<h3><a href="https://oeis.org/(A\d{6})">A\d{6}</a></h3>', page)
    found = []
    for seq, body in zip(blocks[1::2], blocks[2::2]):
        name = re.search(r'<p class="seqdef">(.*?)</p>', body).group(1)
        name = (name.replace('<span class="m">w(</span>', "w(")
                .replace('<span class="m">)</span> with', ") with"))
        name = re.sub(r"t<sub>([^<]+)</sub>",
                      lambda m: "t_" + (m.group(1) if m.group(1).isdigit()
                                        else "{" + m.group(1) + "}"), name)
        name = html.unescape(name.replace("&hellip;", "..."))
        terms = re.findall(r'<th scope="row" class="m">a\((\d+)\)</th>\s*'
                           r'<td class="m">(?:<strong>)?(\d+)', body)
        offset = int(terms[0][0])
        src.add(seq, [int(v) for _, v in terms], offset=offset, name=name)
        found.append(seq)
    return found


class CommittedPage(unittest.TestCase):
    def test_vdw_html_is_what_the_builder_renders(self):
        committed = (ROOT / "vdw.html").read_text(encoding="utf-8")
        day = datetime.datetime.strptime(
            re.search(r"last regenerated (\d{1,2} \w+ \d{4})\.", committed).group(1),
            "%d %B %Y").date()
        with tempfile.TemporaryDirectory() as tmp:
            src = Sources(Path(tmp))
            self.assertEqual(page_sources(committed, src),
                             [seq for seq, _, _, _ in bvp.FAMILIES])
            out = Path(tmp) / "vdw.html"
            with mock.patch.object(bvp, "_dt", pinned_date(day)), \
                    contextlib.redirect_stdout(io.StringIO()):
                bvp.build(src.mathrecords, src.snapshots, out)
            rendered = out.read_text(encoding="utf-8")
        self.assertEqual(rendered, committed,
                         "vdw.html and tools/build_vdw_page.py have drifted apart; "
                         "regenerate the page rather than editing it by hand")


if __name__ == "__main__":
    unittest.main()
