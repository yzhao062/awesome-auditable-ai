# Contributing

Thanks for helping keep this list useful. New resources, corrections, and broken-link fixes are welcome.

## How to Suggest a Resource

Open an issue with the "Suggest a Resource" template, or send a pull request that edits `README.md` directly. For a pull request, add the entry to the most relevant section and use the formats below exactly. A suggestion must provide a title, primary link, target section, and one-sentence factual summary. Paper and dataset suggestions must also provide the venue and year. Tool suggestions must provide the license and activity period.

`The Auditable Agents Ecosystem` is maintainer-curated and is not open to resource suggestions. It presents one named ecosystem without ranking resources, and every component it names is also listed in the topical section it belongs to under the ordinary inclusion bar. Suggest such a component for its topical section instead, where it is judged on the same terms as everything else.

## Scope and Inclusion Bar

Auditability is the goal for this list: establishing what an agent did, what it relied on, why it acted, and whether the action was right. Reliability engineering is how a system gets there, which is why consistency, robustness, fault tolerance, recovery, monitoring, failure diagnosis, security review, and evaluation are all in scope alongside decision records and post-hoc review.

An entry must be directly useful for auditing an AI agent, or for the building, evaluating, monitoring, securing, or diagnosing work that makes an agent auditable. Generic LLM benchmarking with no agent angle, generic MLOps, and agent frameworks that are not themselves reliability or auditing assets are out of scope.

A tool entry must link to an inspectable public source repository. A closed-source managed service is listed only when it is used widely enough that omitting it would give a reader a false picture of the field, and it is then marked `[Managed]` and its closed-source status stated in the entry. LangSmith is the current example. A newly launched product is not that case, so a managed service without public source and without established adoption is out of scope. A paper entry must link to an arXiv record or a published venue. Self-deposited preprints with no confirmed venue and no evaluation are out of scope. Standards and frameworks must link to the official specification or issuing organization.

## Table Entries

Paper and dataset sections use this four-column table format:

```markdown
| Resource | Venue | Summary | Links |
|---|---|---|---|
| [Which Agent Causes Task Failures and When? On Automated Failure Attribution of LLM Multi-Agent Systems](https://arxiv.org/abs/2505.00212) | ICML 2025 | Defines automated failure attribution for LLM multi-agent systems and releases the Who&When dataset of annotated failure logs labeling the responsible agent and the decisive error step. | [[Code]](https://github.com/mingyin1/Agents_Failure_Attribution) |
```

The example is copied from the current README. Use one row per occurrence and one short, factual sentence in `Summary`.

Use these Venue forms:

- Main conference or journal: `<acronym or established journal short title> <year>`, such as `ICML 2025` or `Sci. China Inf. Sci. 2025`.
- Findings: `<host> Findings <year>`, such as `ACL Findings 2025` or `EMNLP Findings 2024`.
- Position paper: `<host> <year> Position Paper` or `<host> <year> Position Paper Track`, matching how the venue names it.
- Datasets and Benchmarks Track: `<host> <year> Datasets and Benchmarks Track`, optionally followed by a decision qualifier the venue itself assigns, such as `(Spotlight)`.
- Workshop: `<host> <year> Workshop (<short workshop name>)`. When the workshop is well known by its own name and its host is not established from the record, `<workshop name> <year> Workshop` is acceptable.
- Other archival venue: `<venue name> <year>`, for a venue that is none of the above, such as a summit with published proceedings.
- Preprint: `Preprint <first arXiv year>`, only when no venue is confirmed.

The venue field records what the venue is, not how strong it is. Do not upgrade a non-archival workshop to its host conference, and do not drop the workshop qualifier to make an entry look like a main-conference paper.

Use only these labels in the `Links` column:

- `[[Code]]` links to a runnable implementation.
- `[[Data]]` links to a dataset.
- `[[Model]]` links to a model artifact.
- `[[Paper]]` links to a paper abstract or landing page.
- `[[PDF]]` links only to a direct PDF URL.
- `[[Paper List]]` links to a survey bibliography repository.
- `[[Project]]` links to an official project or benchmark website that is neither the paper nor the code.

Separate multiple links with commas. Do not label a bibliography repository as code or use `[[PDF]]` for an abstract page.

## Tool, Standard, and Framework Entries

Tools use a standalone bold entry rather than a table row. Include the implementation language or category, inspectable source repository, factual description, license, and activity period. Follow this current README example:

```markdown
**[Python, TypeScript] Langfuse** ([langfuse/langfuse](https://github.com/langfuse/langfuse)): self-hostable platform for tracing LLM and agent calls, running evaluations, managing prompts, and tracking cost and latency, with OpenTelemetry, LangChain, and OpenAI SDK integrations. MIT-licensed core, 2023-present.
```

The license and activity note is required for every tool entry, including guardrail, decision-record, and scanner tools. Use a companion `[[Paper]]` link only for an abstract or landing page and `[[PDF]]` only for a direct PDF.

Standards and frameworks also use a standalone bold entry. Start with `[Standard]` or `[Framework]`, link to the official source, and end with the issuing body and current version, revision, or year. Follow this current README example:

```markdown
**[Standard] Agent2Agent (A2A) Protocol** ([a2a-protocol.org](https://a2a-protocol.org/latest/specification/)): task delegation between independent agents, where each server publishes an Agent Card declaring identity, capabilities, skills, endpoint, and authentication across API key, HTTP, OAuth 2.0, OpenID Connect, and mutual TLS. Linux Foundation, contributed by Google, v1.0.1.
```

## Cross-listing

Five papers intentionally appear once in a topical section and once in `Datasets and Benchmarks`. Keep this pattern when a paper makes both a topical contribution and a dataset or benchmark contribution. A cross-listed occurrence should point to a different canonical artifact when one exists. For example, the topical Aegis row is titled to the arXiv record and links `[[Code]]`, while its dataset occurrence is titled directly to the Hugging Face dataset. Do not cross-list only to increase visibility.

## Quality Bar

- Cite the primary source, not a third-party reposting.
- Verify that every submitted link works and matches its label.
- Use no promotional language. A maintainer may edit a summary for tone and length.
- Keep one primary occurrence per resource unless the cross-listing rule above applies.

## Automated Verification

Pull requests that change `README.md` or `tools/**` recompute the inventory in the GitHub Actions job summary and check every cited link, arXiv identifier, and arXiv title. This repository's own status badges and the GitHub pages behind them are skipped and listed in the report under `Repository Chrome Not Audited`, so that a rate limit on our own pages cannot fail an audit of everyone else's links, and so that the badge reporting the audit cannot decide its result. The link check retries transient responses twice. An arXiv disagreement, a non-retryable HTTP 4xx response, or a non-network error fails the pull request; exhausted timeouts, connection failures, 408, 425, 429, 5xx, and other HTTP statuses are reported as warnings and checked again by the strict weekly audit. The job summary works for pull requests from forks because it does not require permission to write to this repository.

Use Python 3.12 to run the same pull-request checks locally before opening a pull request. They require only the standard library:

```console
python tools/inventory.py README.md
python tools/check_links.py README.md --out link-audit-local.md --delay 0.10 --timeout 15 --retries 2 --retry-backoff 1 --failure-policy pull-request
```

## License

By contributing, you agree that your contributions are released under the [CC0 1.0 Universal](LICENSE) public domain dedication, the same terms as the rest of this repository.
