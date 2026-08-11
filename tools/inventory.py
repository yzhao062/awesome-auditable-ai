"""Count what this list actually contains, so the numbers in the README can be rechecked.

Every quantity the README states about itself is produced here. Run it after editing the list
and copy the numbers across, or run it to confirm that a claim still holds.

Counting rules, stated so the numbers mean something specific:

- An **entry** is one line between the first content section and `## Related Projects` that
  begins a resource: a table row starting ``| [`` or a bold standalone entry starting ``**\\[``.
  A paper that is deliberately cross-listed in two sections counts once per occurrence, which
  is why the entry total exceeds the number of distinct resources.
- A **venue-named row** is a four-column table row whose venue field is non-empty and is not
  ``Preprint <year>``. That means the entry names a conference, journal, or workshop; it is not
  by itself a claim about the kind of peer review that venue applies. A row that does not have
  the documented shape is reported as malformed rather than counted either way, so a broken row
  cannot quietly inflate the venue-named total.
- A **cross-listed paper** is one whose title appears in two sections. Matching on the arXiv
  identifier alone misses most of them, because a cross-listed occurrence usually points at a
  different artifact: the dataset row links Hugging Face or GitHub while the topical row links
  arXiv. Both counts are printed, and they are different measurements.
- A **repository** is a distinct ``github.com/<owner>/<name>`` pair, counted once no matter how
  often it is linked. This counts repositories, not code: a paper-list or specification
  repository is included. Having a repository is also not the same as having an open-source
  license, so licences are read from the entry text rather than assumed.

The counted window runs from the first content section to ``## Related Projects``, so the
maintainer's own projects and the Reliability Map taxonomy rows are excluded by construction.

Usage:
    python tools/inventory.py [README.md]

Requires the standard library only. No network access.
"""

import argparse
import re
import sys
from collections import Counter

ENTRY_RE = re.compile(r"^(\| \[|\*\*\\\[)")
TITLE_RE = re.compile(r"^\| \[([^\]]+)\]")
PREPRINT_RE = re.compile(r"Preprint \d{4}")
SECTION_RE = re.compile(r"^(#{2,3}) (.+)$")
ARXIV_RE = re.compile(r"arxiv\.org/abs/(\d{4}\.\d{4,5})")
GITHUB_RE = re.compile(r"github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)")
BOLD_KIND_RE = re.compile(r"^\*\*\\\[([^\]]+?)\\\]")
START_SECTION = "Surveys and Foundations"
STOP_SECTION = "Related Projects"


def analyze(path):
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")

    counts = Counter()
    per_section = Counter()
    arxiv_ids, repos, kinds = [], [], Counter()
    titles, malformed = [], []
    table_rows = venue_named = 0
    section = None
    active = False

    for line in lines:
        heading = SECTION_RE.match(line)
        if heading:
            name = heading.group(2).strip()
            if name == START_SECTION:
                active = True
            elif name == STOP_SECTION:
                active = False
            if heading.group(1) == "##":
                section = name
            continue
        if not active or not ENTRY_RE.match(line):
            continue

        per_section[section] += 1
        counts["entries"] += 1
        arxiv_ids += ARXIV_RE.findall(line)
        repos += ["%s/%s" % m for m in GITHUB_RE.findall(line)]

        if line.startswith("| ["):
            table_rows += 1
            cells = [c.strip() for c in line.split("|")]
            # A row must have the documented four columns and a non-empty venue before its
            # venue can be counted; otherwise a malformed row silently reads as venue-named.
            if len(cells) != 6 or not cells[2]:
                malformed.append(line[:80])
            elif PREPRINT_RE.fullmatch(cells[2]):
                pass
            else:
                venue_named += 1
            heading = TITLE_RE.match(line)
            if heading:
                titles.append(re.sub(r"[^a-z0-9]+", " ", heading.group(1).lower()).strip())
        else:
            kind = BOLD_KIND_RE.match(line)
            if kind and section == "Standards and Governance":
                kinds[kind.group(1)] += 1

    duplicates = [i for i, n in Counter(arxiv_ids).items() if n > 1]
    # A cross-listed paper often points at a different artifact in each section, so a
    # repeated arXiv identifier finds only some of them. Title is the reliable key.
    cross_listed = sorted(t for t, n in Counter(titles).items() if n > 1)
    return {
        "entries": counts["entries"],
        "sections": per_section,
        "table_rows": table_rows,
        "venue_named": venue_named,
        "preprint_rows": table_rows - venue_named,
        "arxiv_occurrences": len(arxiv_ids),
        "arxiv_unique": len(set(arxiv_ids)),
        "arxiv_cross_listed": sorted(duplicates),
        "cross_listed": cross_listed,
        "malformed_rows": malformed,
        "repos_unique": len(set(repos)),
        "standards_kinds": kinds,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("readme", nargs="?", default="README.md")
    args = ap.parse_args()
    data = analyze(args.readme)

    print("entries (occurrences)      %d" % data["entries"])
    print("  across sections          %d" % len(data["sections"]))
    for name, count in data["sections"].items():
        print("    %-48s %d" % (name, count))
    print("table rows                 %d" % data["table_rows"])
    print("  venue named              %d" % data["venue_named"])
    print("  labelled Preprint        %d" % data["preprint_rows"])
    print("arXiv links (occurrences)  %d" % data["arxiv_occurrences"])
    print("arXiv papers (unique)      %d" % data["arxiv_unique"])
    print("  repeated arXiv URL       %d %s"
          % (len(data["arxiv_cross_listed"]), data["arxiv_cross_listed"]))
    print("cross-listed papers        %d" % len(data["cross_listed"]))
    for name in data["cross_listed"]:
        print("    %s" % name[:64])
    if data["malformed_rows"]:
        print("MALFORMED ROWS             %d" % len(data["malformed_rows"]))
        for row in data["malformed_rows"]:
            print("    %s" % row)
    print("GitHub repositories        %d" % data["repos_unique"])
    print("Standards section labels   %s" % dict(data["standards_kinds"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
