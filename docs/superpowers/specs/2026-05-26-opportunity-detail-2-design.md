# Opportunity Detail 2.0 Design

## Purpose

osmind should help a developer decide whether an open-source issue is worth turning into a learning pack without forcing them to leave the TUI, reread a long English GitHub thread, or ask another agent to re-explain the same context.

The next product step is to make the Discover issue detail view the decision surface for one complete user loop:

1. Understand what the issue is about.
2. See why osmind thinks it may fit the user's profile.
3. Identify risks and missing evidence.
4. Get a concrete first validation path.
5. Generate a learning pack with an agent-ready prompt.

This spec focuses on issue opportunities. PR support remains out of scope for this iteration.

## User Problem

The current recommendation experience is too shallow. A score and short reason can point the user toward an issue, but it does not answer the questions that decide whether the user can act:

- What is this issue actually asking for?
- Which part matches my interests or skills?
- What is uncertain or risky?
- What should I inspect first?
- How do I hand this to Codex or Claude without rebuilding context manually?

The expected user is a developer using open-source contribution as a learning and influence-building workflow. They may be comfortable with code, but not necessarily with the repository context, English issue phrasing, or the hidden assumptions in a large project.

## Goals

- Make the issue detail view useful enough that the user can decide `Do now`, `Defer`, or `Discard` without opening external tools first.
- Store the generated explanation in the local cache so repeated visits do not re-call the LLM.
- Make generated learning packs carry the same reasoning that appeared in Discover.
- Produce an agent prompt that can be copied or saved into the pack as the next action.
- Keep the feature local-first and compatible with the existing OpenAI-compatible LLM backend.

## Non-Goals

- Do not implement a conversational chatbot in this iteration.
- Do not make PRs a first-class Discover source yet.
- Do not add full application-wide localization yet.
- Do not require Obsidian.
- Do not change the current scoring model beyond consuming its reason and profile context.
- Do not automatically launch Codex or Claude from this flow.

## Product Behavior

### Discover Detail View

When the user selects an issue and presses `Enter`, the detail view should show two panes:

- `Analysis`: recommendation, decision factors, profile fit, risks, and first validation steps.
- `Source`: generated issue brief, original issue text, comments, and GitHub URL.

The generated issue brief should be in Chinese by default for this iteration because the current user pain is comprehension of English-heavy repository material. The original GitHub text remains visible below the brief.

The detail view should answer:

- `What is this issue about?`
- `Why might it fit me?`
- `What evidence supports that?`
- `What is missing or risky?`
- `What should I do in the first 30 minutes?`
- `What prompt should I give a coding agent if I continue?`

### Learning Pack Output

When the user presses `w`, the generated pack should include the same structured brief:

- `Issue Brief`
- `Why It May Fit You`
- `Risks And Missing Evidence`
- `First 30 Minutes`
- `Validation Path`
- `Agent Prompt`
- Original issue metadata and link

The pack should not merely say "this may fit you"; it must name the matched interests, matched skills, resource assumptions, and the concrete source signals used for the recommendation.

### Agent Prompt

The agent prompt should be specific enough to hand to Codex or Claude as a starting task. It should include:

- Repository and issue URL.
- One-sentence goal.
- Relevant context from the issue.
- First files, symbols, or search terms to inspect when available.
- Constraints from the user's resources.
- Expected validation command or validation shape.
- A stop condition when the issue is too underspecified.

The prompt should be saved into the pack. Copy-to-clipboard can be added later; this iteration only needs to render and persist it.

## Data Model

Extend `IssueBrief` with structured fields:

- `one_liner`: short Chinese explanation.
- `problem_summary`: what the issue asks for.
- `background`: domain or repository context needed to understand the issue.
- `matched_interests`: profile interests that match the issue.
- `matched_skills`: profile skills that match the issue.
- `resource_assessment`: whether the configured resources are enough, risky, or blocked.
- `evidence`: source signals from title, labels, body, comments, score reason, and profile.
- `risks`: missing context, reproduction uncertainty, resource concerns, or maintainer ambiguity.
- `first_steps`: first 30-minute inspection plan.
- `validation_path`: how the user can know they made progress.
- `agent_prompt`: prompt text for a coding agent.

The cache should continue to store the brief as JSON. The brief cache is valid only when:

- It exists for the same repo and issue number.
- The source issue content hash or updated timestamp has not changed.
- The scoring reason/profile-derived recommendation context has not changed.

If any of those change, regenerate the brief.

## Architecture

### Existing Components

- `osmind.tui.screens.discover`: owns the issue list, detail view, and start-work flow.
- `osmind.engine.issue_brief`: generates and renders issue briefs.
- `osmind.engine.llm`: calls an OpenAI-compatible backend.
- `osmind.cache.store`: persists issues, scores, packs, and brief JSON.
- `osmind.services.library`: writes learning pack Markdown.

### Proposed Changes

`issue_brief.py` becomes the boundary for LLM output. It should expose:

- `IssueBrief`: dataclass with the new structured fields.
- `IssueBriefGenerator.generate(issue, reason, profile_context)`.
- `issue_brief_from_json(raw)`.
- `render_issue_brief_markdown(brief)`.
- `render_agent_prompt(brief)` if separating the prompt helps testing.

`discover.py` should not know prompt details. It should request a brief, render it, and update panes.

`library.py` should accept an optional `IssueBrief` and include all structured sections when writing the pack.

`cache.store` should either keep the current brief JSON storage or add metadata fields for invalidation. If adding columns is too invasive, store invalidation metadata inside the JSON payload for this iteration.

## Flow

### Detail View Flow

1. User highlights an issue.
2. User presses `Enter`.
3. Discover immediately shows the existing decision panel and source skeleton.
4. Discover checks cache for a valid `IssueBrief`.
5. If valid, render cached brief.
6. If missing or stale, call `IssueBriefGenerator`.
7. Store the brief JSON with invalidation metadata.
8. Render the brief above the original issue text.

### Pack Generation Flow

1. User presses `w`.
2. Discover loads the cached brief or generates one.
3. `PackLibrary.write_issue_pack(issue, brief=brief)` writes the learning pack.
4. The pack includes the same recommendation evidence and agent prompt.
5. The start-work panel shows the first validation path and agent prompt summary.

## Error Handling

- If brief generation fails, the detail view must still show the original issue text.
- The error should be written to `osmind.log`.
- The user-facing message should say that the Issue Brief failed and where the log is.
- Pack generation should still work without a brief, but the pack should mark the missing brief section clearly.
- Invalid or partial LLM JSON should be recovered when possible; otherwise fail the brief generation and keep the raw issue visible.

## Prompt Requirements

The LLM prompt should require strict JSON with no markdown wrapper. It should instruct the model to:

- Answer in Chinese.
- Ground claims in issue title, labels, body, comments, score reason, and user profile.
- Avoid pretending to know repository internals when evidence is absent.
- Explicitly mark uncertainty.
- Produce concrete first steps and validation ideas.
- Produce an agent prompt that is useful but not overconfident.

The generator should validate required fields and normalize missing optional lists to empty lists.

## Testing

Add focused tests for:

- `IssueBrief` JSON round trip with all new fields.
- Rendering includes `Why It May Fit You`, `Risks`, `First 30 Minutes`, `Validation Path`, and `Agent Prompt`.
- Cached brief is reused without constructing an LLM client.
- Cached brief regenerates when recommendation reason changes.
- Pack generation includes the agent prompt and structured evidence.
- Detail view still shows original issue text if brief generation fails.
- Invalid LLM JSON raises a controlled error and logs through the existing path.

Existing full test suite should remain green.

## Acceptance Criteria

- From Discover, pressing `Enter` on an issue shows a Chinese brief plus original issue text.
- The brief names matched interests, matched skills, resource assessment, risks, and first validation steps.
- Pressing `w` writes a learning pack containing the same structured brief and an agent prompt.
- Returning to the same issue uses cached brief data unless the issue or recommendation context changed.
- If LLM generation fails, the user can still view the original issue and generate a basic pack.
- `python -m pytest -q` passes.

## Implementation Notes

- Keep current `notes_vault` internal naming unless changing it is directly required; `output_dir` compatibility already maps to that path.
- Prefer extending the current `IssueBrief` path instead of adding a parallel "detail explanation" object.
- Keep copy-to-clipboard out of this iteration. Rendering and persistence are enough to unblock user workflow.
- Keep the UI keyboard-first: `Enter` to inspect, `g` to open GitHub, `w` to start work, `o` to open the pack.

## Self-Review

- No placeholders or TBD sections remain.
- The scope is limited to issue detail, brief generation, pack output, and tests.
- PR discovery, full localization, chat, and automatic agent launch are explicitly out of scope.
- Error behavior is defined for LLM failure and invalid JSON.
- Cache invalidation is specified without forcing a schema migration unless implementation requires it.
