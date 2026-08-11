"""Audit every link in README.md and write a reproducible report to LINK-AUDIT.md.

This list's stated differentiator is that its citations are checked, and that claim is only
worth making if a reader can inspect it. This script produces the artifact behind it.

Three checks run over every link:

1. **Reachability.** Each distinct HTTP(S) destination is requested and the final status code
   after redirects is recorded.
2. **Identifier agreement.** For an ``arxiv.org/abs/<id>`` destination, the page's
   ``citation_arxiv_id`` meta tag is compared with the identifier in the URL. This is a weak
   check on its own, because the two almost always agree, so it is reported separately from
   the check below rather than being folded into one "verified" number.
3. **Title agreement.** For an ``arxiv.org/abs/<id>`` destination whose Markdown link label is
   the paper title, the label is compared with the page's ``citation_title`` meta tag. This is
   the check that catches the failure mode that matters: an entry whose title describes one
   paper while its link points at a different, perfectly live paper.

Links are extracted with a Markdown scanner that keeps each destination's label, handles
balanced parentheses inside destinations, and skips fenced code blocks and HTML comments.
HTML ``src``/``href`` attributes and autolinks are included; a URL that appears only inside a
fenced code block (the BibTeX snippet, for example) is not a link and is not counted.

The command exits non-zero when a title or identifier disagrees, or when a destination fails
to resolve and is not in ``KNOWN_BOT_WALLS`` below, so it is usable as a CI gate.

Usage:
    python tools/check_links.py [README.md] [-o LINK-AUDIT.md] [--delay 0.25]

Requires the standard library only. Network access is required.
"""

import argparse
import datetime
import difflib
import html
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Destinations known to refuse automated requests while being reachable in a browser. Each
# entry is an explicit, inspectable exception rather than a blanket tolerance for non-200.
KNOWN_BOT_WALLS = {
    "https://www.iso.org/standard/42001":
        "ISO returns 403 to non-browser clients; verified by hand in a browser.",
    "https://eur-lex.europa.eu/eli/reg/2026/1744/oj":
        "EUR-Lex answers non-browser clients with an empty 202 from its JavaScript gateway; the "
        "cited act (Digital Omnibus on AI, in force 27 July 2026) was confirmed against the "
        "European Commission announcement and independent legal summaries.",
}

ARXIV_ABS_RE = re.compile(r"arxiv\.org/abs/(\d{4}\.\d{4,5})")
META_ID_RE = re.compile(r'name="citation_arxiv_id"\s+content="([^"]*)"')
META_TITLE_RE = re.compile(r'name="citation_title"\s+content="([^"]*)"')

# Link labels that are navigation, not paper titles. Compared after bracket/escape stripping.
RESERVED_LABELS = {
    "code", "data", "model", "paper", "pdf", "paper list", "project", "arxiv",
    "docs", "site", "spec", "report", "blog", "video", "slides",
}

MATCH_STRONG = 0.92   # at or above: titles agree
MATCH_WEAK = 0.80     # between weak and strong: agree loosely, listed for a human to confirm


# --------------------------------------------------------------------------- extraction

def _blank_code_and_comments(text):
    """Return text with fenced code blocks and HTML comments blanked out, offsets preserved."""
    lines = text.split("\n")
    out = []
    fence = None
    for line in lines:
        stripped = line.lstrip()
        opener = re.match(r"(`{3,}|~{3,})", stripped)
        if fence is None:
            if opener:
                fence = opener.group(1)[0]
                out.append("")
                continue
            out.append(line)
        else:
            if opener and opener.group(1)[0] == fence:
                fence = None
            out.append("")
    text = "\n".join(out)
    return re.sub(r"<!--.*?-->", lambda m: " " * len(m.group(0)), text, flags=re.S)


def _scan_balanced(text, start, open_ch, close_ch, stop_at_newline):
    """Scan a balanced ``open_ch``..``close_ch`` run beginning at ``start``.

    Returns ``(inner_text, index_after_close)`` or ``(None, start + 1)``.
    Backslash escapes are honoured so ``\\[`` and ``\\)`` do not affect nesting.
    """
    depth = 0
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "\n" and stop_at_newline:
            return None, start + 1
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    return None, start + 1


def _clean_dest(raw):
    """Strip an optional Markdown link title and angle brackets from a destination."""
    if raw is None:
        return None
    raw = raw.strip()
    if raw.startswith("<") and ">" in raw:
        return raw[1:raw.index(">")].strip()
    # A destination may be followed by a quoted title: (url "Title")
    for quote in ('"', "'"):
        idx = raw.find(" " + quote)
        if idx != -1:
            raw = raw[:idx]
            break
    return raw.split()[0].strip() if raw.split() else None


def _scan_markdown(scan, found):
    """Append every ``(url, label, kind)`` in ``scan`` to ``found``, recursing into labels.

    Recursion matters for the badge idiom ``[![alt](image)](href)``, where the image
    destination lives inside the outer link's label.
    """
    i = 0
    n = len(scan)
    while i < n:
        ch = scan[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "[":
            label, after = _scan_balanced(scan, i, "[", "]", stop_at_newline=True)
            if label is not None:
                # Recurse first: a badge's image sits inside the label even when the outer
                # destination is a relative path such as CONTRIBUTING.md.
                if "](" in label:
                    _scan_markdown(label, found)
                if after < n and scan[after] == "(":
                    dest, end = _scan_balanced(scan, after, "(", ")", stop_at_newline=True)
                    if dest is not None:
                        url = _clean_dest(dest)
                        if url and url.startswith(("http://", "https://")):
                            kind = "image" if i > 0 and scan[i - 1] == "!" else "link"
                            found.append((url, label, kind))
                        i = end
                        continue
            i = after
            continue
        i += 1


def extract_links(readme):
    """Return a list of ``(url, label_or_None, kind)`` for every link target in the file."""
    with open(readme, encoding="utf-8") as fh:
        text = fh.read()
    scan = _blank_code_and_comments(text)
    found = []
    _scan_markdown(scan, found)

    for match in re.finditer(r'(?:src|href)\s*=\s*"([^"]+)"', scan):
        if match.group(1).startswith(("http://", "https://")):
            found.append((match.group(1), None, "html"))
    for match in re.finditer(r"<(https?://[^>\s]+)>", scan):
        found.append((match.group(1), None, "autolink"))

    return found


def normalize_title(value):
    """Fold a title to a comparable form: unescaped, de-punctuated, lowercase, collapsed."""
    value = html.unescape(value or "")
    value = value.replace("\\[", "[").replace("\\]", "]")
    value = value.replace("&", " and ")
    value = re.sub(r"[^0-9A-Za-z]+", " ", value)
    return " ".join(value.lower().split())


def is_title_label(label):
    """True when a link label is a paper title rather than a navigation label."""
    if not label:
        return False
    plain = label.replace("\\[", "").replace("\\]", "").replace("[", "").replace("]", "").strip()
    if plain.lower() in RESERVED_LABELS:
        return False
    if re.fullmatch(r"arxiv:\s*\d{4}\.\d{4,5}", plain.lower()):
        return False
    return len(plain) >= 12


# --------------------------------------------------------------------------- network

def fetch(url, timeout=30):
    """Return ``(status, body)``. Status is an int, or a short exception name on failure."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(300_000)
            return resp.status, raw.decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:
        return type(exc).__name__, ""


# --------------------------------------------------------------------------- report

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("readme", nargs="?", default="README.md")
    ap.add_argument("-o", "--out", default="LINK-AUDIT.md")
    ap.add_argument("--delay", type=float, default=0.25)
    args = ap.parse_args()

    links = extract_links(args.readme)
    labels_by_url = {}
    for url, label, _kind in links:
        labels_by_url.setdefault(url, [])
        if label is not None:
            labels_by_url[url].append(label)
    urls = sorted(labels_by_url)

    rows = []                 # (url, status, id_result, title_result, detail)
    id_checked = id_matched = id_absent = 0
    title_checked = title_matched = title_weak = 0
    title_mismatches, id_mismatches, title_unverified = [], [], []

    for index, url in enumerate(urls, 1):
        status, body = fetch(url)
        id_result = title_result = "n/a"
        detail = ""
        arxiv = ARXIV_ABS_RE.search(url)

        if arxiv:
            if not body:
                id_result = title_result = "unverified"
                detail = "page could not be read (status %s)" % status
                title_unverified.append((url, detail))
            else:
                id_checked += 1
                meta_id = META_ID_RE.search(body)
                if meta_id and meta_id.group(1).split("v")[0] == arxiv.group(1):
                    id_matched += 1
                    id_result = "match"
                elif meta_id:
                    id_result = "MISMATCH"
                    detail = "page reports identifier %s" % meta_id.group(1)
                    id_mismatches.append((url, detail))
                else:
                    id_absent += 1
                    id_result = "unverified"
                    detail = "no citation_arxiv_id meta tag"

                title_label = next((l for l in labels_by_url[url] if is_title_label(l)), None)
                meta_title = META_TITLE_RE.search(body)
                if title_label and meta_title:
                    title_checked += 1
                    ours = normalize_title(title_label)
                    theirs = normalize_title(meta_title.group(1))
                    ratio = difflib.SequenceMatcher(None, ours, theirs).ratio()
                    if ratio >= MATCH_STRONG:
                        title_matched += 1
                        title_result = "match"
                    elif ratio >= MATCH_WEAK:
                        title_weak += 1
                        title_result = "near (%.2f)" % ratio
                        detail = (detail + "; " if detail else "") + \
                            'page title "%s"' % html.unescape(meta_title.group(1))
                    else:
                        title_result = "MISMATCH (%.2f)" % ratio
                        detail = (detail + "; " if detail else "") + \
                            'page title "%s"' % html.unescape(meta_title.group(1))
                        title_mismatches.append((url, title_label, html.unescape(meta_title.group(1)), ratio))
                elif title_label:
                    title_result = "unverified"
                    title_unverified.append((url, "no citation_title meta tag"))
                else:
                    title_result = "no title label"

        rows.append((url, status, id_result, title_result, detail))
        print("[%d/%d] %s %s %s" % (index, len(urls), status, id_result, url), file=sys.stderr)
        time.sleep(args.delay)

    resolved = [r for r in rows if r[1] in (200, 206)]
    unresolved = [r for r in rows if r[1] not in (200, 206)]
    unexpected = [r for r in unresolved if r[0] not in KNOWN_BOT_WALLS]
    today = datetime.date.today().isoformat()

    lines = [
        "# Link Audit",
        "",
        "Generated by `tools/check_links.py`. Re-run it to reproduce this file.",
        "",
        "## Summary",
        "",
        "| Field | Value |",
        "|---|---|",
        "| Audit date | %s |" % today,
        "| Distinct link destinations | %d |" % len(rows),
        "| Resolved (200 or 206) | %d |" % len(resolved),
        "| Did not resolve | %d |" % len(unresolved),
        "| Unresolved and not a known bot wall | %d |" % len(unexpected),
        "| arXiv titles compared with `citation_title` | %d |" % title_checked,
        "| arXiv titles agreeing | %d |" % title_matched,
        "| arXiv titles agreeing loosely (listed below) | %d |" % title_weak,
        "| arXiv title disagreements | %d |" % len(title_mismatches),
        "| arXiv identifiers compared with `citation_arxiv_id` | %d |" % id_checked,
        "| arXiv identifiers agreeing | %d |" % id_matched,
        "| arXiv identifiers with no meta tag | %d |" % id_absent,
        "| arXiv identifier disagreements | %d |" % len(id_mismatches),
        "",
        "## What This Checks, and What It Does Not",
        "",
        "Checked: that every destination responds; that each arXiv page reports the identifier in",
        "its own URL; and that each arXiv entry's title in this list agrees with the",
        "`citation_title` the arXiv page reports. The third check is the one that can catch an",
        "entry pointing at a real but different paper.",
        "",
        "Not checked: whether a summary sentence fairly describes the linked work, whether a venue",
        "field is correct, or whether a non-arXiv destination contains the claimed content. Titles",
        "are compared after case folding and punctuation removal, so a formatting difference does",
        "not register as a disagreement; a row scoring between %.2f and %.2f is listed below for a"
        % (MATCH_WEAK, MATCH_STRONG),
        "human to confirm rather than being counted as agreement.",
        "",
    ]

    lines += ["## Title Disagreements", ""]
    if title_mismatches:
        lines += ["| URL | Title in this list | Title on the page | Score |", "|---|---|---|---:|"]
        lines += ["| %s | %s | %s | %.2f |" % row for row in title_mismatches] + [""]
    else:
        lines += ["None. Every arXiv entry with a title label agrees with the title its page reports.", ""]

    lines += ["## Titles Agreeing Loosely", ""]
    weak_rows = [r for r in rows if r[3].startswith("near")]
    if weak_rows:
        lines += ["| URL | Score | Detail |", "|---|---|---|"]
        lines += ["| %s | %s | %s |" % (u, t.replace("near ", ""), d) for u, _, _, t, d in weak_rows] + [""]
    else:
        lines += ["None.", ""]

    lines += ["## Identifier Disagreements", ""]
    if id_mismatches:
        lines += ["| URL | Detail |", "|---|---|"]
        lines += ["| %s | %s |" % row for row in id_mismatches] + [""]
    else:
        lines += ["None. Every arXiv page reports the identifier in its own URL.", ""]

    lines += ["## Destinations That Did Not Return 200", ""]
    if unresolved:
        lines += [
            "A non-200 result is not automatically a dead link: some publishers refuse automated",
            "requests. Destinations listed in `KNOWN_BOT_WALLS` in `tools/check_links.py` carry a",
            "recorded reason and were confirmed by hand. Any other row here fails the command.",
            "",
            "| Status | URL | Note |",
            "|---|---|---|",
        ]
        lines += [
            "| %s | %s | %s |" % (s, u, KNOWN_BOT_WALLS.get(u, "not a recorded exception"))
            for u, s, _, _, _ in unresolved
        ] + [""]
    else:
        lines += ["None.", ""]

    counts = Counter(str(r[1]) for r in rows)
    lines += ["## Status Code Distribution", "", "| Status | Count |", "|---|---:|"]
    lines += ["| %s | %d |" % (k, v) for k, v in sorted(counts.items())] + [""]

    lines += [
        "## Every Destination",
        "",
        "| # | Status | Identifier | Title | URL |",
        "|---:|---|---|---|---|",
    ]
    lines += [
        "| %d | %s | %s | %s | %s |" % (n, s, i, t, u)
        for n, (u, s, i, t, _) in enumerate(rows, 1)
    ] + [""]

    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))

    failures = len(title_mismatches) + len(id_mismatches) + len(unexpected)
    print("wrote %s: %d destinations, %d resolved, %d title checks, %d failures"
          % (args.out, len(rows), len(resolved), title_checked, failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
