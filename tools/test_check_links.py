"""Regression tests for tools/check_links.py.

Every case below is a way the audit was once able to report success while the list contained a
wrong or unverifiable entry. They are kept as tests because the value of the audit is entirely
in what it refuses to pass, and each of these was a real false pass at some point.

No network access: responses are supplied directly. Run with:

    python -m unittest discover -s tools -p "test_*.py"
"""

import builtins
import importlib.util
import io
import pathlib
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

_SPEC = importlib.util.spec_from_file_location(
    "check_links", pathlib.Path(__file__).with_name("check_links.py")
)
check_links = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_links)


def meta(identifier, title):
    return ('<meta name="citation_arxiv_id" content="%s">'
            '<meta name="citation_title" content="%s">' % (identifier, title))


class _Sink(io.StringIO):
    """Stand-in for the report file so a test never writes to disk."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass


def run_audit(links, responses, argv=None):
    """Run main() over fixed links and responses; return (exit_code, report_text)."""
    sink = _Sink()
    with patch.object(check_links, "extract_links", return_value=links), \
         patch.object(check_links, "fetch", side_effect=responses), \
         patch.object(sys, "argv", argv or ["check_links.py"]), \
         patch("time.sleep"), \
         patch.object(builtins, "open", return_value=sink):
        code = check_links.main()
    return code, sink.getvalue()


class TitleComparison(unittest.TestCase):
    def test_different_papers_in_a_series_disagree(self):
        """"Part I" against "Part II" scores 0.995; similarity alone must not pass it."""
        verdict, _ = check_links.compare_titles(
            "Machine Learning for Fluid Mechanics Part I: Foundations",
            "Machine Learning for Fluid Mechanics Part II: Applications",
        )
        self.assertEqual(verdict, "MISMATCH")

    def test_differing_number_disagrees(self):
        verdict, _ = check_links.compare_titles(
            "A Study of Scaling Laws in 3 Domains", "A Study of Scaling Laws in 5 Domains"
        )
        self.assertEqual(verdict, "MISMATCH")

    def test_latex_and_unicode_notation_agree(self):
        """arXiv reports LaTeX; this list writes Unicode. Notation is not disagreement."""
        for ours, theirs in (
            ("τ²-Bench: Evaluating Conversational Agents", r"$\tau^2$-Bench: Evaluating Conversational Agents"),
            ("τ-bench: A Benchmark for Tool-Agent-User Interaction", r"$\tau$-bench: A Benchmark for Tool-Agent-User Interaction"),
            ("Δ-Calibration for Agents", r"$\Delta$-Calibration for Agents"),
        ):
            with self.subTest(ours=ours):
                self.assertEqual(check_links.compare_titles(ours, theirs)[0], "match")

    def test_punctuation_and_case_are_not_disagreement(self):
        verdict, _ = check_links.compare_titles(
            "HiL-Bench: Do Agents Know When to Ask for Help?",
            "HiL-Bench - do agents know when to ask for help",
        )
        self.assertEqual(verdict, "match")


class ExitCode(unittest.TestCase):
    URL = "https://arxiv.org/abs/2601.12345"
    TITLE = "A Sufficiently Long Paper Title For Checking"

    def test_wrong_paper_with_matching_identifier_fails(self):
        code, _ = run_audit(
            [(self.URL, self.TITLE, "link")],
            [(200, meta("2601.12345", "An Entirely Different Paper About Fish"))],
        )
        self.assertEqual(code, 1)

    def test_legacy_arxiv_identifier_is_checked(self):
        """A legacy identifier is a real arXiv reference and must not skip verification."""
        code, _ = run_audit(
            [("https://arxiv.org/abs/hep-th/9901001", self.TITLE, "link")],
            [(200, meta("hep-th/9901001", "String Junctions and Their Duals"))],
        )
        self.assertEqual(code, 1)

    def test_every_label_for_one_destination_is_checked(self):
        """A correct first occurrence must not hide a wrong later one."""
        code, _ = run_audit(
            [(self.URL, "The Correct Paper Title Here", "link"),
             (self.URL, "An Entirely Different Work Indeed", "link")],
            [(200, meta("2601.12345", "The Correct Paper Title Here"))],
        )
        self.assertEqual(code, 1)

    def test_single_quoted_and_reordered_meta_is_read(self):
        body = ("<meta content='2601.99999' name='citation_arxiv_id'>"
                "<meta content='Completely unrelated paper' name='citation_title'>")
        code, _ = run_audit([(self.URL, self.TITLE, "link")], [(200, body)])
        self.assertEqual(code, 1)

    def test_metadata_absent_is_not_a_pass_under_strict(self):
        code, report = run_audit([(self.URL, self.TITLE, "link")], [(200, "<html>nothing</html>")])
        self.assertEqual(code, 1)
        self.assertIn("| arXiv pages where a check could not run (unverified) | 1 |", report)

    def test_identifier_disagreement_fails(self):
        code, _ = run_audit(
            [(self.URL, self.TITLE, "link")], [(200, meta("9999.99999", self.TITLE))]
        )
        self.assertEqual(code, 1)

    def test_clean_run_passes(self):
        code, _ = run_audit(
            [(self.URL, self.TITLE, "link")], [(200, meta("2601.12345", self.TITLE))]
        )
        self.assertEqual(code, 0)


class ReachabilityPolicy(unittest.TestCase):
    WALL = "https://www.iso.org/standard/42001"

    def test_known_wall_excuses_only_its_documented_status(self):
        self.assertEqual(run_audit([(self.WALL, None, "link")], [(403, "")])[0], 0)

    def test_known_wall_does_not_mask_an_outage(self):
        """A timeout at an excused URL is an outage, not the documented bot wall."""
        self.assertEqual(run_audit([(self.WALL, None, "link")], [("TimeoutError", "")])[0], 1)

    def test_self_chrome_is_skipped_rather_than_fetched(self):
        """A rate limit on this repository's own pages must not fail an audit of other work."""
        chrome = "https://github.com/%s/actions/workflows/verify.yml" % check_links.SELF_REPO
        code, report = run_audit([(chrome, None, "link")], [(429, "")])
        self.assertEqual(code, 0)
        self.assertIn("Repository Chrome Not Audited", report)
        self.assertIn(chrome, report)

    def test_self_chrome_covers_the_badge_image_and_its_link(self):
        for path in ("actions/workflows/verify.yml",
                     "actions/workflows/verify.yml/badge.svg",
                     "commits/main"):
            with self.subTest(path=path):
                url = "https://github.com/%s/%s" % (check_links.SELF_REPO, path)
                self.assertTrue(check_links.is_self_chrome(url))

    def test_content_and_other_repositories_stay_in_the_audit(self):
        """The exclusion must not quietly stop checking real cited resources."""
        for url in (
            "https://github.com/yzhao062/auditable",
            "https://github.com/yzhao062/grade",
            "https://github.com/%s" % check_links.SELF_REPO,
            "https://github.com/%s/blob/main/CONTRIBUTING.md" % check_links.SELF_REPO,
            "https://github.com/someone-else/awesome-auditable-ai/actions",
        ):
            with self.subTest(url=url):
                self.assertFalse(check_links.is_self_chrome(url))

    def test_self_repo_still_matches_the_git_remote(self):
        """SELF_REPO is a literal, and a literal that stops matching excludes nothing while
        looking like it still does. A rename must fail here rather than in production."""
        try:
            remote = subprocess.run(
                ["git", "-C", str(pathlib.Path(__file__).resolve().parent.parent),
                 "remote", "get-url", "origin"],
                capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            self.skipTest("git is unavailable")
        if remote.returncode != 0:
            self.skipTest("no origin remote configured")
        url = remote.stdout.strip().removesuffix(".git")
        self.assertTrue(
            url.endswith(check_links.SELF_REPO),
            "SELF_REPO is %r but origin is %r. The chrome exclusion matches on this literal, "
            "so a stale value silently audits pages it was written to skip."
            % (check_links.SELF_REPO, url),
        )

    def test_readme_states_the_destination_count_it_would_audit(self):
        """The audited-destination total is a claim in the prose, and it moves whenever any
        link is added anywhere. Two people editing different sections each computed it against
        a base missing the other's link, and the stated figure was short by one."""
        readme = pathlib.Path(__file__).resolve().parent.parent / "README.md"
        text = readme.read_text(encoding="utf-8")
        stated = re.search(r"across (\d+) destinations", text)
        if stated is None:
            self.skipTest("README states no destination count")
        urls = {
            u for u, _, _ in check_links.extract_links(str(readme))
            if u.startswith(("http://", "https://"))
        }
        audited = {u for u in urls if not check_links.is_self_chrome(u)}
        self.assertEqual(
            len(audited),
            int(stated.group(1)),
            "README.md says it audits %s destinations; extracting the links finds %d. Any link "
            "added or removed moves this, so recount instead of carrying the old number."
            % (stated.group(1), len(audited)),
        )

    def test_readme_states_the_number_of_destinations_it_skips(self):
        """This total is spelled as a word, so it never reads like a figure that needs
        recomputing. Adding a contributor strip pointing at this repository's own graphs page
        made it four while the prose still said three, and nothing failed: the sentence stayed
        grammatical and stayed wrong, which is the whole failure mode this file exists for."""
        readme = pathlib.Path(__file__).resolve().parent.parent / "README.md"
        text = readme.read_text(encoding="utf-8")
        stated = re.search(r"The (\w+) destinations it does not audit", text)
        if stated is None:
            self.skipTest("README states no skipped-destination count")
        written = {"two": 2, "three": 3, "four": 4, "five": 5,
                   "six": 6, "seven": 7, "eight": 8, "nine": 9}
        urls = {
            u for u, _, _ in check_links.extract_links(str(readme))
            if u.startswith(("http://", "https://"))
        }
        skipped = {u for u in urls if check_links.is_self_chrome(u)}
        self.assertEqual(
            written.get(stated.group(1)),
            len(skipped),
            "README.md says there are %r destinations it does not audit; extracting the links "
            "finds %d. Any badge or link to this repository's own pages moves this."
            % (stated.group(1), len(skipped)),
        )

    def test_every_excused_destination_is_still_in_the_readme(self):
        """An exemption for a link that has been removed stops excusing anything and starts
        hiding the fact that the list no longer cites the source it was written for."""
        readme = pathlib.Path(__file__).resolve().parent.parent / "README.md"
        text = readme.read_text(encoding="utf-8")
        for url, status in check_links.KNOWN_BOT_WALLS:
            with self.subTest(url=url):
                self.assertIn(
                    url,
                    text,
                    "KNOWN_BOT_WALLS excuses %s (status %d), which README.md no longer links. "
                    "Remove the exemption, or restore the link it was written for."
                    % (url, status),
                )

    def test_unresolvable_hostname_blocks_a_pull_request(self):
        """A mistyped hostname is the most common broken link in a contribution."""
        code, _ = run_audit(
            [("https://nope.invalid/x", None, "link")], [("DNSError", "")],
            ["check_links.py", "--failure-policy", "pull-request"],
        )
        self.assertEqual(code, 1)

    def test_transient_server_error_only_warns_on_a_pull_request(self):
        code, _ = run_audit(
            [("https://example.test/x", None, "link")], [(503, "")],
            ["check_links.py", "--failure-policy", "pull-request"],
        )
        self.assertEqual(code, 0)

    def test_404_fails_under_both_policies(self):
        for policy in ("strict", "pull-request"):
            with self.subTest(policy=policy):
                code, _ = run_audit(
                    [("https://example.test/gone", None, "link")], [(404, "")],
                    ["check_links.py", "--failure-policy", policy],
                )
                self.assertEqual(code, 1)


class Extraction(unittest.TestCase):
    def _extract(self, markdown):
        path = pathlib.Path(__file__).with_name("_extract_fixture.md")
        path.write_text(markdown, encoding="utf-8")
        try:
            return check_links.extract_links(str(path))
        finally:
            path.unlink()

    def test_fenced_code_is_not_a_link(self):
        found = self._extract("```\n@misc{x, url={https://example.test/bibtex}}\n```\n")
        self.assertEqual(found, [])

    def test_balanced_parentheses_in_destination(self):
        found = self._extract("[A paper](https://example.test/path_(variant))\n")
        self.assertEqual([u for u, _, _ in found], ["https://example.test/path_(variant)"])

    def test_badge_image_inside_a_relative_link_is_found(self):
        found = self._extract("[![PRs Welcome](https://example.test/badge.svg)](CONTRIBUTING.md)\n")
        self.assertIn("https://example.test/badge.svg", [u for u, _, _ in found])

    def test_html_comment_is_not_a_link(self):
        self.assertEqual(self._extract("<!-- https://example.test/hidden -->\n"), [])


if __name__ == "__main__":
    unittest.main()
