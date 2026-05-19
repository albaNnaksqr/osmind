# osmind Contribution Radar Product Shape

Date: 2026-05-19

## Summary

osmind should evolve from a generic Learning Pack generator into a local-first contribution radar for developers who want to understand and contribute to open-source projects.

The product should help a user answer one practical question quickly:

> Is this GitHub issue or PR worth my time, and what should I do next?

Learning Packs remain the durable artifact, but they should become action-oriented contribution packets instead of broad study notes.

## Target User

The strongest initial user is not every open-source developer. It is a developer who:

- follows one or more large repositories over weeks or months,
- wants to build contribution context without reading every issue manually,
- is comfortable with local tools, Markdown, and terminal workflows,
- may already use Codex, Claude Code, or another coding agent,
- wants a better triage and learning loop before attempting implementation.

The product should not assume the user already uses Obsidian. Obsidian can be a recommended reader, but the core output should be plain Markdown in a configurable output directory.

## Product Positioning

osmind is a contribution decision and preparation tool.

It is not primarily:

- a generic GitHub issue finder,
- a task manager,
- a coding agent,
- a note-taking app,
- a replacement for GitHub or an editor.

It should sit before coding. Its job is to shrink the gap between "this issue looks interesting" and "I know whether to continue, what to inspect, and what evidence would prove progress."

## Core User Promise

Within 10-20 minutes, a user should be able to:

1. see the most relevant items from watched repositories,
2. understand why an item is recommended,
3. inspect evidence for difficulty and fit,
4. generate a concrete action packet,
5. decide whether to continue, defer, or discard the item,
6. hand a precise prompt to Codex or Claude if agent assistance is useful.

## Ideal First Screen

The first screen should be organized around the user's job, not the app's storage model.

Recommended top-level sections:

- Today: the highest-signal items from watched repositories.
- Queue: saved items the user intends to inspect later.
- Packs: generated contribution packets and learning records.
- Review: prior notes, unresolved questions, and low-confidence areas.
- Settings: effective config, output directory, LLM backend, GitHub status, and agent commands.

The current Discover/Packs/Review structure can remain internally, but the user-facing language should make Today or Radar the primary entry point.

The first TUI slice should keep the existing Discover tab but present it as an opportunity queue. The table should lead with the recommended action and reason instead of internal scoring dimensions.

## Today/Radar Item Design

Each recommended item should show enough evidence to be trusted.

Minimum visible fields for the full radar:

- repo and issue/PR number,
- title,
- source type,
- state,
- labels,
- freshness,
- fit score,
- resource fit,
- difficulty estimate,
- learning value estimate,
- agent suitability,
- whether a packet already exists,
- one-line recommendation reason.

Minimum visible fields for the current TUI slice:

- recommended action,
- one-line reason,
- issue number,
- title,
- labels.

Structured dimensions such as fit, resource fit, and actionability should stay available in the detail view rather than forcing the first screen to look like a scoring dashboard.

The detail view should explain the recommendation with evidence:

- which profile interest or skill matched,
- which labels, files, symbols, or comments contributed to the score,
- whether the item has reproduction steps,
- whether a likely test path exists,
- whether maintainer discussion suggests it is still actionable,
- whether the next step is reading, reproducing, validating, or implementing.

In the TUI, the detail view should separate these jobs visually. The left pane should be a short, decision-oriented Analysis panel. The right pane should be a scrollable Source panel containing the generated summary, original issue text, and comments. `Tab` should switch focus between the two panes.

## Action Model

The main actions should map to decisions a user naturally makes:

- Inspect: read source metadata and recommendation evidence.
- Generate Packet: create or refresh the Markdown action packet.
- Open Packet: open the generated Markdown file.
- Open Source: open the GitHub issue or PR in a browser.
- Copy Agent Prompt: copy a precise exploration prompt.
- Continue: mark as worth pursuing.
- Defer: keep for later without treating it as active.
- Discard: hide from the active radar unless it changes upstream.

Keyboard shortcuts can remain, but the UI should make the primary flow obvious without requiring the README.

## Contribution Packet Format

Learning Packs should be reframed as Contribution Packets. The Markdown file should still use YAML frontmatter and remain readable in any editor.

Common frontmatter:

```yaml
type: osmind-contribution-packet
source_type: issue
repo: owner/name
number: 1234
title: Example title
url: https://github.com/owner/name/issues/1234
status: inspecting
decision: undecided
confidence: low
generated_at: 2026-05-19
source_updated_at: 2026-05-19T10:30:00Z
modules: []
tags:
  - osmind
  - open-source
```

Required sections:

- What This Is: a concrete one-paragraph restatement of the issue or PR.
- Why It May Fit You: evidence tied to profile interests, skills, or watched modules.
- Continue Or Stop Criteria: clear signals for whether to continue, defer, or discard.
- First 10 Minutes: the smallest useful inspection path.
- Files And Symbols To Inspect: concrete search terms, files, modules, or functions when available.
- Validation Path: commands, tests, reproduction steps, or missing evidence to find.
- Agent Exploration Prompt: a prompt that asks an agent to investigate before implementing.
- Decision Log: dated notes about continue/defer/discard decisions.
- Notes: freeform user notes and review answers.

PR packets can additionally include:

- What Changed,
- Diff Map,
- Design Questions,
- Follow-Up Contribution Ideas.

Issue packets can additionally include:

- Known Facts,
- Missing Context,
- Reproduction Hypothesis,
- Maintainer Signals.

## Recommendation Model

The app should move beyond a single score and one sentence.

Each item should have these analysis fields:

- fit: how closely it matches the user's profile,
- resource_fit: whether the user's configured GPUs, time, and local environment are enough to reproduce or validate the item,
- difficulty: expected effort to understand or act,
- learning_value: how much project context the user can gain,
- actionability: whether the item has enough evidence to take a next step,
- agent_suitability: whether Codex or Claude can help productively,
- confidence: how reliable the analysis is.

The UI can still compress these into a simple rank, but the detail view and packet should expose the factors.

## Evidence Requirements

A recommendation is weak unless it can cite concrete evidence.

Useful evidence includes:

- matching words from title, labels, body, and comments,
- changed files and modules for PRs,
- mentioned files, functions, stack traces, commands, or error messages,
- maintainer comments or labels such as good first issue, bug, help wanted, stale, needs reproduction,
- presence or absence of reproduction steps,
- presence or absence of tests or validation hints.

If evidence is missing, the app should say so plainly instead of pretending the recommendation is strong.

## TUI Behavior

The TUI should be a control console.

It should avoid long-form reading and chat as the primary experience. Long explanations, diffs, and notes belong in Markdown, GitHub, the user's editor, or a local checkout.

The TUI should clearly show states:

- never fetched,
- fetched but not analyzed,
- analysis cached,
- packet generated,
- packet stale,
- analysis failed,
- user continued,
- user deferred,
- user discarded.

The app should preserve old cached data when refresh fails.

## Configuration

The current `notes_vault` field should be renamed or aliased to `output_dir`.

Recommended config shape:

```yaml
profile:
  interests:
    - SGLang inference optimization
  skills:
    - Python
  constraints:
    time: part-time
    compute: local

watching:
  - repo: sgl-project/sglang

output_dir: ~/workspace/Note/osmind

llm:
  base_url: http://localhost:30000/v1
  model: Qwen3.5-27B
  api_key_env: OPENAI_API_KEY

external_agents:
  claude_code: claude
  codex: codex
```

Backward compatibility with `notes_vault` should be preserved for at least one release.

## Success Metrics

Product success should be measured by whether users make better contribution decisions, not by the number of generated notes.

Useful signals:

- user marks an item continue/defer/discard after inspection,
- user opens a generated packet,
- user copies or launches an agent prompt,
- user updates the decision log,
- user returns to a packet later,
- generated packets contain concrete evidence instead of generic templates,
- unchanged items are not repeatedly reanalyzed.

## First Implementation Slice

The first slice should avoid a full rewrite.

Recommended scope:

1. Add decision fields to cached packs/items: undecided, continue, defer, discard.
2. Rename UI language from Learning Pack to Contribution Packet where user-facing.
3. Add action-oriented packet sections while preserving existing Markdown compatibility.
4. Expand ranking output from score/reason to structured analysis factors.
5. Show evidence and stop/continue criteria in the detail view.
6. Keep Obsidian compatibility but introduce `output_dir` as the neutral config name.

This slice should produce visible product value without requiring full codebase search or repository indexing.

## Open Questions

- Should Today/Radar include PRs before issues by default?
- Should discarded items reappear when upstream `updated_at` changes?
- Should agent launch remain a hidden shortcut or become an explicit action?
- Should packet status live only in Markdown frontmatter, SQLite, or both with conflict resolution?
- How much local repository inspection should happen before the app requires a checkout path?
