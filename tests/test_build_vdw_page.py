"""Tests for tools/build_vdw_page.py.

The builder's promise is that it refuses to write vdw.html when its sources
disagree or when the page would say less than it claims. Each refusal is
exercised here against small synthetic inputs. The last test holds the
committed vdw.html to the builder: rendering the page's own data again must
give back the page byte for byte, so a hand edit to the prose, provenance
labels or links, or a builder change the page was not regenerated for, shows
up. The terms, names, credits and regeneration date are read back out of the
page itself, so a consistent hand edit to those passes here; the terms, names
and credits are held to their sources only when the builder is run against a
MathRecords checkout and an OEIS snapshot.

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
AUTHOR = "_Tanbir Ahmed_, Sep 25 2012"
OWNER = "Leo Y. Zhang"
REGENERATED = datetime.date(2026, 11, 23)


def owner_line(j):
    """The EXTENSIONS line crediting a(j) to the page's owner."""
    return "a(%d) from _%s_, Jul 30 2026" % (j, OWNER)


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
            cert=True, author=AUTHOR, ext=None):
        """By default the entry's author is credited with every term but the
        last, which an EXTENSIONS line credits to the page's owner."""
        if ext is None:
            ext = [owner_line(offset + len(values) - 1)]
        record = {"number": int(seq[1:]), "name": name,
                  "offset": "%d,1" % offset,
                  "data": ",".join(str(v) for v in values),
                  "author": author}
        if ext:
            record["ext"] = ext  # the OEIS leaves the field out when there are none
        raw = [record] if shape == "list" else {"results": [record]}
        (self.snapshots / ("oeis_%s.json" % seq)).write_text(json.dumps(raw), encoding="utf-8")
        rows = bfile if bfile is not None else [
            (offset + i, v) for i, v in enumerate(values)]
        (self.mathrecords / ("b%s.txt" % seq[1:])).write_text(
            "# b-file for %s\n" % seq + "".join("%d %d\n" % r for r in rows),
            encoding="utf-8")
        if cert:
            for family in bvp.FAMILIES:
                if family[0] == seq:
                    (self.mathrecords / family[-1]).write_text("certificate\n",
                                                               encoding="utf-8")


class LoadAndRender(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.src = Sources(Path(tmp.name))

    def load(self, seq="A217058"):
        return bvp.load_family(seq, self.src.snapshots, self.src.mathrecords)

    def render(self, seq, owner_idx):
        fam = self.load(seq)
        return bvp.family_html(fam, owner_idx, "vdw/cert_n56.txt",
                               self.src.mathrecords, "23 November 2026")

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

    def test_owner_term_is_marked_and_linked(self):
        self.src.add("A217058", [18, 21, 25])
        page = self.render("A217058", 2)
        self.assertIn('<td class="m"><strong>25</strong></td>', page)
        self.assertIn(bvp.GH + "vdw/cert_n56.txt", page)
        self.assertEqual(page.count("<td>Tanbir Ahmed, Sep 2012</td>"), 2)

    def test_owner_term_missing_from_the_snapshot_is_refused(self):
        # A snapshot that stops before the owner's term would otherwise render a
        # table with no certified row and no certificate link, and say nothing.
        self.src.add("A217058", [18, 21, 25])
        self.assertRefuses(lambda: self.render("A217058", 3),
                           r"A217058 a\(3\) is the term with evidence here, "
                           r"but the OEIS snapshot")

    def test_name_is_escaped(self):
        self.src.add("A217058", [18, 21, 25], name="w(j+2; 3, 4) with a < b & b > c")
        page = self.render("A217058", 2)
        self.assertIn("a &lt; b &amp; b &gt; c", page)
        self.assertNotIn("& b", page)


class Credits(unittest.TestCase):
    """Each term is credited as its OEIS entry credits it.

    Driven through build(), so every family is present and the page is the one
    a reader would get. Each family's owner term is followed by two terms
    another contributor added; A217058 is then replaced per test.
    """

    OCHOCKI = "a(%d)-a(%d) from _Marek Ochocki_, Nov 05 2026"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.src = Sources(self.root)
        for family in bvp.FAMILIES:
            seq, j = family[0], family[1]
            self.src.add(seq, list(range(10, 13 + j)),
                         ext=[owner_line(j), self.OCHOCKI % (j + 1, j + 2)])

    def build(self):
        out = self.root / "vdw.html"
        with mock.patch.object(bvp, "_dt", pinned_date(REGENERATED)), \
                contextlib.redirect_stdout(io.StringIO()):
            bvp.build(self.src.mathrecords, self.src.snapshots, out)
        return out.read_text(encoding="utf-8")

    def cells(self, page, seq):
        """Term index -> provenance cell, for one family's table."""
        table = page.split('<a href="https://oeis.org/%s">' % seq, 1)[1]
        table = table.split("</table>", 1)[0]
        return {int(j): cell for j, cell in re.findall(
            r'a\((\d+)\)</th>\s*<td class="m">.*?</td>\s*<td>(.*?)</td>', table, re.S)}

    def assertRefuses(self, message):
        with self.assertRaises(SystemExit) as cm:
            self.build()
        self.assertRegex(str(cm.exception.code), r"^REFUSING: " + message)

    def test_each_term_carries_its_oeis_credit(self):
        self.src.add("A217058", list(range(18, 33)), ext=[
            "a(11) from _Tanbir Ahmed_, Dec 07 2012",
            owner_line(12),
            "Edited by _A. Editor_, Jan 02 2020",
            self.OCHOCKI % (13, 14)])
        page = self.build()
        cells = self.cells(page, "A217058")
        self.assertEqual(sorted(cells), list(range(15)))
        self.assertEqual({cells[j] for j in range(11)}, {"Tanbir Ahmed, Sep 2012"})
        self.assertEqual(cells[11], "Tanbir Ahmed, Dec 2012")
        self.assertTrue(cells[12].startswith(
            'Leo Y. Zhang, Jul 2026; <a href="%svdw/cert_n56.txt">witness colouring</a>'
            % bvp.GH), cells[12])
        self.assertEqual([cells[13], cells[14]], ["Marek Ochocki, Nov 2026"] * 2)
        self.assertNotIn("previously known", page)

    def test_tables_are_dated_by_the_regeneration(self):
        page = self.build()
        self.assertEqual(page.count("<caption>Terms and credits as recorded by the "
                                    "OEIS on 23 November 2026.</caption>"),
                         len(bvp.FAMILIES))

    def test_owner_evidence_on_someone_elses_term_is_refused(self):
        self.src.add("A217058", list(range(18, 33)), ext=[self.OCHOCKI % (12, 14)])
        self.assertRefuses(r"A217058 a\(12\) is credited to Marek Ochocki")

    def test_terms_added_without_indices_are_refused(self):
        self.src.add("A217058", list(range(18, 33)), ext=[
            owner_line(12), "More terms from _Marek Ochocki_, Nov 05 2026"])
        self.assertRefuses(r"A217058 EXTENSIONS line .* does not say which terms")

    def test_a_term_credited_twice_is_refused(self):
        self.src.add("A217058", list(range(18, 33)), ext=[
            owner_line(12), self.OCHOCKI % (12, 14)])
        self.assertRefuses(r"A217058 a\(12\) is credited twice")

    def test_a_credit_beyond_the_data_is_refused(self):
        self.src.add("A217058", list(range(18, 33)), ext=[
            owner_line(12), self.OCHOCKI % (13, 15)])
        self.assertRefuses(r"A217058 EXTENSIONS line .* credits a\(15\)")


# --- the committed page against the builder ----------------------------------

def oeis_credit(cell):
    """'Name, Mon YYYY' as shown on the page -> an OEIS '_Name_, Mon DD YYYY'.
    The page shows no day, so any day renders the same."""
    name, month, year = re.fullmatch(r"(.+), ([A-Z][a-z]{2}) (\d{4})",
                                     html.unescape(cell)).groups()
    return "_%s_, %s 01 %s" % (name, month, year)


def page_sources(page, src):
    """Recover each family's OEIS name, terms and credits from a rendered vdw.html.

    The credits come back as the entry's author for the first run of equally
    credited terms and one EXTENSIONS line for each later run."""
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
                           r'<td class="m">(?:<strong>)?(\d+)(?:</strong>)?</td>\s*'
                           r'<td>([^;<]*)', body)
        runs = []
        for j, _, credit in terms:
            if runs and runs[-1][2] == credit:
                runs[-1][1] = int(j)
            else:
                runs.append([int(j), int(j), credit])
        ext = [("a(%d)" % lo if lo == hi else "a(%d)-a(%d)" % (lo, hi))
               + " from " + oeis_credit(credit) for lo, hi, credit in runs[1:]]
        src.add(seq, [int(v) for _, v, _ in terms], offset=int(terms[0][0]),
                name=name, author=oeis_credit(runs[0][2]), ext=ext)
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
                             [family[0] for family in bvp.FAMILIES])
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
