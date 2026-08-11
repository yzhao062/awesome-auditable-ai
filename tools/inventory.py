"""Count what this list actually contains, so the numbers in the README can be rechecked.

Every quantity the README states about itself is produced here. Run it after editing the list
and copy the numbers across, or run it to confirm that a claim still holds.

Counting rules, stated so the numbers mean something specific:

- An **entry** is one line between the first content section and `## Related Projects` that
  begins a resource: a table row starting ``| [`` or a bold standalone entry starting ``**\\[``.
  A paper that is deliberately cross-listed in two sections counts once per occurrence, which
  is why the entry total exceeds the number of distinct resources.
- A **venue-named row** is a table row whose venue field is not ``Preprint``. That means the
  entry names a conference, journal, or workshop; it is not by itself a claim about the kind of
  peer review that venue applies.
- A **repository** is a distinct ``github.com/<owner>/<name>`` pair, counted once no matter how
  often it is linked. Having a repository is not the same as having an open-source license, so
  licences are reported separately and are read from the entry text rather than assumed.

Usage:
    python tools/inventory.py [README.md]

Requires the standard library only. No network access.
"""

import argparse
import re
import sys
from collections import Counter

ENTRY_RE = re.compile(r"^(\| \[|\*\*\\\[)")
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
            if len(cells) > 2 and not cells[2].startswith("Preprint"):
                venue_named += 1
        else:
            kind = BOLD_KIND_RE.match(line)
            if kind and section == "Standards and Governance":
                kinds[kind.group(1)] += 1

    duplicates = [i for i, n in Counter(arxiv_ids).items() if n > 1]
    return {
        "entries": counts["entries"],
        "sections": per_section,
        "table_rows": table_rows,
        "venue_named": venue_named,
        "preprint_rows": table_rows - venue_named,
        "arxiv_occurrences": len(arxiv_ids),
        "arxiv_unique": len(set(arxiv_ids)),
        "arxiv_cross_listed": sorted(duplicates),
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
    print("  cross-listed             %d %s"
          % (len(data["arxiv_cross_listed"]), data["arxiv_cross_listed"]))
    print("GitHub repositories        %d" % data["repos_unique"])
    print("Standards section labels   %s" % dict(data["standards_kinds"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
