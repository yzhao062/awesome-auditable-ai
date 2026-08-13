"""Regression tests for tools/inventory.py.

The counting window is bounded by two literal heading names. A rename or a deletion of either
heading does not raise; it silently changes what gets counted, and the totals in the README
stay plausible while measuring a different set of lines. That is the failure this file exists to
catch: `## Related Projects` was once the stop heading, and when that section was removed the
window quietly ran to the end of the file.

    python -m unittest discover -s tools -p "test_*.py"
"""

import importlib.util
import pathlib
import tempfile
import unittest

_SPEC = importlib.util.spec_from_file_location(
    "inventory", pathlib.Path(__file__).with_name("inventory.py")
)
inventory = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(inventory)

README = pathlib.Path(__file__).resolve().parent.parent / "README.md"


def _analyze_text(text):
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / "README.md"
        path.write_text(text, encoding="utf-8")
        return inventory.analyze(str(path))


class WindowBoundaries(unittest.TestCase):
    def test_inventory_window_boundaries_exist(self):
        """Both boundary headings must be present, or the window means something else."""
        text = README.read_text(encoding="utf-8")
        for boundary in (inventory.START_SECTION, inventory.STOP_SECTION):
            with self.subTest(boundary=boundary):
                self.assertIn(
                    "\n## %s\n" % boundary,
                    text,
                    "inventory.py bounds its counting window on '## %s', which is not a "
                    "heading in README.md. Point the boundary at a heading that exists, or "
                    "the window silently covers the wrong span." % boundary,
                )

    def test_entries_after_the_stop_heading_are_not_counted(self):
        """The stop heading must actually stop counting, not merely be spelled correctly."""
        text = README.read_text(encoding="utf-8")
        baseline = _analyze_text(text)
        row = (
            "\n| [Probe](https://arxiv.org/abs/9999.99999) | Preprint 2026 | Probe row. "
            "| [\\[Code\\]](https://github.com/probe/probe) |\n"
        )
        after = _analyze_text(text + row)
        self.assertEqual(
            baseline["entries"],
            after["entries"],
            "an entry-shaped line appended after the stop heading changed the entry count, "
            "so the counting window is running past its intended end.",
        )

    def test_entries_before_the_start_heading_are_not_counted(self):
        """The maintainer's own section sits above the window and must add nothing to it."""
        text = README.read_text(encoding="utf-8")
        baseline = _analyze_text(text)
        marker = "\n## %s\n" % inventory.START_SECTION
        index = text.index(marker)
        row = (
            "| [Probe](https://arxiv.org/abs/9999.99999) | Preprint 2026 | Probe row. "
            "| [\\[Code\\]](https://github.com/probe/probe) |\n"
        )
        after = _analyze_text(text[:index] + "\n" + row + text[index:])
        self.assertEqual(
            baseline["entries"],
            after["entries"],
            "an entry-shaped line before the first counted section changed the entry count.",
        )


class ReadmeClaims(unittest.TestCase):
    def test_readme_states_the_entry_count_it_computes(self):
        """The headline count is a claim about this repository, so recompute it here."""
        data = inventory.analyze(str(README))
        text = README.read_text(encoding="utf-8")
        self.assertIn(
            "**%d entries across nine sections**" % data["entries"],
            text,
            "README.md states an entry count that inventory.py does not reproduce.",
        )
        self.assertEqual(9, len(data["sections"]))


if __name__ == "__main__":
    unittest.main()
