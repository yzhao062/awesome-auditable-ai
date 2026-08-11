# Contributing

Thanks for helping keep this list useful. New resources, corrections, and broken-link fixes are welcome.

## How to Suggest a Resource

Open an issue with the "Suggest a Resource" template, or send a pull request that edits `README.md` directly. For a pull request, add the entry to the most relevant section and use the formats below exactly. A suggestion must provide a title, primary link, target section, and one-sentence factual summary. Paper and dataset suggestions must also provide the venue and year. Tool suggestions must provide the license and activity period.

`Related Projects` is maintainer-curated and is not open to resource suggestions. Use an issue for a resource that belongs in one of the contributor-facing sections instead.

## Scope and Inclusion Bar

Reliability is the umbrella for this list. Auditing is one strand within reliability, alongside consistency, robustness, fault tolerance, recovery, monitoring, failure diagnosis, security review, and evaluation.

An entry must be directly useful for building, evaluating, monitoring, securing, diagnosing, or auditing reliable AI agents. Generic LLM benchmarking with no agent angle, generic MLOps, and agent frameworks that are not themselves reliability assets are out of scope.

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
- ACL Findings: `ACL Findings <year>`.
- Position paper: `<host> <year> Position Paper`.
- Datasets and Benchmarks Track: `<host> <year> Datasets and Benchmarks Track`.
- Workshop: `<host> <year> Workshop (<short workshop name>)`.
- Preprint: `Preprint <first arXiv year>`, only when no venue is confirmed.

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

## License

By contributing, you agree that your contributions are released under the [CC0 1.0 Universal](LICENSE) public domain dedication, the same terms as the rest of this repository.
