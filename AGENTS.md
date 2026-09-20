# AGENTS.md

This file defines the review contract for Codex-assisted documentation review in
this repository. DocSifter can run without Codex; use these rules when pairing
the local small-model review layer with Codex Local, Codex Cloud, or another
repository-aware agent.

## Review Layers

1. Rule preview
   - Run fast checks without loading a model.
   - Use this pass for common terminology, wording, and allowlist issues.
   - Only deterministic `error` findings should be considered CI-blocking.

2. Local small-model AI review
   - Recommended starting model: `shibing624/chinese-text-correction-1.5b`.
   - Use this pass for typo, wording, and sentence-level correction.
   - Keep code snippets, SQL, command output, API names, and product terms intact.
   - Treat model output as a suggestion, not product evidence. Low-risk spelling
     and grammar fixes may be applied when their scope is clear; factual,
     procedural, compatibility, and command changes need evidence or review.
   - If the requested model cannot load, fail the review; do not silently downgrade.

3. Codex context review
   - Use this pass for repository-aware issues that require more than one file.
   - Check links, anchors, includes, navigation, sidebar paths, and examples.
   - Compare documentation claims against nearby source, examples, configuration,
     tests, and release notes when available.

## Agent Roles

- Local reviewer: runs DocSifter and summarizes generated findings.
- Context reviewer: checks cross-file consistency, broken references, and stale
  product behavior.
- Release reviewer: focuses on release notes, migration notes, public examples,
  and user-facing setup instructions.

## Review Rules

- Preserve fenced code blocks, inline code, SQL, shell commands, API names, file
  paths, and product identifiers unless there is clear evidence they are wrong.
- Treat allowlist terms and protected patterns as intentional domain language.
- Prefer precise, evidence-backed findings over broad style advice.
- Flag broken links, stale anchors, missing includes, and mismatched sidebar or
  navigation references.
- Flag documentation that contradicts current examples, configuration defaults,
  CLI options, or tests.
- Do not invent product behavior. If evidence is missing, mark the item as an
  open question instead of rewriting it as fact.
- Keep comments actionable: include file path, line or section, observed issue,
  and suggested fix.
- Preserve each finding's source (`rule`, `model`, or `rule+model`), severity,
  and rule ID when DocSifter provides them.
- Deduplicate overlapping rule and model findings before presenting the result.

## Release Gate

- Run rule preview on changed documentation first.
- Run the local model only when its dependencies and model weights are available.
- Run context review after local findings are resolved or intentionally accepted.
- Require evidence or human review for model-generated factual, procedural,
  compatibility, command, or scope changes; do not block safe local wording fixes
  solely because a model suggested them.
- Use periodic full-repository reviews for drift; keep pull-request checks focused
  on changed files and their references.

## Suggested Commands

```bash
pip install -e .
docsifter ./examples/sample-docs
pip install -e ".[model]"
docsifter ./examples/sample-docs --model shibing624/chinese-text-correction-1.5b
python -m pytest tests/smoke
```

## Output Format

When acting as a Codex reviewer, report findings in this order:

1. Blocking issues that can mislead users or break setup.
2. Cross-file consistency issues.
3. Language, terminology, and clarity issues.
4. Open questions or assumptions.

Each finding should include severity, file path, evidence, and a concrete
suggested change.
