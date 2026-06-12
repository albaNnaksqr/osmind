# osmind Personal Watcher Shape

Date: 2026-06-12

## Summary

osmind becomes a headless repository watcher and decision-state store for a single user. It stops embedding judgment (ranking prose, briefs, grounding) and stops owning an interactive UI. General agents (Claude Code, Codex) supply the judgment; osmind supplies what agents lack: continuous observation and durable decision memory.

The product is two outlets on top of one state store:

1. a Markdown **digest** pushed into the user's notes vault,
2. an **agent interface** (CLI with JSON output, wrapped by a Claude Code skill) for queue queries and decision write-back.

The TUI is retired. The learning line is deleted.

## What osmind is no longer

- Not a recommender: no LLM-written briefs, no repo grounding, no pre-rendered agent prompts. The agent derives these itself, fresher, at the moment of work.
- Not a reading surface: no TUI detail views, no in-app packet reader. Reading happens in Obsidian or the editor.
- Not a general product: single user, one profile, conventions hardcoded where a choice would otherwise need config.

## State model (the core)

Keep and consolidate the existing SQLite store (`osmind/cache/store.py`) around three facts:

- **Items**: issues/PRs from watched repos — metadata, body/comment hashes, `updated_at`, fetch time.
- **Decisions**: per item — `undecided | continue | defer | discard`, dated reason, resource snapshot at decision time (`osmind/decision.py` already models this).
- **Resurfacing**: an item deferred/discarded earlier re-enters the active set when its upstream content hash changes or the configured `resources` change. This rule is the heart of the product.

`profile.yaml` keeps `interests`, `skills`, `resources`, `watching`, `output_dir`. Drop `llm` and `external_agents` from the required path (see Open Questions).

## Vault integration: osmind is the Issue Radar

The user's Obsidian vault (`~/workspace/Note`) already runs an isomorphic pattern for papers: `Sources/Paper_Radar/2026-WXX.md` weekly digests (Why surfaced / Status / User signal / Next, wiki-links to deeper notes), a lightweight `Reading_Queue.md`, agent write-protocols (`AI_WORKFLOW.md` family), and a weekly review habit. osmind slots in as the **Issue Radar**: same shape, GitHub as the source instead of arXiv, with one upgrade — the fetch/diff layer is deterministic code instead of an agent browsing.

Concretely:

- Digests land in `Sources/Issue_Radar/2026-WXX.md` (weekly files, one dated section per run), formatted in the Paper Radar entry style so the existing weekly review covers both radars.
- The decision-log mirror lives next to them; entries wiki-link to `Projects/<project>` pages via the vault's `Project_Index.md` mapping (e.g. sgl-project/sglang work links to its project page, follow-up work logs to `Projects/<project>/devlog/`).
- State ownership follows the vault's own rule ("Reading_Queue 不是长期状态源"): **osmind's SQLite is canonical for issue state and decisions; vault files are generated, human-readable mirrors.** Nothing parses the vault back.
- The triage skill follows the `ai-dev-log` pattern: intentionally thin, pointing the agent at a protocol file in the vault (`AI_ISSUE_WORKFLOW.md`) that defines when to `sync`, how to judge against the profile, and to write conclusions back via `osmind decide`. Vault notes are written 以中文为主 per the vault's language preference.

## Outlet 1: Digest

Command: `osmind digest` (run manually or via cron/launchd; osmind itself does not schedule). `digest` always syncs first; there is no separate fetch step to forget.

Behavior: fetch watched repos, diff against the store, append a dated run section to `Sources/Issue_Radar/2026-WXX.md` in the vault (rerunning on the same day replaces that day's section).

Content is **deterministic facts, not LLM prose**:

- New items since the last digest, with labels, state, and a keyword-overlap note against profile interests (plain heuristic, clearly labeled as such).
- Resurfaced items: previously deferred/discarded, now changed — with the original decision reason and what changed (new comments, label change, body edit).
- Changes to items marked `continue`.
- Counts: active queue size, undecided backlog.

Each item links to GitHub and embeds a ready-to-paste line for the agent outlet, e.g. `osmind show sgl-project/sglang#2187`.

No digest entry tries to answer "should I do this" — that question is routed to the agent or the human.

## Outlet 2: Agent interface

A small CLI surface with `--json`, designed to be called by a Claude Code skill:

- `osmind sync` — fetch watched repos, update the store, print a change summary (also runs implicitly at the start of `digest`).
- `osmind queue [--filter active|undecided|continue|resurfaced] --json` — list items with state, decision history pointer, and content-hash freshness.
- `osmind show <repo>#<number> --json` — full cached item (body, comments) plus decision log and resource snapshots.
- `osmind decide <repo>#<number> <continue|defer|discard> --reason "..."` — write a decision with the current resource snapshot, and append a line to the vault decision log (`Sources/Issue_Radar/Decision_Log.md`).
- `osmind profile --json` — interests, skills, resources, watched repos.

A thin skill (`issue-radar` or similar, mirroring `ai-dev-log`) wraps these: it points the agent at the vault protocol file, which instructs it to `sync`, read `queue` and `profile`, judge fit against resources, discuss with the user, and write conclusions back via `decide`. The agent is the ranking engine; osmind is its memory and eyes.

MCP server is deferred — the CLI+skill path covers the same need with less machinery. Revisit only if a second agent surface (e.g. claude.ai) needs access.

## Keep / delete map

Keep (slim as needed):

- `cache/store.py`, `decision.py`, `config.py`, `logs.py`
- `github/` (client, models)
- `services/library.py` (becomes the query layer behind the CLI)
- `notes/vault.py` reduced to a Markdown writer for digests

Delete:

- `tui/` entirely (app, screens, widgets, workflow, dialogs) — including the already-dead `learn.py`, `review.py`, `socratic.py`, `chat_panel.py`, `diff_viewer.py`
- `engine/issue_brief.py`, `engine/issue_explainer.py`, `engine/repo_grounding.py`, `engine/grounding.py`, `engine/socratic.py`
- `packs/generator.py`, `packs/renderer.py`, `packs/models.py`, `packs/opener.py` — packets as an artifact class are retired; decision history lives in SQLite and surfaces through `show` and digests
- `agents/launcher.py` — launching agents is the skill's job, not osmind's

Existing generated packets in the vault remain as plain Markdown history; nothing migrates them.

## Implementation order

1. Carve the CLI (`sync`, `queue`, `show`, `decide`, `profile`) on top of the existing store and library service, with tests at the JSON boundary.
2. Implement `digest` as pure store-diff rendering.
3. Write the triage skill that drives the CLI.
4. Delete the TUI, engine judgment modules, and packs pipeline; strip `pyproject.toml` of textual and related deps.
5. Rewrite README for an audience of one.

Order matters: outlets land first so the tool never loses usability mid-surgery.

## Success criteria

- A week of normal use touches only: cron-produced digests in Obsidian, `osmind` CLI via Claude Code, and GitHub itself.
- Re-running `digest` or `sync` on unchanged upstream does no LLM work and no redundant GitHub work.
- A deferred issue that gains a reproduction comment shows up in the next digest with the original defer reason attached.
- The codebase fits in one head: target under ~1500 lines of source.

## Decided (2026-06-12)

- `ranker` is deleted. Digests carry keyword-overlap heuristics only; judgment belongs to the agent. Revisit only if digests feel too flat in practice.
- Decisions mirror to a Markdown log in the vault (`Sources/Issue_Radar/Decision_Log.md`); SQLite stays canonical.
- `digest` always syncs first; `sync` remains available standalone for the skill path.
- Digests integrate into the existing vault radar pattern (`Sources/Issue_Radar/`, weekly files, Paper Radar entry style) rather than a separate `output_dir/digests/` tree.

## Open Questions

- Weekly file with per-run sections vs. one file per run — start weekly to match Paper Radar and the weekly review; split only if files grow unwieldy.
- Should `AI_ISSUE_WORKFLOW.md` live in the vault (consistent with the other protocols) or in this repo? Default: vault, since the vault is the canonical workflow home and skills are deliberately thin.
