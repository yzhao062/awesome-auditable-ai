"""Regression tests for tools/inventory.py.

The counting window is bounded by two literal heading names. A rename or a deletion of either
heading does not raise; it silently changes what gets counted, and the totals in the README
stay plausible while measuring a different set of lines. That is the failure this file exists to
catch: `## Related Projects` was once the stop heading, and when that section was removed the
window quietly ran to the end of the file.

    python -m unittest discover -s tools -p "test_*.py"
"""

import importlib.util
import os
import pathlib
import tempfile
import unittest

_SPEC = importlib.util.spec_from_file_location(
    "inventory", pathlib.Path(__file__).with_name("inventory.py")
)
inventory = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(inventory)

README = pathlib.Path(__file__).resolve().parent.parent / "README.md"

# A single-entry pull request moves every count in this class, and the contributor has no way
# to know the number a maintainer will merge it at: another PR queued ahead of it changes the
# correct value before this one lands. verify.yml sets this for the pull-request job only, so
# the claim stays a hard gate at the one moment it has a single true value: push to main and
# the weekly audit.
README_CLAIMS_LENIENT = os.environ.get("README_CLAIMS_LENIENT") == "1"


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


@unittest.skipIf(
    README_CLAIMS_LENIENT,
    "hero-count claims are enforced at merge time (push to main / weekly audit), not on "
    "contributor pull requests, where the correct number depends on merge order",
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

    def test_every_hero_number_is_reproducible(self):
        """The whole hero sentence is a set of claims, and each one drifts independently.

        Editing a single link can move a count nobody thought to recheck: replacing a dead
        GitHub link with a Hugging Face one dropped the unique-repository total by one while
        the entry total stayed put, and the stale figure shipped.
        """
        data = inventory.analyze(str(README))
        text = README.read_text(encoding="utf-8")
        claims = {
            "unique arXiv papers": data["arxiv_unique"],
            "GitHub repositories": data["repos_unique"],
        }
        for label, computed in claims.items():
            with self.subTest(claim=label):
                self.assertIn(
                    "%d %s" % (computed, label),
                    text,
                    "README.md does not state '%d %s'. inventory.py computes %d, so the hero "
                    "sentence is stating a number this repository cannot reproduce."
                    % (computed, label, computed),
                )

    def test_social_card_matches_the_inventory(self):
        """The card is the first thing a link preview shows, and nothing else checks it."""
        card = README.parent / "assets" / "social-card.html"
        if not card.exists():
            self.skipTest("social card not present")
        data = inventory.analyze(str(README))
        markup = card.read_text(encoding="utf-8")
        for value, label in ((data["entries"], "Entries"),
                             (data["arxiv_unique"], "arXiv papers"),
                             (data["repos_unique"], "Repos")):
            with self.subTest(label=label):
                self.assertIn(
                    '<div class="n">%d</div><div class="l">%s</div>' % (value, label),
                    markup,
                    "assets/social-card.html does not show %d for %s. Update the card and "
                    "re-render the PNG with assets/render_social.py." % (value, label),
                )


if __name__ == "__main__":
    unittest.main()
