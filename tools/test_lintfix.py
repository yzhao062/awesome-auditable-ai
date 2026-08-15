"""Regression tests for tools/lintfix.py.

The important property here is preservation, not idempotency. A transform that corrupts an
input on the first run and then leaves the corrupted form alone is perfectly idempotent, so
hashing two consecutive runs proves nothing. Each test below is a case where the transform
once changed content it should only have reformatted.

    python -m unittest discover -s tools -p "test_*.py"
"""

import importlib.util
import pathlib
import unittest

_SPEC = importlib.util.spec_from_file_location(
    "lintfix", pathlib.Path(__file__).with_name("lintfix.py")
)
lintfix = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(lintfix)

BADGE = "[![Awesome](https://awesome.re/badge-flat2.svg)](https://awesome.re)"


class Heading(unittest.TestCase):
    def test_existing_h1_is_preserved_when_renamed(self):
        """A renamed list must not gain a second, stale H1 from a hard-coded constant."""
        out = lintfix.transform("# Awesome Something Else %s\n\nbody\n" % BADGE)
        headings = [l for l in out.split("\n") if l.startswith("# ")]
        self.assertEqual(len(headings), 1)
        self.assertIn("Awesome Something Else", headings[0])

    def test_h1_without_badge_gains_one(self):
        out = lintfix.transform("# Awesome Renamed List\n\nbody\n")
        headings = [l for l in out.split("\n") if l.startswith("# ")]
        self.assertEqual(len(headings), 1)
        self.assertIn(BADGE, headings[0])

    def test_h1_inside_a_fence_is_not_taken_as_the_title(self):
        text = "# Real Title %s\n\n```markdown\n# Not The Title\n```\n" % BADGE
        out = lintfix.transform(text)
        self.assertIn("# Not The Title", out)
        self.assertEqual(len([l for l in out.split("\n") if l.startswith("# Real Title")]), 1)


class CodePreservation(unittest.TestCase):
    def test_inline_code_span_is_not_escaped(self):
        """A code span quoting link syntax is documentation, not a link to rewrite."""
        text = "# T %s\n\nUse `[[Code]](https://example.test/x)` in the Links column.\n" % BADGE
        self.assertIn("`[[Code]](https://example.test/x)`", lintfix.transform(text))

    def test_fenced_block_is_not_escaped(self):
        text = "# T %s\n\n```markdown\n**[Python] Tool** ([o/r](https://example.test/r))\n```\n" % BADGE
        self.assertIn("**[Python] Tool**", lintfix.transform(text))

    def test_real_reference_outside_code_is_still_escaped(self):
        text = "# T %s\n\n| a | [[Code]](https://example.test/x) |\n" % BADGE
        self.assertIn(r"[\[Code\]](https://example.test/x)", lintfix.transform(text))


class TableCells(unittest.TestCase):
    def test_cell_payloads_survive_reformatting(self):
        rows = [
            "| [A | B](https://example.test/a?x=1|2) | z |",
            "| `left | right` | z |",
            r"| escaped \| pipe | z |",
        ]
        for row in rows:
            with self.subTest(row=row):
                before = lintfix.split_table_row(row)
                after = lintfix.format_tables(["| A | B |", "| --- | --- |", row])
                self.assertEqual(lintfix.split_table_row(after[2]), before)


class Stability(unittest.TestCase):
    def test_transform_is_idempotent(self):
        text = "# Awesome Thing %s\n\n| A | B |\n|---|---|\n| x | y |\n" % BADGE
        once = lintfix.transform(text)
        self.assertEqual(lintfix.transform(once), once)

    def test_real_readme_is_a_fixed_point(self):
        """The committed README must already be normalized, so CI never rewrites it."""
        readme = pathlib.Path(__file__).resolve().parent.parent / "README.md"
        if not readme.exists():
            self.skipTest("README.md not present")
        text = readme.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
        self.assertEqual(lintfix.transform(text), text)

    def test_cross_listed_artifacts_are_live(self):
        """These URLs overwrite whatever the README has, so a stale one reverts a correction
        instead of failing. A dead link fixed by hand came back this way on the next run."""
        readme = pathlib.Path(__file__).resolve().parent.parent / "README.md"
        if not readme.exists():
            self.skipTest("README.md not present")
        text = readme.read_text(encoding="utf-8")
        for fragment, artifact in lintfix.CROSS_LISTED_ARTIFACTS:
            with self.subTest(fragment=fragment):
                self.assertIn(
                    artifact,
                    text,
                    "CROSS_LISTED_ARTIFACTS retargets %r to %s, which README.md does not "
                    "contain. lintfix would rewrite the row to that URL on its next run, so "
                    "update this tuple whenever the artifact moves."
                    % (fragment, artifact),
                )


if __name__ == "__main__":
    unittest.main()
