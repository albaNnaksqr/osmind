# osmind Learning Pack Redesign

Date: 2026-05-15

## Summary

osmind should become a local-first Learning Pack generator for open-source contribution. It tracks repositories the user cares about, identifies PRs and issues worth learning from, and turns selected items into Markdown packs that can be read, annotated, reviewed, and used as context for Codex or Claude.

The TUI remains, but it becomes a lightweight control console. It should not be the main surface for reading diffs, long explanations, or chat. Deep reading happens in Obsidian, an editor, GitHub, or a local checkout.

## Problem

The current product experience has three core problems:

1. Analysis is repeated too often. Each run can rescore issues and PRs even when upstream content has not changed.
2. The Learn chat path is fragile. If the user answers a model question and the TUI does not visibly respond, there is little feedback about whether the input, worker, or LLM call failed.
3. The TUI is the wrong place to understand code changes. Users cannot comfortably inspect full diffs, jump between files, compare context, and answer Socratic questions in the same terminal view.

These are not just bugs. They indicate that osmind is trying to make the TUI carry too much of the learning experience.

## Product Positioning

osmind is not another GitHub issue finder and not another coding agent. It is an open-source Learning Pack system:

> Convert GitHub PRs and issues into local, durable, reviewable learning materials that help the user understand projects and decide when to contribute, with optional Codex or Claude assistance.

The primary artifact is a Learning Pack, not an interactive chat session.

## Related Products

Research found adjacent products in four categories:

- Issue recommendation tools such as OSS Notify, Devfound, OpenCollab, and GiveMeLabeledIssues focus on matching developers with issues or repositories.
- Issue analysis tools such as oss-issue-analyzer index local repositories, bulk-score issues cheaply, and deep-analyze selected issues with caching.
- PR learning tools such as sphinx-ci generate quizzes from PR diffs, but target merge gates and team CI workflows rather than personal open-source learning.
- Agent workflows such as GitHub Agent HQ, Copilot coding agent, Claude, Codex, and GitHub Actions wrappers focus on delegating issues or PR changes to coding agents.

osmind should borrow the useful architecture patterns from these tools while keeping a different center of gravity:

- Cache aggressively.
- Use cheap list-level scoring before deep analysis.
- Generate durable Markdown instead of ephemeral chat.
- Treat agent prompts as a section inside the pack, not as the whole product.

## Core User Flow

1. The user configures watched repositories, interests, skills, notes vault, LLM settings, and optional local repository paths.
2. The user opens osmind.
3. The Discover screen shows cached PRs and issues from watched repositories.
4. The user refreshes only when they want new upstream data.
5. osmind fetches changed items and reuses cached analysis for unchanged items.
6. The user selects a PR or issue and generates a Learning Pack.
7. osmind writes a Markdown file into the user's notes vault.
8. The user opens the pack in Obsidian or an editor and reads it alongside GitHub or a local checkout.
9. The user may copy or launch the included Codex or Claude exploration prompt.
10. The user updates status, confidence, notes, and answers directly in Markdown.
11. Review mode later surfaces unanswered questions and low-confidence areas from existing packs.

## First-Version Scope

The first version should support both PRs and issues, but implementation should be PR-first.

PRs are the best first target because they contain concrete diffs, touched files, and visible design decisions. Issues remain important because they are closer to contribution opportunities, but they often require local repository search or agent exploration to supply missing context.

### In Scope

- Persistent cache for GitHub item metadata and analysis outputs.
- PR Learning Pack generation from PR title, body, changed files, and patches.
- Issue Learning Pack generation from issue title, body, labels, comments when available, and cached analysis.
- Markdown rendering into `notes_vault/osmind/<repo>/`.
- TUI flow for discover, refresh, generate pack, open pack, and view pack status.
- Basic agent prompt section for Codex and Claude.
- Pack status fields: unread, reading, done.
- Confidence field for later review.

### Out of Scope

- Full in-TUI diff reading.
- Long in-TUI Socratic chat.
- Automatically solving issues.
- Blocking PRs with quizzes.
- Multi-user/team workflows.
- Full codebase RAG in the first version.

## TUI Design

The TUI should be a control console with four sections:

- Discover: list watched repositories, cached PRs, cached issues, scores, status, and freshness.
- Packs: list generated Learning Packs, status, confidence, last opened time, and source item.
- Review: surface unanswered questions, low-confidence packs, and recurring modules.
- Settings: show effective config, cache location, notes vault, LLM backend, and external agent commands.

Discover actions:

- `f`: refresh upstream metadata for the selected repository.
- `g`: generate or regenerate a Learning Pack for the selected item.
- `o`: open the existing pack.
- `a`: show or copy the agent prompt from the pack.
- `r`: force reanalyze selected item.

The TUI should always distinguish these states:

- Never fetched.
- Fetched but not analyzed.
- Analysis cached.
- Pack generated.
- Pack stale because upstream item changed.
- Analysis failed with visible error.

## Learning Pack Format

Packs are Markdown files with YAML frontmatter. The frontmatter makes packs queryable by Obsidian, scripts, and osmind itself.

Common frontmatter:

```yaml
type: osmind-learning-pack
source_type: pr
repo: owner/name
number: 1234
title: Example title
url: https://github.com/owner/name/pull/1234
status: unread
confidence: unknown
generated_at: 2026-05-15
source_updated_at: 2026-05-15T10:30:00Z
modules:
  - src/runtime
  - tests
tags:
  - osmind
  - open-source
```

### PR Pack Sections

- Why This Is Worth Reading
- What Changed
- Files To Read First
- Diff Map
- Reading Path
- Socratic Questions
- Agent Exploration Prompt
- If You Want To Contribute Next
- Review Later
- Notes

### Issue Pack Sections

- Why This May Fit You
- What Is Known
- Missing Context
- Investigation Path
- Files Or Symbols To Search
- Agent Exploration Prompt
- Human Checkpoints
- Learning Questions
- Notes

## Analysis Model

List-level analysis should be cheap and cacheable. It should produce enough signal to rank items without doing deep work for every issue or PR.

Suggested scores:

- fit: how well the item matches the user's interests and skills.
- learning_value: how useful the item is for understanding the project.
- difficulty: expected implementation or comprehension difficulty.
- impact: likely value to the project or user.
- agent_suitability: whether Codex or Claude can help explore or draft work.

Deep analysis should run only when generating or regenerating a pack.

## Cache Design

The cache should prevent repeated GitHub and LLM work. SQLite is preferred over ad hoc JSON because the app needs to query by repo, source item, update time, pack path, stale state, and analysis status.

Minimum tables:

- `github_items`: repo, type, number, title, body hash, labels, state, url, updated_at, fetched_at.
- `analysis`: item key, model, prompt version, input hash, scores, reason, generated_at, error.
- `packs`: item key, path, status, confidence, source_updated_at, generated_at, stale.

An item is stale when GitHub `updated_at`, relevant body/comment hash, or PR changed-files hash differs from the cached record.

## Architecture

Add service modules behind the TUI:

```text
osmind/cache/
  store.py

osmind/analysis/
  scorer.py
  diff_mapper.py
  issue_mapper.py

osmind/packs/
  models.py
  generator.py
  renderer.py
  opener.py
```

Existing modules should be migrated gradually:

- `Ranker` becomes part of `analysis.scorer`.
- `SocraticEngine` becomes pack question generation rather than live chat.
- `NotesVault` becomes a lower-level Markdown writer/reader for pack files.
- Textual screens call service APIs and should not contain GitHub or LLM business logic.

## Error Handling

The UI and CLI should expose failures as state, not silence.

- GitHub fetch failures should preserve old cache and mark refresh failed.
- LLM failures should allow pack generation with partial heuristic sections.
- Pack rendering failures should not mutate existing pack files.
- Open-file failures should show the path and the attempted command.
- If analysis fails, the item should remain selectable and regenerable.

## Testing Strategy

Tests should focus on service boundaries first:

- Cache stale detection for unchanged, updated, and changed PR files.
- PR pack rendering from fixture PR data.
- Issue pack rendering from fixture issue data.
- Analysis fallback when LLM returns invalid JSON or errors.
- TUI screens using mocked services rather than live GitHub or LLM calls.

Existing chat-input behavior does not need to be fixed if live chat is removed from the core flow. If any TUI input remains for review answers, it must have tests that verify submitted input updates visible state.

## Success Criteria

The redesign succeeds when:

- Reopening osmind does not reanalyze unchanged items.
- A user can generate a PR Learning Pack and read it comfortably outside the TUI.
- A user can generate an Issue Learning Pack with an investigation path and agent prompt.
- The TUI clearly shows cached, stale, generated, failed, and unread states.
- The app produces durable learning artifacts that improve future review and recommendation.

## Implementation Order

1. Introduce cache store and item freshness model.
2. Create Markdown pack models and renderer.
3. Generate PR Learning Packs from existing GitHub PR data.
4. Add Discover actions for generate/open pack.
5. Replace Learn chat with Packs screen.
6. Add Issue Learning Pack generation.
7. Add Review mode over pack frontmatter and unanswered questions.

