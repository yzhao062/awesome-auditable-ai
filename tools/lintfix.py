#!/usr/bin/env python3
"""Apply deterministic awesome-lint remediations to a Markdown README."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


# Used only when the document has no H1 at all. The existing H1 is preserved otherwise, so
# renaming the list does not leave a stale heading behind: hard-coding the title here once
# caused a rename to produce two H1 headings, with the stale one rendered first.
DEFAULT_TITLE = (
    "# Awesome Auditable AI "
    "[![Awesome](https://awesome.re/badge-flat2.svg)](https://awesome.re)"
)
STANDALONE_AWESOME_BADGE = (
    "[![Awesome](https://awesome.re/badge-flat2.svg)](https://awesome.re)"
)
CONTENTS = """## Contents

- [The Reliability Map](#the-reliability-map)
- [Surveys and Foundations](#surveys-and-foundations)
- [Failure Attribution and Diagnosis](#failure-attribution-and-diagnosis)
- [Reliability and Robustness](#reliability-and-robustness)
- [Runtime Monitoring and Guardrails](#runtime-monitoring-and-guardrails)
- [Audit Trails and Decision Records](#audit-trails-and-decision-records)
- [Security Auditing and Scanners](#security-auditing-and-scanners)
- [Datasets and Benchmarks](#datasets-and-benchmarks)
- [Tools and Platforms](#tools-and-platforms)
- [Standards and Governance](#standards-and-governance)
- [Related Projects](#related-projects)
- [Maintained By](#maintained-by)
- [Citation](#citation)"""

CONTENTS_BLOCK_RE = re.compile(
    r"<details>\n"
    r"<summary><b>Table of Contents</b></summary>\n"
    r".*?"
    r"</details>",
    re.DOTALL,
)
H2_RE = re.compile(r"^##\s+(.+?)\s*$")
PRIMARY_LINK_RE = re.compile(r"\[([^]\n]+)\]\(([^)\n]+)\)")
DOUBLE_BRACKET_LINK_RE = re.compile(
    r"(?:\[\[([^]\n]+)\]\]|\[\\\[([^]\n]+)\\\]\])\(([^)\n]+)\)"
)
DELIMITER_CELL_RE = re.compile(r":?-{3,}:?")

CROSS_LISTED_ARTIFACTS = (
    ("TRAIL: Trace Reasoning", "https://github.com/patronus-ai/trail-benchmark"),
    (
        "Which Agent Causes Task Failures and When?",
        "https://github.com/ag2ai/Agents_Failure_Attribution",
    ),
    (
        "Aegis: Automated Error Generation and Attribution",
        "https://huggingface.co/datasets/Fancylalala/AEGIS",
    ),
    ("bench: A Benchmark for Tool-Agent-User", "https://github.com/sierra-research/tau-bench"),
)

IGNORED_RELIABILITY_LISTS = (
    "<summary><b>Common failure modes:</b>",
    "<summary><b>Evaluation axes:</b>",
    "<summary><b>Open gaps:</b>",
)


def split_table_row(line: str) -> list[str] | None:
    """Split a pipe table row without splitting Markdown constructs or code spans."""
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None

    cells: list[str] = []
    cell: list[str] = []
    bracket_depth = 0
    parenthesis_depth = 0
    code_ticks = 0
    i = 1

    while i < len(stripped):
        char = stripped[i]

        if char == "\\" and i + 1 < len(stripped):
            cell.append(stripped[i : i + 2])
            i += 2
            continue

        if char == "`":
            end = i + 1
            while end < len(stripped) and stripped[end] == "`":
                end += 1
            run_length = end - i
            if code_ticks == 0:
                code_ticks = run_length
            elif code_ticks == run_length:
                code_ticks = 0
            cell.append(stripped[i:end])
            i = end
            continue

        if code_ticks == 0:
            if char == "[":
                bracket_depth += 1
            elif char == "]" and bracket_depth:
                bracket_depth -= 1
            elif char == "(" and bracket_depth == 0:
                parenthesis_depth += 1
            elif char == ")" and bracket_depth == 0 and parenthesis_depth:
                parenthesis_depth -= 1
            elif char == "|" and bracket_depth == 0 and parenthesis_depth == 0:
                cells.append("".join(cell).strip())
                cell = []
                i += 1
                if i == len(stripped):
                    return cells
                continue

        cell.append(char)
        i += 1

    if cell or not stripped.endswith("|"):
        cells.append("".join(cell).strip())
    return cells


def is_delimiter_row(cells: list[str] | None) -> bool:
    return bool(cells) and all(DELIMITER_CELL_RE.fullmatch(cell) for cell in cells)


def delimiter_width(cell: str) -> int:
    return max(3, 3 + int(cell.startswith(":")) + int(cell.endswith(":")))


def padded_delimiter(cell: str, width: int) -> str:
    left = cell.startswith(":")
    right = cell.endswith(":")
    if left and right:
        return ":" + "-" * (width - 2) + ":"
    if left:
        return ":" + "-" * (width - 1)
    if right:
        return "-" * (width - 1) + ":"
    return "-" * width


def format_tables(lines: list[str]) -> list[str]:
    result: list[str] = []
    i = 0
    while i < len(lines):
        header = split_table_row(lines[i])
        delimiter = split_table_row(lines[i + 1]) if i + 1 < len(lines) else None
        if (
            header is None
            or delimiter is None
            or len(header) != len(delimiter)
            or not is_delimiter_row(delimiter)
        ):
            result.append(lines[i])
            i += 1
            continue

        rows = [header, delimiter]
        end = i + 2
        while end < len(lines):
            row = split_table_row(lines[end])
            if row is None or len(row) != len(header):
                break
            rows.append(row)
            end += 1

        widths = []
        for column in range(len(header)):
            content_width = max(
                len(row[column]) for row_number, row in enumerate(rows) if row_number != 1
            )
            widths.append(max(content_width, delimiter_width(delimiter[column])))

        for row_number, row in enumerate(rows):
            if row_number == 1:
                cells = [
                    padded_delimiter(cell, widths[column])
                    for column, cell in enumerate(row)
                ]
            else:
                cells = [cell.ljust(widths[column]) for column, cell in enumerate(row)]
            result.append("| " + " | ".join(cells) + " |")

        i = end
    return result


def add_title_and_fix_badges(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    title: str | None = None
    fence: str | None = None
    for line in lines:
        opener = re.match(r"(`{3,}|~{3,})", line.lstrip())
        if fence is None and opener:
            fence = opener.group(1)[0]
        elif fence is not None and opener and opener.group(1)[0] == fence:
            fence = None
        elif fence is None:
            # Take the document's own H1 rather than imposing one, and never treat a heading
            # inside a fenced code block as the document title.
            if title is None and line.startswith("# "):
                title = line.rstrip()
                continue
            if line.strip() == STANDALONE_AWESOME_BADGE:
                continue
        if (
            line.strip().startswith("**[Reliability Map](#the-reliability-map)**")
            and "&nbsp;&middot;&nbsp;" in line
        ):
            continue
        if "![PRs Welcome]" in line:
            line = re.sub(r"\]\(#contributing\)\s*$", "](CONTRIBUTING.md)", line)
        if "![Topic:" in line:
            match = re.fullmatch(r"\[(!\[[^]]+\]\([^)]+\))\]\(#[^)]+\)", line.strip())
            if match:
                line = match.group(1)
        cleaned.append(line)

    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    if title is None:
        title = DEFAULT_TITLE
    elif STANDALONE_AWESOME_BADGE not in title:
        title = "%s %s" % (title, STANDALONE_AWESOME_BADGE)
    return [title, "", *cleaned]


def replace_contents(text: str) -> str:
    if CONTENTS_BLOCK_RE.search(text):
        return CONTENTS_BLOCK_RE.sub(CONTENTS, text, count=1)
    return text


def add_reliability_list_ignores(lines: list[str]) -> list[str]:
    result = list(lines)
    for summary_start in IGNORED_RELIABILITY_LISTS:
        summary_index = next(
            (index for index, line in enumerate(result) if line.startswith(summary_start)),
            None,
        )
        if summary_index is None:
            continue
        list_index = next(
            (
                index
                for index in range(summary_index + 1, len(result))
                if result[index].startswith("- ") or result[index] == "</details>"
            ),
            None,
        )
        if list_index is None or result[list_index] == "</details>":
            continue
        if list_index > 0 and result[list_index - 1] == "<!--lint ignore awesome-list-item-->":
            continue
        result.insert(list_index, "<!--lint ignore awesome-list-item-->")
    return result


def format_related_projects(text: str) -> str:
    start = text.find("## Related Projects\n")
    if start == -1:
        return text
    end = text.find("\n---", start)
    if end == -1:
        end = len(text)
    section = text[start:end]

    def linked_project(match: re.Match[str]) -> str:
        description = match.group(3)
        description = description[:1].upper() + description[1:]
        return f"- [{match.group(1)}]({match.group(2)}) - {description}"

    section = re.sub(
        r"(?m)^- \*\*\[([^]\n]+)\]\(([^)\n]+)\)\*\*:\s*(.+)$",
        linked_project,
        section,
    )
    section = re.sub(
        r"(?m)^(- \[[^]\n]+\]\([^)\n]+\) - )([a-z])",
        lambda match: match.group(1) + match.group(2).upper(),
        section,
    )
    section = re.sub(
        r"(?m)^- \*\*([^*\n]+)\*\*([^:\n]*):\s*(.+)$",
        r"\1\2: \3",
        section,
    )
    return text[:start] + section + text[end:]


def remove_artifact_link(cell: str, artifact: str) -> str:
    def replacement(match: re.Match[str]) -> str:
        return "" if match.group(3) == artifact else match.group(0)

    return DOUBLE_BRACKET_LINK_RE.sub(replacement, cell).strip()


def retarget_cross_listings(lines: list[str]) -> list[str]:
    section = ""
    result: list[str] = []
    for line in lines:
        heading = H2_RE.match(line)
        if heading:
            section = heading.group(1)

        cells = split_table_row(line)
        if not cells or len(cells) < 2 or is_delimiter_row(cells):
            result.append(line)
            continue

        first_cell = cells[0]
        matched = next(
            (
                (title_fragment, artifact)
                for title_fragment, artifact in CROSS_LISTED_ARTIFACTS
                if title_fragment in first_cell
            ),
            None,
        )
        if matched is None:
            result.append(line)
            continue

        _, artifact = matched
        if section == "Datasets and Benchmarks":
            first_link = PRIMARY_LINK_RE.search(first_cell)
            if first_link:
                cells[0] = (
                    first_cell[: first_link.start()]
                    + f"[{first_link.group(1)}]({artifact})"
                    + first_cell[first_link.end() :]
                )
            cells[-1] = remove_artifact_link(cells[-1], artifact)
        else:
            cells[-1] = remove_artifact_link(cells[-1], artifact)
        result.append("| " + " | ".join(cells) + " |")
    return result


def _protect_code(text: str) -> tuple[str, list[str]]:
    """Replace fenced blocks and inline code spans with placeholders.

    Escaping runs as a text substitution, so without this it also rewrites Markdown that a
    code span is quoting verbatim, turning documentation of a syntax into a corrupted example.
    """
    stash: list[str] = []

    def stash_match(match: re.Match) -> str:
        stash.append(match.group(0))
        return "\x00CODE%d\x00" % (len(stash) - 1)

    text = re.sub(r"(?ms)^(?:```|~~~).*?^(?:```|~~~)[^\n]*$", stash_match, text)
    return re.sub(r"`+[^`\n]*`+", stash_match, text), stash


def _restore_code(text: str, stash: list[str]) -> str:
    for index, original in enumerate(stash):
        text = text.replace("\x00CODE%d\x00" % index, original)
    return text


def escape_undefined_references(text: str) -> str:
    text, stash = _protect_code(text)
    text = re.sub(
        r"(?<!\\)\[\[([^]\n]+)\]\]\(",
        r"[\[\1\]](",
        text,
    )
    text = re.sub(
        r"(?m)^(\s*(?:-\s+)?\*\*)\[([^]\n]+)\]",
        r"\1\[\2\]",
        text,
    )
    return _restore_code(text, stash)


def transform(text: str) -> str:
    lines = add_title_and_fix_badges(text.split("\n"))
    text = "\n".join(lines)
    text = replace_contents(text)
    text = format_related_projects(text)
    lines = add_reliability_list_ignores(text.split("\n"))
    lines = retarget_cross_listings(lines)
    text = escape_undefined_references("\n".join(lines))
    return "\n".join(format_tables(text.split("\n")))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("readme", type=Path, help="path to the README to rewrite")
    args = parser.parse_args()

    raw = args.readme.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    fixed = transform(text)
    args.readme.write_bytes(fixed.replace("\n", newline).encode("utf-8"))


if __name__ == "__main__":
    main()
