"""Tests for tools/verify_certificate.py.

CI already shows that the verifier accepts index.html as published. These show
the other half: that it rejects the page once the certificate, the claim or the
words around them are broken, one realistic edit at a time. A verifier that
printed OK whatever it was given would pass the CI step and fail every test
here.

Standard library only:  python -m unittest discover -s tests -v
"""

import contextlib
import importlib.util
import io
import itertools
import random
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vc = load_tool("verify_certificate")


def cell(position, kind, css=None):
    """One certificate cell, in exactly the markup index.html uses."""
    if kind == "wildcard":
        css, title = css or "w", "wildcard"
    else:
        css, title = css or "c%d" % kind, "class %d" % kind
    return '<i class="%s" style="--i:%d" title="position %d: %s"></i>' % (
        css, position - 1, position, title)


def brute_force_progression(positions, length):
    """Independent oracle: try every `length`-subset for equal gaps."""
    for combo in itertools.combinations(sorted(set(positions)), length):
        gaps = {b - a for a, b in zip(combo, combo[1:])}
        if len(gaps) == 1:
            return True
    return False


class HasProgression(unittest.TestCase):
    def test_agrees_with_brute_force(self):
        rng = random.Random(20260925)
        for _ in range(400):
            top = rng.randint(1, 40)
            positions = rng.sample(range(1, top + 1), rng.randint(0, min(top, 16)))
            for length in (2, 3, 4, 5):
                found = vc.has_progression(positions, length)
                self.assertEqual(bool(found), brute_force_progression(positions, length),
                                 (sorted(positions), length))
                if found:
                    self.assertEqual(len(found), length)
                    self.assertTrue(set(found) <= set(positions))
                    self.assertEqual(len({b - a for a, b in zip(found, found[1:])}), 1)

    def test_widest_step_is_searched(self):
        # 1, 28, 55 uses the largest step that fits below the top element.
        self.assertEqual(vc.has_progression([1, 28, 55], 3), [1, 28, 55])
        self.assertIsNone(vc.has_progression([1, 28, 54], 3))

    def test_empty_class_has_no_progression(self):
        self.assertIsNone(vc.has_progression([], 3))

    def test_shortest_targets(self):
        # Target 1 forbids a colour outright; target 2 lets it hold one position.
        self.assertTrue(vc.has_progression([5], 1))
        self.assertFalse(vc.has_progression([], 1))
        self.assertIsNone(vc.has_progression([5], 2))
        self.assertEqual(vc.has_progression([5, 9], 2), [5, 9])


class VerifyPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "index.html").read_text(encoding="utf-8")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "index.html"

    def tampered(self, *edits):
        text = self.page
        for old, new in edits:
            self.assertEqual(text.count(old), 1, "edit target must be unique: %r" % old)
            text = text.replace(old, new)
        return text

    def verify(self, text):
        self.path.write_text(text, encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            vc.verify(self.path)
        return out.getvalue()

    def assertRejected(self, text, message):
        with self.assertRaisesRegex(vc.Problem, message):
            self.verify(text)

    # --- the page as published ------------------------------------------------

    def test_published_page_is_accepted(self):
        out = self.verify(self.page)
        self.assertIn("claim:       w(14; 2^12, 3, 4) > 56", out)
        self.assertIn("class 1: 16 positions, no 3-term progression", out)
        self.assertIn("class 2: 28 positions, no 4-term progression", out)
        self.assertIn("wildcards: 12 of 12 singleton colours used", out)
        self.assertTrue(out.endswith(
            "OK: the rendered certificate proves w > 56, so a(12) >= 57.\n"))

    def test_exit_status(self):
        self.path.write_text(self.page, encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(vc.main(["verify", str(self.path)]), 0)
        self.path.write_text(self.tampered((cell(1, 2), cell(1, 1))), encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(vc.main(["verify", str(self.path)]), 1)
        self.assertTrue(err.getvalue().startswith("FAIL: "))

    # --- the colouring itself -------------------------------------------------

    def test_navy_three_term_progression_is_rejected(self):
        self.assertRejected(self.tampered((cell(1, 2), cell(1, 1))),
                            r"class 1 contains the 3-term progression")

    def test_ochre_four_term_progression_is_rejected(self):
        self.assertRejected(self.tampered((cell(4, 1), cell(4, 2))),
                            r"class 2 contains the 4-term progression")

    def test_thirteenth_wildcard_is_rejected(self):
        # Twelve colours may each hold one position; a thirteenth cannot fit,
        # even when the caption is updated to match.
        page = self.tampered((cell(4, 1), cell(4, "wildcard")),
                             ("twelve\n      wildcards", "thirteen\n      wildcards"))
        self.assertRejected(page, r"13 wildcards but only 12 singleton colours")

    def test_missing_cell_is_rejected(self):
        self.assertRejected(self.tampered((cell(56, 2) + "\n", "")),
                            r"\[1,56\] but the page renders 55 cells")

    def test_cells_out_of_order_are_rejected(self):
        first, second = cell(1, 2), cell(2, "wildcard")
        pair = first + "\n    " + second
        self.assertRejected(self.tampered((pair, second + "\n    " + first)),
                            r"cells are out of order")

    def test_position_titles_must_count_up(self):
        self.assertRejected(
            self.tampered((cell(3, 2), cell(3, 2).replace("position 3", "position 4"))),
            r"cell 3 claims to be position 4")

    def test_colour_outside_the_claim_is_rejected(self):
        # The claim has two non-wildcard colours; a third would escape every
        # progression check.
        self.assertRejected(self.tampered((cell(4, 1), cell(4, 3))),
                            r"claim names 2 non-wildcard colours, page uses \[1, 2, 3\]")

    def test_one_css_class_cannot_carry_two_colours(self):
        self.assertRejected(self.tampered((cell(4, 1), cell(4, 1, css="c2"))),
                            r"class 'c2' is used for both")

    def test_two_css_classes_cannot_carry_one_colour(self):
        self.assertRejected(self.tampered((cell(4, 1), cell(4, 1, css="c3"))),
                            r"two CSS classes render the same colour")

    # --- the claim, and the term it is offered for ----------------------------

    def test_bound_must_match_the_cells(self):
        self.assertRejected(self.tampered(("&gt;&nbsp;56.", "&gt;&nbsp;57.")),
                            r"claim is about \[1,57\] but the page renders 56 cells")

    def test_colour_count_must_add_up(self):
        self.assertRejected(self.tampered(("<span class=\"claim\">w(14;", "<span class=\"claim\">w(15;")),
                            r"claim says 15 colours")

    def test_value_must_follow_from_the_bound(self):
        self.assertRejected(self.tampered(("a(12)&nbsp;=&nbsp;57:", "a(12)&nbsp;=&nbsp;58:")),
                            r"a\(12\) >= 57, but the caption says 58")

    def test_term_must_be_indexed_by_the_exponent(self):
        self.assertRejected(self.tampered(("a(12)&nbsp;=&nbsp;57:", "a(11)&nbsp;=&nbsp;57:")),
                            r"offers this as A217058 a\(11\)")

    def test_claim_must_be_the_cited_sequence(self):
        # Ochre has no 5-term progression either, so this weaker claim is
        # true of the colouring; it is just not a statement about A217058,
        # which is w(j+2; 2^j, 3, 4). The bound it proves says nothing about
        # a(12).
        page = self.tampered(("3,&nbsp;4)&nbsp;&gt;", "3,&nbsp;5)&nbsp;&gt;"),
                             ("never carrying four", "never carrying five"))
        self.assertRejected(page, r"A217058 is w\(j\+2; 2\^j, 3, 4\)")

    def test_unknown_sequence_is_rejected(self):
        page = self.tampered(('<a href="https://oeis.org/A217058">A217058</a>&nbsp;a(12)',
                              '<a href="https://oeis.org/A217059">A217059</a>&nbsp;a(12)'))
        self.assertRejected(page, r"no definition of A217059")

    def test_contributions_table_must_list_the_value(self):
        self.assertRejected(
            self.tampered(('<td class="m">a(12)</td><td class="m">57</td>',
                           '<td class="m">a(12)</td><td class="m">58</td>')),
            r"table row for A217058 does not list the value 57")

    def test_contributions_table_must_list_the_term(self):
        self.assertRejected(
            self.tampered(('<td class="m">a(12)</td><td class="m">57</td>',
                           '<td class="m">a(13)</td><td class="m">57</td>')),
            r"table row for A217058 does not list a\(12\)")

    def test_contributions_table_must_carry_the_sequence(self):
        row = '<th scope="row"><a href="https://oeis.org/A217058">A217058</a></th>'
        self.assertRejected(self.tampered((row, row.replace("A217058", "A999999"))),
                            r"A217058 is not in the contributions table")

    # --- the words around it --------------------------------------------------

    def test_caption_must_state_each_target(self):
        self.assertRejected(self.tampered(("never carrying three", "never carrying five")),
                            r"caption says navy never carries five, claim requires 3")

    def test_caption_must_count_the_cells(self):
        self.assertRejected(self.tampered(("56 cells,", "55 cells,")),
                            r"caption says 55 cells, claim is about 56")

    def test_caption_must_count_the_wildcards(self):
        self.assertRejected(self.tampered(("twelve\n      wildcards", "eleven\n      wildcards")),
                            r"caption says eleven wildcards, page renders 12")

    def test_aria_label_must_count_the_cells(self):
        self.assertRejected(self.tampered(("The 56-cell certificate", "The 55-cell certificate")),
                            r"aria-label says 55 cells, claim is about 56")


if __name__ == "__main__":
    unittest.main()
