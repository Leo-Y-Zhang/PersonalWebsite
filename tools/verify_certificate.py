#!/usr/bin/env python3
"""Re-verify the van der Waerden certificate rendered on index.html.

The page claims w(14; 2^12, 3, 4) > 56 and shows the colouring that witnesses
it. This script reads that colouring out of the page and re-derives the
property from the definition: it enumerates the arithmetic progressions itself
rather than comparing the page against a second copy of the answer.

Everything it checks is taken from the page: the parameters come from the
rendered claim, the colouring comes from the rendered cells, and the wording of
the caption is held to the same numbers. Standard library only.

Usage: python tools/verify_certificate.py [path/to/index.html]
Exit status 0 if the page is sound, 1 if it is not.
"""

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20,
}
NUMBERS = {v: k for k, v in WORDS.items()}


class Problem(Exception):
    pass


class PageParser(HTMLParser):
    """Pulls the certificate figure and the OEIS table out of the page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cells = []          # (css class, style, title) in document order
        self.cells_label = None  # aria-label of the cell grid
        self.caption = []        # figcaption text fragments
        self.rows = []           # OEIS table rows, as lists of cell texts
        self._in_cells = 0
        self._in_caption = 0
        self._in_table = 0
        self._row = None
        self._cell = None
        self._href = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = a.get("class", "").split()
        if tag == "div" and "cells" in classes:
            self._in_cells = 1
            self.cells_label = a.get("aria-label")
        elif tag == "i" and self._in_cells:
            self.cells.append((a.get("class"), a.get("style"), a.get("title")))
        elif tag == "figcaption":
            self._in_caption = 1
        elif tag == "table" and "seqs" in classes:
            self._in_table = 1
        elif self._in_table and tag == "tr":
            self._row = []
        elif self._in_table and tag in ("td", "th"):
            self._cell = []
        elif tag == "sup" and self._in_caption:
            # keep 2^12 from flattening to 212
            self.caption.append("^")
        elif tag == "a" and self._cell is not None:
            self._href = a.get("href", "")

    def handle_endtag(self, tag):
        if tag == "div" and self._in_cells:
            self._in_cells = 0
        elif tag == "figcaption":
            self._in_caption = 0
        elif tag == "table":
            self._in_table = 0
        elif self._in_table and tag in ("td", "th") and self._cell is not None:
            text = "".join(self._cell)
            if self._href:
                text = text + " <" + self._href + ">"
                self._href = None
            if self._row is not None:
                self._row.append(text)
            self._cell = None
        elif self._in_table and tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._in_caption:
            self.caption.append(data)
        if self._cell is not None:
            self._cell.append(data)


def squash(text):
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()


def find(pattern, text, what):
    m = re.search(pattern, text)
    if not m:
        raise Problem("could not read %s from the page" % what)
    return m


def has_progression(positions, length):
    """True if `positions` contains an arithmetic progression of `length`.

    Derived from the definition, by enumeration. No table of known answers.
    """
    if length <= 1:
        return bool(positions)
    members = set(positions)
    ordered = sorted(members)
    top = ordered[-1] if ordered else 0
    for start in ordered:
        for step in range(1, (top - start) // (length - 1) + 1):
            if all(start + k * step in members for k in range(length)):
                return [start + k * step for k in range(length)]
    return None


def verify(path):
    parser = PageParser()
    parser.feed(path.read_text(encoding="utf-8"))

    caption = squash("".join(parser.caption))

    # --- the claim, as rendered: w(j+r; 2^j, t_1 ... t_r) > n --------------
    m = find(r"w\((\d+);\s*2\^(\d+)((?:,\s*\d+)+)\)\s*>\s*(\d+)",
             caption, "the w(...) claim in the caption")
    colours, j, tail, n = int(m.group(1)), int(m.group(2)), m.group(3), int(m.group(4))
    targets = [int(x) for x in re.findall(r"\d+", tail)]
    if colours != j + len(targets):
        raise Problem("claim says %d colours but lists %d wildcard colours plus %d others"
                      % (colours, j, len(targets)))

    # --- the colouring, as rendered ----------------------------------------
    if not parser.cells:
        raise Problem("no certificate cells found in the page")
    if len(parser.cells) != n:
        raise Problem("claim is about [1,%d] but the page renders %d cells"
                      % (n, len(parser.cells)))

    kinds = {}        # css class -> kind, must be one-to-one
    classes = {}      # colour index -> positions
    wildcards = []
    for index, (css, style, title) in enumerate(parser.cells):
        if css is None or title is None or style is None:
            raise Problem("cell %d is missing a class, style or title" % (index + 1))
        s = find(r"--i:\s*(\d+)", style, "the --i index of cell %d" % (index + 1))
        if int(s.group(1)) != index:
            raise Problem("cell %d carries --i:%s; the cells are out of order"
                          % (index + 1, s.group(1)))
        t = re.fullmatch(r"position (\d+): (?:class (\d+)|(wildcard))", title.strip())
        if not t:
            raise Problem("cell %d has an unreadable title: %r" % (index + 1, title))
        if int(t.group(1)) != index + 1:
            raise Problem("cell %d claims to be position %s" % (index + 1, t.group(1)))
        kind = "wildcard" if t.group(3) else int(t.group(2))
        if kinds.setdefault(css, kind) != kind:
            raise Problem("class %r is used for both %s and %s"
                          % (css, kinds[css], kind))
        if kind == "wildcard":
            wildcards.append(index + 1)
        else:
            classes.setdefault(kind, []).append(index + 1)
    if len(set(kinds.values())) != len(kinds):
        raise Problem("two CSS classes render the same colour: %r" % (kinds,))

    # --- the property, re-derived ------------------------------------------
    if sorted(classes) != list(range(1, len(targets) + 1)):
        raise Problem("claim names %d non-wildcard colours, page uses %r"
                      % (len(targets), sorted(classes)))
    for colour, target in enumerate(targets, start=1):
        found = has_progression(classes[colour], target)
        if found:
            raise Problem("class %d contains the %d-term progression %s; "
                          "the certificate is invalid"
                          % (colour, target, found))
    # each of the j wildcard colours forbids a 2-term progression, so it can
    # hold at most one position: at most j wildcards in total.
    if len(wildcards) > j:
        raise Problem("%d wildcards but only %d singleton colours available: %s"
                      % (len(wildcards), j, wildcards))
    covered = sorted(wildcards + [p for ps in classes.values() for p in ps])
    if covered != list(range(1, n + 1)):
        raise Problem("the cells do not colour [1,%d] exactly once each" % n)

    # --- the page's own words, held to the same numbers ---------------------
    label = squash(parser.cells_label or "")
    m = find(r"(\d+)-cell", label, "the cell count in the grid's aria-label")
    if int(m.group(1)) != n:
        raise Problem("aria-label says %s cells, claim is about %d" % (m.group(1), n))
    m = find(r"(\d+) cells", caption, "the cell count in the caption")
    if int(m.group(1)) != n:
        raise Problem("caption says %s cells, claim is about %d" % (m.group(1), n))
    m = find(r"(\w+) wildcards", caption, "the wildcard count in the caption")
    word = m.group(1).lower()
    if word not in WORDS:
        raise Problem("caption says %r wildcards, which is not a number word" % word)
    if WORDS[word] != len(wildcards):
        raise Problem("caption says %s wildcards, page renders %d"
                      % (word, len(wildcards)))
    for colour, target in enumerate(targets, start=1):
        ordinal = NUMBERS.get(colour)
        if ordinal is None:
            raise Problem("no number word for class %d" % colour)
        m = find(r"(\w+) cells are class %s\b" % ordinal, label,
                 "the colour name for class %d" % colour)
        name = m.group(1)
        m = find(r"%s never carrying (\w+)" % re.escape(name), caption,
                 "what the caption says %s avoids" % name)
        said = m.group(1).lower()
        if WORDS.get(said) != target:
            raise Problem("caption says %s never carries %s, claim requires %d"
                          % (name, said, target))

    # --- the certificate against the term it is offered for -----------------
    m = find(r"(A\d{6})\D+a\((\d+)\)\s*=\s*(\d+)", caption,
             "the OEIS reference in the caption")
    seq, term, value = m.group(1), int(m.group(2)), int(m.group(3))
    if term != j:
        raise Problem("caption offers this as %s a(%d) but the claim has 2^%d; "
                      "the sequence is indexed by that exponent" % (seq, term, j))
    if value != n + 1:
        raise Problem("certificate proves w > %d, so a(%d) >= %d, but the caption "
                      "says %d" % (n, term, n + 1, value))
    row = [r for r in parser.rows if any(seq in c for c in r)]
    if not row:
        raise Problem("%s is not in the contributions table" % seq)
    row_text = squash(" ".join(row[0]))
    if not re.search(r"\ba\(%d\)" % term, row_text):
        raise Problem("table row for %s does not list a(%d): %r" % (seq, term, row_text))
    if not re.search(r"(?<![\d(])%d(?![\d)])" % value, row_text):
        raise Problem("table row for %s does not list the value %d: %r"
                      % (seq, value, row_text))

    print("certificate: %s a(%d) = %d" % (seq, term, value))
    print("claim:       w(%d; 2^%d, %s) > %d"
          % (colours, j, ", ".join(str(t) for t in targets), n))
    for colour, target in enumerate(targets, start=1):
        print("  class %d: %2d positions, no %d-term progression (checked by enumeration)"
              % (colour, len(classes[colour]), target))
    print("  wildcards: %d of %d singleton colours used" % (len(wildcards), j))
    print("  [1,%d] coloured exactly once, caption and aria-label agree" % n)
    print("OK: the rendered certificate proves w > %d, so a(%d) >= %d." % (n, term, value))


def main(argv):
    path = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent / "index.html"
    try:
        verify(path)
    except Problem as exc:
        print("FAIL: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
