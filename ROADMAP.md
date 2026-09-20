# Roadmap

This document summarizes the milestones DocSifter has delivered and where
the project is heading next. There are no fixed dates; priorities may shift
based on community feedback — feel free to open an issue to discuss a use
case that is not covered yet.

## Shipped

### v0.1.0 — Initial public release

- Layered review pipeline: conservative rule preview, local small-model
  correction (`shibing624/chinese-text-correction-1.5b` by default), and an
  optional repository-aware agent layer.
- Markdown, AsciiDoc, and plain-text directory reviews from both the CLI and
  the Web UI.
- Self-contained HTML reports with diffs, finding provenance, severity, rule
  IDs, statistics, and filtered views.
- Asynchronous web reviews with live progress, cancellation, history, and
  report downloads.
- Event-driven GitHub pull request review through signed webhooks with
  changed-file filtering and delivery deduplication.
- SMTP notifications, bilingual (English / Simplified Chinese) UI and docs,
  an annotated benchmark corpus for the rule-preview path, Docker support,
  and security hardening for public deployments.
- Optional verification of model-sourced findings through any
  OpenAI-compatible `chat/completions` endpoint before report generation,
  with verdict badges (`confirmed` / `rejected`) in HTML reports. Cost-capped,
  failure-tolerant, disabled by default, and never persists the API key.
- Modular runtime: review orchestration, Flask app factory, GitHub webhook
  routes, and the CLI entry point split into focused modules.
- Pluggable correction model backends: the default local transformers runtime
  can be replaced with Ollama or any OpenAI-compatible endpoint via
  configuration or environment variables.
- Report markup, styles, and scripts moved out of Python string literals into
  plain web assets under `src/docsifter/templates/report/`.
- Documented the single-instance deployment boundary and scaling guidance in
  the READMEs.
- Pluggable text extraction: Markdown and AsciiDoc parsing moved into a
  registry (`docsifter.extractors`); new file formats integrate through
  `register_text_extractor` without touching the corrector.
- Structured logging (`DOCSIFTER_LOG_FORMAT=json`, `DOCSIFTER_LOG_LEVEL`) for
  review metrics, correction-guard warnings, the email subsystem, retention, and
  web request logs, plus dependency-free in-process metrics exposed at
  `/metrics` in Prometheus text format.
- Optional LLM cross-line context review (`DOCSIFTER_CONTEXT_REVIEW_ENABLED`)
  that reports terminology inconsistency, contradictions, and broken
  cross-references across lines, capped at ten issues per file.
- Benchmark runner support for remote model backends (`--backend ollama|openai`
  with `--base-url`), per-case error tolerance, and an expanded annotated
  corpus of 76 cases, including seven errors paired with and without a
  technical token so that guards skipping dense text stay measurable.
- Retention for review history, monitor logs, and generated report files
  (`retention_days`, default 90), applied at web startup.
- All narration routed through the logger. Per-file progress, startup, and
  `--debug` traces are log records, so `DOCSIFTER_LOG_FORMAT=json` covers the
  whole run; the CLI's result stays on stdout, separate from the log stream.
- Web layer split by concern: an app factory plus one module each for the
  administrator gate, the error contract, and each route group.
- Vendored Web UI assets. Tailwind (as a generated subset) and Font Awesome
  ship inside the package, so the UI renders on an air-gapped host and no CDN
  is contacted.
- CI on every pull request: lint, the smoke suite on Python 3.10 and 3.13, the
  frontend tests, the benchmark, and an install of the built wheel.

## Planned

Near term:

- Deeper test coverage of the correction engine and more correction backends.
- Share more of the review pipeline between the local and GitHub paths; they
  currently duplicate the per-file loop around a common core.
- Split the Web UI script. The Python side is now one module per concern;
  `static/js/app.js` is still one file of around three thousand lines.
- Give the second-pass reviewer more to judge with. It currently sees only the
  original sentence and the suggested correction, with no file, neighbouring
  lines, or project terminology, which is enough for typos but weak for
  terminology decisions. Supplying allowlist terms or adjacent lines is the
  first thing to try if terminology verdicts prove unreliable.

Later:

- External task storage so multi-replica deployments can share queue state
  and history safely.

See [CHANGELOG.md](CHANGELOG.md) for the detailed change history.
