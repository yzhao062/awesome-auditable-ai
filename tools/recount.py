"""Rewrite every derived number in README.md and the social card.

Fourteen figures in the prose and on the card are computed from the list itself: entry, section
and cross-listing totals, the table-row breakdown, arXiv and repository counts, the standards
and framework labels, and the destination counts an audit would cover. Keeping them correct by
hand is what made a batch of merges fail: each merge adds an entry, every figure moves, and the
state between the first merge and the last recount is inconsistent by construction. Six
consecutive pushes to main failed that way on 2026-09-04, and none of the six was a finding
anyone could act on.

Every figure here is derived without network access, in well under a second. Three things in
the audit paragraph need a real run: its date, its verdict, and how many comparisons it
actually completed. The counts written here are what the list makes available to compare, which
is not the same number: a title is compared only when the page returns one. The prose keeps
those apart so that adding an entry never rewrites a claim about a run that happened.

    python tools/recount.py README.md            # rewrite in place
    python tools/recount.py README.md --check    # exit 1 if anything would change

Run it after every merge, before pushing. `--check` is what CI asserts.
"""

import argparse
import importlib.util
import pathlib
import re
import sys

_HERE = pathlib.Path(__file__).resolve().parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inventory = _load("inventory")
check_links = _load("check_links")

# Spelled out because the sentence reads as prose, not as a figure. That is also why it went
# stale unnoticed once: "three" stayed grammatical after a fourth badge was added.
NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
                6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def _word(count):
    return NUMBER_WORDS.get(count, str(count))


def _plural(count, noun):
    return "%s %s" % (_word(count), noun if count == 1 else noun + "s")


def compute(readme):
    """Return every derived figure, using no network access."""
    data = inventory.analyze(str(readme))

    rows = [(url, label) for url, label, _ in check_links.extract_links(str(readme))
            if url.startswith(("http://", "https://"))]
    urls = {url for url, _ in rows}
    audited = {url for url in urls if not check_links.is_self_chrome(url)}

    # Occurrences, not distinct pairs: the audit compares a title everywhere it appears, and two
    # cross-listed papers carry the same label twice. Counting distinct pairs here would report
    # 128 against the audit's own 130 and put the README a step out of line with its report.
    arxiv_titles = [(url, label) for url, label in rows
                    if url in audited
                    and check_links.ARXIV_ABS_RE.search(url)
                    and check_links.is_title_label(label)]

    return {
        "entries": data["entries"],
        "sections": len(data["sections"]),
        "table_rows": data["table_rows"],
        "venue_named": data["venue_named"],
        "preprint_rows": data["preprint_rows"],
        "arxiv_unique": data["arxiv_unique"],
        "repos_unique": data["repos_unique"],
        "standards": data["standards_kinds"].get("Standard", 0),
        "frameworks": data["standards_kinds"].get("Framework", 0),
        "cross_listed": len(data["cross_listed"]),
        "audited": len(audited),
        "skipped": len(urls - audited),
        "arxiv_ids_checked": len({u for u in audited if check_links.ARXIV_ABS_RE.search(u)}),
        "title_checks": len(arxiv_titles),
    }


def _sub(text, pattern, replacement, what):
    """Substitute one occurrence, failing loudly on none and on more than one.

    Passing count=1 here would cap the substitution before counting it, so the returned number
    could only ever be zero or one and a second stale copy of the sentence would survive with
    the guard reporting success. Substituting everywhere and rejecting a total other than one
    is what makes the count mean what the error message says.
    """
    updated, count = re.subn(pattern, replacement, text)
    if count != 1:
        raise SystemExit(
            "recount: found %d places to write %s, expected exactly 1. Either the sentence it "
            "edits was reworded, or the figure now appears twice and one copy would go stale. "
            "Fix the text, or update the pattern in tools/recount.py." % (count, what)
        )
    return updated


def rewrite_readme(text, figures):
    text = _sub(
        text,
        r"\*\*\d+ entries across \w+ sections\*\*, covering \d+ unique arXiv papers, "
        r"\d+ GitHub repositories, \d+ standards, and \w+ frameworks?",
        "**%d entries across %s sections**, covering %d unique arXiv papers, %d GitHub "
        "repositories, %d standards, and %s"
        % (figures["entries"], _word(figures["sections"]), figures["arxiv_unique"],
           figures["repos_unique"], figures["standards"],
           _plural(figures["frameworks"], "framework")),
        "the hero totals",
    )
    text = _sub(
        text,
        r"of the \d+ table rows, \d+ name a publication venue and \d+ are marked Preprint",
        "of the %d table rows, %d name a publication venue and %d are marked Preprint"
        % (figures["table_rows"], figures["venue_named"], figures["preprint_rows"]),
        "the table-row breakdown",
    )
    text = _sub(
        text,
        r"cites \d+ destinations it audits, among them \d+ arXiv records and \d+ entry-title "
        r"labels",
        "cites %d destinations it audits, among them %d arXiv records and %d entry-title labels"
        % (figures["audited"], figures["arxiv_ids_checked"], figures["title_checks"]),
        "the live destination and eligible-comparison counts",
    )
    text = _sub(
        text,
        r"The \w+ destinations it does not audit(?= are this repository's own badges)",
        "The %s destinations it does not audit" % _word(figures["skipped"]),
        "the skipped-destination count",
    )
    text = _sub(
        text,
        r"\b\w+ papers? (?:are|is) deliberately cross-listed",
        "%s %s deliberately cross-listed"
        % (_plural(figures["cross_listed"], "paper").capitalize(),
           "is" if figures["cross_listed"] == 1 else "are"),
        "the cross-listed-paper count",
    )
    return text


def rewrite_card(text, figures):
    # The card carries inventory counts only. It used to show "Titles checked", which reads as
    # work already done while the figure it displayed was the number of titles a run would be
    # eligible to check. A card is the wrong surface for a claim that needs a precondition, so
    # the precise version of it lives in the README instead.
    for value, label in ((figures["entries"], "Entries"),
                         (figures["arxiv_unique"], "arXiv papers"),
                         (figures["repos_unique"], "Repos"),
                         (figures["standards"], "Standards")):
        text = _sub(
            text,
            r'<div class="n">\d+</div><div class="l">%s</div>' % re.escape(label),
            '<div class="n">%d</div><div class="l">%s</div>' % (value, label),
            "the card's %s figure" % label,
        )
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("readme", nargs="?", default=str(_HERE.parent / "README.md"))
    parser.add_argument("--check", action="store_true",
                        help="exit 1 when a figure is stale, writing nothing")
    args = parser.parse_args(argv)

    readme = pathlib.Path(args.readme).resolve()
    card = readme.parent / "assets" / "social-card.html"
    figures = compute(readme)

    targets = [(readme, rewrite_readme)]
    if card.exists():
        targets.append((card, rewrite_card))

    stale = []
    for path, rewrite in targets:
        before = path.read_text(encoding="utf-8")
        after = rewrite(before, figures)
        if before == after:
            continue
        stale.append(path.name)
        if not args.check:
            path.write_text(after, encoding="utf-8", newline="\n")

    for key in sorted(figures):
        print("%-18s %d" % (key, figures[key]))

    if not stale:
        print("\nevery derived figure already matches the list")
        return 0
    if args.check:
        print("\nstale: %s. Run `python tools/recount.py README.md`." % ", ".join(stale))
        return 1
    print("\nrewrote: %s" % ", ".join(stale))
    if "social-card.html" in stale:
        print("re-render the PNG with `python assets/render_social.py`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
