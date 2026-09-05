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

def _load_sibling(name):
    spec = importlib.util.spec_from_file_location(
        name, pathlib.Path(__file__).with_name(name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inventory = _load_sibling("inventory")

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
        """The headline count is a claim about this repository, so recompute it here.

        The stated section count is parsed rather than hard-coded. Writing `nine` in here made
        a legitimately recounted README fail a test whose message says a figure is stale, and
        re-running the repair command could not fix it, because nothing was stale.
        """
        recount = _load_sibling("recount")
        data = inventory.analyze(str(README))
        text = README.read_text(encoding="utf-8")
        self.assertIn(
            "**%d entries across %s sections**"
            % (data["entries"], recount._word(len(data["sections"]))),
            text,
            "README.md states an entry count that inventory.py does not reproduce.",
        )

    def test_the_list_still_has_nine_sections(self):
        """A separate claim from the hero figure: the taxonomy itself is meant to be stable.

        A tenth section is a deliberate editorial act, so it should fail here, under a name
        that says the taxonomy changed, rather than inside a test about a stale number.
        """
        self.assertEqual(9, len(inventory.analyze(str(README))["sections"]))

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

    def test_readme_and_card_are_already_recounted(self):
        """Every derived figure at once, and the one that names its own fix.

        The tests above each catch one stale number and say which. This one runs the rewriter
        over the committed files and asserts it has nothing to change, which is the property
        that actually matters at merge time: a batch of merges moves ten figures across two
        files, and the operator needs one command rather than ten hand edits. It fails with the
        command that fixes it.
        """
        recount = _load_sibling("recount")
        figures = recount.compute(README)
        readme_text = README.read_text(encoding="utf-8")
        self.assertEqual(
            recount.rewrite_readme(readme_text, figures),
            readme_text,
            "README.md carries a derived figure that no longer matches the list. "
            "Run `python tools/recount.py README.md`.",
        )
        card = README.parent / "assets" / "social-card.html"
        if not card.exists():
            self.skipTest("social card not present")
        card_text = card.read_text(encoding="utf-8")
        self.assertEqual(
            recount.rewrite_card(card_text, figures),
            card_text,
            "assets/social-card.html is stale. Run `python tools/recount.py README.md`, then "
            "re-render the PNG with `python assets/render_social.py`.",
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


class RecountRewriter(unittest.TestCase):
    """What the rewriter must refuse, tested on text rather than on the committed README.

    These run regardless of README_CLAIMS_LENIENT: they are properties of the tool, not claims
    about the current list, so a contributor's pull request should run them too.
    """

    def setUp(self):
        self.recount = _load_sibling("recount")
        self.text = README.read_text(encoding="utf-8")
        self.figures = self.recount.compute(README)

    def test_a_second_copy_of_a_figure_is_refused_rather_than_left_stale(self):
        """One substitution capped at one cannot tell one target from two.

        A duplicated sentence used to absorb the single permitted rewrite and leave the copy
        behind, with the tool reporting success and the suite passing.
        """
        doubled = self.text + (
            "\nThe list cites 1 destinations it audits, among them 2 arXiv records and 3 "
            "entry-title labels a run checks against the arXiv page itself.\n"
        )
        with self.assertRaises(SystemExit) as raised:
            self.recount.rewrite_readme(doubled, self.figures)
        self.assertIn("found 2 places", str(raised.exception))

    def test_a_missing_target_is_refused_rather_than_silently_skipped(self):
        removed = self.text.replace("deliberately cross-listed", "deliberately grouped")
        with self.assertRaises(SystemExit) as raised:
            self.recount.rewrite_readme(removed, self.figures)
        self.assertIn("found 0 places", str(raised.exception))

    def test_the_cross_listed_count_is_written_and_not_only_computed(self):
        """It was computed and returned, but no rewriter consumed it, so it stayed manual."""
        stale = self.text.replace(
            "Five papers are deliberately cross-listed",
            "Four papers are deliberately cross-listed",
        )
        self.assertNotEqual(stale, self.text, "the sentence this test edits was reworded")
        self.assertEqual(
            self.recount.rewrite_readme(stale, self.figures),
            self.text,
            "recount did not restore the cross-listed-paper count.",
        )

    def test_one_cross_listed_paper_reads_as_a_singular_sentence(self):
        singular = dict(self.figures, cross_listed=1)
        self.assertIn(
            "One paper is deliberately cross-listed",
            self.recount.rewrite_readme(self.text, singular),
        )

    def test_a_skipped_total_above_the_word_table_falls_back_to_digits(self):
        many = dict(self.figures, skipped=11)
        self.assertIn(
            "The 11 destinations it does not audit",
            self.recount.rewrite_readme(self.text, many),
        )


if __name__ == "__main__":
    unittest.main()
