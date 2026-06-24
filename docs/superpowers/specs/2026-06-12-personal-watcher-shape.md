# osmind Personal Watcher Shape

Date: 2026-06-12

## Revision 3 — 2026-06-24: become a pure Claude Code skill

Once the memory layer was gone (revision 2), osmind was a stateless
"fetch → judge → present" pipeline — which is precisely what an agent does
natively. The Python package had become a worse, fixed-prompt reimplementation of
what Claude Code already does: it could only judge the payload it was fed, while an
agent can `gh issue view`, read the linked PR, even grep a local checkout.

So the whole package is replaced by a single `SKILL.md`. `gh` (keychain auth)
replaces PyGithub + `GITHUB_TOKEN`; the agent itself replaces the DeepSeek
judgment call, so there is no LLM key. Net: no secrets to manage, almost no code.
The skill stays pull; an optional launchd job running `claude -p "run the osmind
skill"` gives push twice a week. The Python CLI is recoverable at tag
`v1-stateless-cli`.

Everything below is superseded design history.

## Revision 2 — 2026-06-15: drop the memory layer; pure stateless push

After the scheduled report landed (revision 1 below), the decision/memory layer
was cut entirely: no continue/defer/discard, no resurface rule, no SQLite store,
no `sync`/`queue`/`show`/`decide` commands, no vault decision-log mirror.

Why: the report only judges the ~30 most recently active issues per repo. For a
busy repo that's a thin, fast-churning slice, so remembering past judgments buys
little — rejected issues fall out of the window on their own, and anything the
user starts working on auto-drops because its PR/assignee appears in the
objective signals (the `occupied` skip). The user's verdict: "osmind 只需要做到
给我推送就好了，已经没有必要记住我之前的判断."

osmind is now stateless: `osmind report` fetches → enriches with signals → one
LLM judgment → Markdown report in `output_dir/reports/` + macOS notification.
The only other command is `osmind profile`. Source dropped to ~850 lines.

Everything below (revision 1 and the original spec) is superseded and kept only
as design history.

## Revision 2026-06-15: judgment moves back in, as a scheduled push

The first cut of this spec deleted judgment entirely and made the automated
output a deterministic, dumb digest written into the Obsidian vault, with all
ranking pushed to a pull-based `issue-radar` skill the user invokes manually.

Real use killed that design. The dumb vault digest was just collection — it
violated the vault's own "knowledge, not inbox" bar (Paper Radar entries record
papers the user *engaged with*; a 36-issue keyword dump does not). And the
skill made judgment pull-based when the user wanted **push**.

Corrected shape (what the code now implements):

- The judgment is **back inside an automated, scheduled command** (`osmind report`,
  cron Mon/Thu), not a skill the user opens. The user wants the recommendation to
  arrive, not to go ask for it.
- Judgment is an **LLM call fed objective signals** — linked open PRs, assignees,
  participant/comment counts, staleness — plus resources, interests, and decision
  history. This is strictly more than the old ranker (which saw only issue text).
- It must include **1-2 serendipity picks** outside the user's interests, so the
  candidate set fed to the LLM is *not* interest-pre-filtered.
- Output is a Markdown report in `output_dir/reports/`, **never the vault**, plus a
  **macOS notification**. Only the user's own decisions mirror to the vault
  (`Sources/Issue_Radar/Decision_Log.md`).
- The deterministic `digest` command is deleted; `report` degrades to a raw
  candidate list when the LLM is unreachable, so cron survives.

The state layer below (store, decisions, resurface rule) is unchanged and is the
input to the judgment. Sections below describe the superseded first cut; the
revision above governs.

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
