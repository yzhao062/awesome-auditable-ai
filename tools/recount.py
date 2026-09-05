"""Rewrite every derived number in README.md and the social card.

Ten figures in the prose and on the card are computed from the list itself: entry and section
totals, table-row breakdown, arXiv and repository counts, the standards and framework labels,
and the destination counts the audit would cover. Keeping them correct by hand is what made a
batch of merges fail: each merge adds an entry, every figure moves, and the state between the
first merge and the last recount is inconsistent by construction. Six consecutive pushes to
main failed that way on 2026-09-04, and none of the six was a finding anyone could act on.

Every figure here is derived without network access, in well under a second. Only two things in
the audit paragraph need a real run: its date and its verdict. The prose keeps those in their
own sentence so that adding an entry never rewrites a claim about a run that happened.

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
    """Substitute exactly one occurrence, or fail loudly rather than silently doing nothing."""
    updated, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise SystemExit(
            "recount: found %d places to write %s, expected exactly 1. The sentence it edits "
            "was reworded; update the pattern in tools/recount.py rather than leaving the "
            "figure unmaintained." % (count, what)
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
        r"cites \d+ destinations it audits, and compares \d+ entry titles and \d+ identifiers",
        "cites %d destinations it audits, and compares %d entry titles and %d identifiers"
        % (figures["audited"], figures["title_checks"], figures["arxiv_ids_checked"]),
        "the live destination and comparison counts",
    )
    text = _sub(
        text,
        r"The \w+ destinations it does not audit",
        "The %s destinations it does not audit" % _word(figures["skipped"]),
        "the skipped-destination count",
    )
    return text


def rewrite_card(text, figures):
    for value, label in ((figures["entries"], "Entries"),
                         (figures["arxiv_unique"], "arXiv papers"),
                         (figures["repos_unique"], "Repos"),
                         (figures["title_checks"], "Titles checked")):
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
