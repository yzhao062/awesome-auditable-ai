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

Titles agree only when they are identical after normalization. A high character-similarity
score is not treated as agreement, because that is exactly what a link to the wrong paper in a
series looks like: "Part I" against "Part II" scores 0.995. A difference confined to a number,
a roman numeral, or a word such as "Part" is reported as a disagreement whatever the score.

The command exits non-zero when a title or identifier disagrees. Under the default ``strict``
failure policy it also fails for every unresolved destination whose exact (URL, status) pair is
not recorded in ``KNOWN_BOT_WALLS`` below, and for any arXiv page that returned a body but
yielded no usable metadata, since that means the check could not run rather than that it
passed. The ``pull-request`` policy fails for non-retryable 4xx responses and for hostnames that
do not resolve, while reporting genuinely transient network failures as warnings.

A resolved destination is one answering 200 or 206; 206 is a success status, not a failure.

Usage:
    python tools/check_links.py [README.md] [-o LINK-AUDIT.md] [--delay 0.25]
                                [--timeout 30] [--retries 0] [--retry-backoff 1]
                                [--failure-policy strict|pull-request]

Requires the standard library only. Network access is required.
"""

import argparse
import datetime
import difflib
import html
import re
import socket
import sys
import time
from html.parser import HTMLParser
import urllib.error
import urllib.request
from collections import Counter

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Destinations known to refuse automated requests while being reachable in a browser. Each
# entry is an explicit, inspectable exception rather than a blanket tolerance for non-200.
# Each entry excuses ONE specific status for ONE destination. The status is part of the key so
# that a genuine outage at an excused URL (a DNS failure, a timeout, a 404) is still a failure
# rather than being masked by the exemption.
KNOWN_BOT_WALLS = {
    ("https://www.iso.org/standard/42001", 403):
        "ISO returns 403 to non-browser clients; verified by hand in a browser.",
    ("https://eur-lex.europa.eu/eli/reg/2026/1744/oj", 202):
        "EUR-Lex answers non-browser clients with an empty 202 from its JavaScript gateway; the "
        "cited act (Digital Omnibus on AI, in force 27 July 2026) was confirmed against the "
        "European Commission announcement and independent legal summaries.",
    ("https://scholar.google.com/citations?user=zoGDYsoAAAAJ&hl=en", 403):
        "Google Scholar serves 403 to datacenter clients, so this destination resolves from a "
        "workstation and fails from a GitHub-hosted runner; the profile was verified by hand in "
        "a browser.",
}

# This audit exists to check the resources the list cites. A few destinations in the README
# are not cited resources: they are the repository's own furniture, the status badges and the
# GitHub pages behind them. Auditing those is a category error, and it cost twice. GitHub
# answers 429 to its own dynamic pages when the caller is a shared CI address, which failed an
# audit of 253 other people's links on one rate limit. Worse, a badge that links to the audit
# can then decide the audit's own result, so the signal reporting link health becomes a reason
# for it to fail. Chrome is named in the report instead of fetched.
#
# The match is deliberately narrow. It covers this repository's UI sections only, so other
# repositories owned by the same person stay in the audit like any other cited resource, and so
# do this repository's own content paths.
SELF_REPO = "yzhao062/awesome-auditable-ai"
SELF_CHROME_SECTIONS = ("actions", "commits", "releases", "graphs", "pulse", "network")


def is_self_chrome(url):
    """True when a destination is this repository's presentation rather than a cited resource."""
    prefix = "https://github.com/%s/" % SELF_REPO
    if not url.startswith(prefix):
        return False
    section = url[len(prefix):].split("/", 1)[0]
    section = section.split("?", 1)[0].split("#", 1)[0]
    return section in SELF_CHROME_SECTIONS

# Modern identifiers (2612.34567) and legacy category identifiers (hep-th/9901001) are both
# real arXiv references, so both must enter verification rather than being skipped silently.
ARXIV_ABS_RE = re.compile(r"arxiv\.org/abs/(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})")

# Tokens that carry the difference between two genuinely different papers whose titles are
# otherwise nearly identical, such as "Part I" against "Part II". A character-similarity score
# cannot separate those, so a difference confined to one of these tokens is a disagreement no
# matter how high the score.
DISCRIMINATIVE_WORDS = {
    "part", "parts", "volume", "vol", "extended", "revisited", "supplement",
    "supplementary", "appendix", "errata", "corrigendum", "addendum", "erratum",
}
ROMAN_NUMERALS = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}

# Link labels that are navigation, not paper titles. Compared after bracket/escape stripping.
RESERVED_LABELS = {
    "code", "data", "model", "paper", "pdf", "paper list", "project", "arxiv",
    "docs", "site", "spec", "report", "blog", "video", "slides",
}

MATCH_STRONG = 0.92   # at or above: titles agree
MATCH_WEAK = 0.80     # between weak and strong: agree loosely, listed for a human to confirm

RETRYABLE_HTTP_STATUSES = {408, 425, 429}
TRANSIENT_ERROR_NAMES = {
    "ConnectionAbortedError", "ConnectionRefusedError", "ConnectionResetError",
    "IncompleteRead", "OSError", "RemoteDisconnected", "SSLError", "TimeoutError",
    "URLError", "gaierror",
}


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


GREEK_NAMES = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon", "ζ": "zeta",
    "η": "eta", "θ": "theta", "ι": "iota", "κ": "kappa", "λ": "lambda", "μ": "mu",
    "ν": "nu", "ξ": "xi", "π": "pi", "ρ": "rho", "σ": "sigma", "τ": "tau",
    "υ": "upsilon", "φ": "phi", "χ": "chi", "ψ": "psi", "ω": "omega",
    "Α": "alpha", "Β": "beta", "Γ": "gamma", "Δ": "delta", "Θ": "theta", "Λ": "lambda",
    "Ξ": "xi", "Π": "pi", "Σ": "sigma", "Φ": "phi", "Ψ": "psi", "Ω": "omega",
}
SUPERSUB_DIGITS = {
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7",
    "⁸": "8", "⁹": "9", "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5",
    "₆": "6", "₇": "7", "₈": "8", "₉": "9",
}


def normalize_title(value):
    """Fold a title to a comparable form: unescaped, de-punctuated, lowercase, collapsed.

    arXiv reports titles in LaTeX while this list writes them in Unicode, so ``$\\tau^2$-Bench``
    and ``τ²-Bench`` must fold to the same string. Both notations are mapped to plain ASCII
    before comparison, otherwise the superscript digit looks like a distinguishing number and
    a formatting difference is reported as a wrong paper.
    """
    value = html.unescape(value or "")
    value = value.replace("\\[", "[").replace("\\]", "]")
    for symbol, name in GREEK_NAMES.items():
        value = value.replace(symbol, name)
    for symbol, digit in SUPERSUB_DIGITS.items():
        value = value.replace(symbol, digit)
    # LaTeX math: drop the delimiters and structural characters, keep the command name so
    # \tau becomes tau and lines up with the Unicode form mapped above.
    value = re.sub(r"\\(?:left|right|mathrm|mathbf|mathcal|text|texttt|emph)\b", " ", value)
    value = re.sub(r"\\([A-Za-z]+)", r"\1", value)
    value = value.replace("$", "").replace("^", "").replace("_", "")
    value = value.replace("{", "").replace("}", "")
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

def is_retryable_status(status):
    """Return whether a response is likely to succeed when repeated shortly afterward."""
    if isinstance(status, int):
        return status in RETRYABLE_HTTP_STATUSES or 500 <= status < 600
    return status in TRANSIENT_ERROR_NAMES


def is_pull_request_failure(status):
    """Return whether an unresolved status should block a pull request."""
    if isinstance(status, int):
        return 400 <= status < 500 and not is_retryable_status(status)
    return not is_retryable_status(status)


def _fetch_once(url, timeout):
    """Return ``(status, body)`` for one request.

    A hostname that does not resolve is reported as ``DNSError`` rather than the generic
    ``URLError``, because a typo in a hostname is the most common way a contributor breaks a
    link and it must not be excused as a transient network condition.
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # Generous cap: a truncated body looks identical to a page with no metadata, which
            # would turn a real disagreement into a silent "unverified".
            raw = resp.read(2_000_000)
            return resp.status, raw.decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, "reason", None), socket.gaierror):
            return "DNSError", ""
        reason = getattr(exc, "reason", None)
        return type(reason).__name__ if isinstance(reason, Exception) else "URLError", ""
    except Exception as exc:
        return type(exc).__name__, ""


class _MetaReader(HTMLParser):
    """Collect ``citation_*`` meta tags without caring about attribute order or quote style."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "meta":
            return
        found = {key.lower(): (value or "") for key, value in attrs}
        name = (found.get("name") or found.get("property") or "").lower()
        if name.startswith("citation_"):
            self.meta.setdefault(name, found.get("content", ""))


def read_citation_meta(body):
    """Return the ``citation_*`` meta tags in ``body`` as a dict."""
    reader = _MetaReader()
    try:
        reader.feed(body)
    except Exception:
        pass
    return reader.meta


def compare_titles(ours, theirs):
    """Return ``(verdict, ratio)`` for two titles, where verdict is match, near, or MISMATCH.

    Only an exact match after normalization counts as agreement. Anything else is surfaced,
    because a high character-similarity score is exactly what a wrong-paper link looks like.
    """
    left, right = normalize_title(ours), normalize_title(theirs)
    ratio = difflib.SequenceMatcher(None, left, right).ratio()
    if left == right:
        return "match", ratio
    difference = set(left.split()) ^ set(right.split())
    decisive = {
        token for token in difference
        if token.isdigit() or token in ROMAN_NUMERALS or token in DISCRIMINATIVE_WORDS
    }
    if decisive:
        return "MISMATCH", ratio
    return ("near", ratio) if ratio >= MATCH_WEAK else ("MISMATCH", ratio)


def fetch(url, timeout=30, retries=0, retry_backoff=1.0):
    """Fetch a URL, retrying transient results, and return ``(status, body)``."""
    for attempt in range(retries + 1):
        status, body = _fetch_once(url, timeout)
        if attempt == retries or not is_retryable_status(status):
            return status, body
        wait = retry_backoff * (2 ** attempt)
        print("retrying %s after status %s in %.1fs" % (url, status, wait), file=sys.stderr)
        time.sleep(wait)


# --------------------------------------------------------------------------- report

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("readme", nargs="?", default="README.md")
    ap.add_argument("-o", "--out", default="LINK-AUDIT.md")
    ap.add_argument("--delay", type=float, default=0.25)
    ap.add_argument("--timeout", type=float, default=30)
    ap.add_argument("--retries", type=int, default=0)
    ap.add_argument("--retry-backoff", type=float, default=1.0)
    ap.add_argument("--failure-policy", choices=("strict", "pull-request"), default="strict")
    args = ap.parse_args()
    if args.delay < 0:
        ap.error("--delay must be non-negative")
    if args.timeout <= 0:
        ap.error("--timeout must be positive")
    if args.retries < 0:
        ap.error("--retries must be non-negative")
    if args.retry_backoff < 0:
        ap.error("--retry-backoff must be non-negative")

    links = extract_links(args.readme)
    labels_by_url = {}
    for url, label, _kind in links:
        labels_by_url.setdefault(url, [])
        if label is not None:
            labels_by_url[url].append(label)
    skipped_chrome = sorted(url for url in labels_by_url if is_self_chrome(url))
    for url in skipped_chrome:
        del labels_by_url[url]
    urls = sorted(labels_by_url)

    rows = []                 # (url, status, id_result, title_result, detail)
    id_checked = id_matched = id_absent = 0
    title_checked = title_matched = title_weak = 0
    title_mismatches, id_mismatches, title_unverified = [], [], []

    for index, url in enumerate(urls, 1):
        status, body = fetch(
            url,
            timeout=args.timeout,
            retries=args.retries,
            retry_backoff=args.retry_backoff,
        )
        id_result = title_result = "n/a"
        detail = ""
        arxiv = ARXIV_ABS_RE.search(url)

        if arxiv:
            if not body:
                id_result = title_result = "unverified"
                detail = "page could not be read (status %s)" % status
                title_unverified.append((url, detail))
            else:
                meta = read_citation_meta(body)
                id_checked += 1
                meta_id = meta.get("citation_arxiv_id")
                if meta_id and meta_id.split("v")[0] == arxiv.group(1):
                    id_matched += 1
                    id_result = "match"
                elif meta_id:
                    id_result = "MISMATCH"
                    detail = "page reports identifier %s" % meta_id
                    id_mismatches.append((url, detail))
                else:
                    id_absent += 1
                    id_result = "unverified"
                    detail = "no citation_arxiv_id meta tag"
                    title_unverified.append((url, "no citation_arxiv_id meta tag"))

                # Every title label pointing at this destination is checked, not just the
                # first: a correct first occurrence must not hide a wrong later one.
                title_labels = [l for l in labels_by_url[url] if is_title_label(l)]
                page_title = meta.get("citation_title")
                if title_labels and page_title:
                    shown = html.unescape(page_title)
                    verdicts = [(l, ) + compare_titles(l, page_title) for l in title_labels]
                    title_checked += len(verdicts)
                    worst = min(verdicts, key=lambda v: (v[1] == "MISMATCH" and 0
                                                         or v[1] == "near" and 1 or 2, v[2]))
                    for label, verdict, ratio in verdicts:
                        if verdict == "MISMATCH":
                            title_mismatches.append((url, label, shown, ratio))
                        elif verdict == "near":
                            title_weak += 1
                        else:
                            title_matched += 1
                    title_result = ("match" if worst[1] == "match"
                                    else "%s (%.2f)" % (worst[1], worst[2]))
                    if worst[1] != "match":
                        detail = (detail + "; " if detail else "") + 'page title "%s"' % shown
                elif title_labels:
                    title_result = "unverified"
                    title_unverified.append((url, "no citation_title meta tag"))
                else:
                    title_result = "no title label"

        rows.append((url, status, id_result, title_result, detail))
        print("[%d/%d] %s %s %s" % (index, len(urls), status, id_result, url), file=sys.stderr)
        if index < len(urls):
            time.sleep(args.delay)

    resolved = [r for r in rows if r[1] in (200, 206)]
    unresolved = [r for r in rows if r[1] not in (200, 206)]
    unexpected = [r for r in unresolved if (r[0], r[1]) not in KNOWN_BOT_WALLS]
    pr_blocking = [r for r in unexpected if is_pull_request_failure(r[1])]
    pr_warnings = [r for r in unexpected if not is_pull_request_failure(r[1])]
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
        "| Failure policy | `%s` |" % args.failure_policy,
        "| Distinct link destinations | %d |" % len(rows),
        "| Resolved (200 or 206) | %d |" % len(resolved),
        "| Did not resolve | %d |" % len(unresolved),
        "| Unresolved and not a known bot wall | %d |" % len(unexpected),
        "| PR-blocking unresolved (non-retryable 4xx or non-network error) | %d |"
        % len(pr_blocking),
        "| PR-warning unresolved (transient or other status) | %d |" % len(pr_warnings),
        "| arXiv titles compared with `citation_title` | %d |" % title_checked,
        "| arXiv titles agreeing | %d |" % title_matched,
        "| arXiv titles agreeing loosely (listed below) | %d |" % title_weak,
        "| arXiv title disagreements | %d |" % len(title_mismatches),
        "| arXiv identifiers compared with `citation_arxiv_id` | %d |" % id_checked,
        "| arXiv identifiers agreeing | %d |" % id_matched,
        "| arXiv identifiers with no meta tag | %d |" % id_absent,
        "| arXiv identifier disagreements | %d |" % len(id_mismatches),
        "| arXiv pages where a check could not run (unverified) | %d |" % len({u for u, _ in title_unverified}),
        "| Repository chrome skipped, listed below | %d |" % len(skipped_chrome),
        "",
        "## What This Checks, and What It Does Not",
        "",
        "Checked: that every destination responds; that each arXiv page reports the identifier in",
        "its own URL; and that each arXiv entry's title in this list agrees with the",
        "`citation_title` the arXiv page reports. The third check is the one that can catch an",
        "entry pointing at a real but different paper.",
        "",
        "Not checked: whether a summary sentence fairly describes the linked work, whether a venue",
        "field is correct, or whether a non-arXiv destination contains the claimed content. This",
        "repository's own badges and the GitHub pages behind them are also not checked, and each",
        "one is named under Repository Chrome Not Audited rather than counted as passing.",
        "",
        "Titles count as agreeing only when they are identical after case folding and punctuation",
        "removal, so a near-identical title is never silently accepted. A remaining difference of",
        "%.2f similarity or better is listed under Titles Agreeing Loosely for a human to confirm."
        % MATCH_WEAK,
        "A difference confined to a number, a roman numeral, or a word such as Part is treated as a",
        "disagreement at any similarity score, because that is the shape of a link to the wrong",
        "paper in a series.",
        "",
        "The strict failure policy rejects every unexpected unresolved destination. The pull-request",
        "policy rejects non-retryable 4xx responses and non-network exceptions, but treats exhausted",
        "timeouts, connection errors, 408, 425, 429, 5xx, and other HTTP statuses as warnings.",
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
            "recorded reason and were confirmed by hand. The strict policy fails every other row;",
            "the pull-request policy applies the narrower rule described above.",
            "",
            "| Status | URL | Note |",
            "|---|---|---|",
        ]
        lines += [
            "| %s | %s | %s |" % (s, u, KNOWN_BOT_WALLS.get((u, s), "not a recorded exception"))
            for u, s, _, _, _ in unresolved
        ] + [""]
    else:
        lines += ["None.", ""]

    lines += ["## Repository Chrome Not Audited", ""]
    if skipped_chrome:
        lines += [
            "These destinations are this repository's own badges and the GitHub pages behind them,",
            "rather than resources this list cites. They are skipped for two reasons. GitHub rate-",
            "limits its own dynamic pages for shared CI addresses, and one such limit should not",
            "fail an audit of everyone else's links. A badge that points at this audit would also",
            "be able to decide the audit's result, which is a loop worth refusing. Every other",
            "github.com destination is audited, including this owner's other repositories.",
            "",
            "| URL |",
            "|---|",
        ]
        lines += ["| %s |" % u for u in skipped_chrome] + [""]
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

    # An arXiv page that returned 200 but yielded no usable metadata is not a pass: it means the
    # check could not run. Under the strict policy that counts as a failure so a markup change
    # cannot quietly turn the whole audit green. Counted per destination, since one page can
    # be missing both the identifier and the title tag.
    unverified_urls = {u for u, _ in title_unverified}
    reachability_failures = unexpected if args.failure_policy == "strict" else pr_blocking
    unverified_failures = len(unverified_urls) if args.failure_policy == "strict" else 0
    failures = (len(title_mismatches) + len(id_mismatches)
                + len(reachability_failures) + unverified_failures)
    warnings = len(pr_warnings) if args.failure_policy == "pull-request" else 0
    print("wrote %s: %d destinations, %d resolved, %d title checks, %d unverified, "
          "%d failures, %d warnings"
          % (args.out, len(rows), len(resolved), title_checked,
             len(unverified_urls), failures, warnings))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
