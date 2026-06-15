# osmind

A headless watcher and decision-memory for the open-source repos I follow.

osmind is not a recommender and not a UI. It watches a few GitHub repos, remembers what I decided about each issue and *why*, and resurfaces an issue when the upstream content or my own resources change. Judgment is delegated to a coding agent (Claude Code / Codex); osmind supplies the two things an agent session doesn't have: **continuous observation** and **durable decision memory**.

This is a personal tool. It assumes one user, one profile, and my Obsidian vault.

## Why it works this way

Three layers, only two of which are worth owning:

- **Judgment** (rank an issue, brief it, ground it in the repo) — a general agent does this better and fresher at the moment of work. osmind doesn't do it.
- **State** (my resources, the defer/discard history, the resurface rule) — an agent forgets this between sessions. osmind is canonical here.
- **Watching** (fetch, diff, notice change unprompted) — an agent only acts when asked. osmind runs from cron.

So osmind is the agent's memory and eyes, not its competitor. The full reasoning is in [`docs/superpowers/specs/2026-06-12-personal-watcher-shape.md`](docs/superpowers/specs/2026-06-12-personal-watcher-shape.md).

## Two outlets

**1. Digest** — `osmind digest` (cron) syncs and writes a Markdown section into the Obsidian vault at `Sources/Issue_Radar/YYYY-WXX.md`, in the same style as my Paper Radar. New issues, resurfaced issues (with the original defer reason and what changed), and updates to issues I'm continuing. Plain facts, no LLM prose. The weekly review already covers it.

**2. Agent CLI** — a small surface a Claude Code skill drives:

```bash
osmind sync                       # fetch watched repos, update the store
osmind queue --filter active      # active / undecided / continue / resurfaced / deferred / discarded / all
osmind show <repo>#<n>            # body, comments, decision log
osmind decide <repo>#<n> defer --reason "no H20 cluster"
osmind profile                    # interests, skills, resources, watched repos
```

All take `--json`. `decide` also mirrors a line to `Sources/Issue_Radar/Decision_Log.md`; the SQLite store stays canonical. The driving protocol lives in the vault at `AI_ISSUE_WORKFLOW.md`, fronted by the thin `issue-radar` skill.

## The resurface rule

The heart of it: an issue I deferred or discarded re-enters the active queue when either

- its upstream content hash changes (new comments, edited body, label change), or
- my configured `resources` change (e.g. I get more GPUs).

That's the memory an agent can't hold — "why did I skip #2187 three weeks ago, and has anything changed since."

## Setup

```bash
pip install -e .
```

`profile.yaml` (see `profile.yaml.example`):

```yaml
interests: [sglang, slime, ai infra]
skills: [python]
resources:
  gpus: 1 x Nvidia-Spark
  time: part-time
watching:
  - repo: THUDM/slime
  - repo: sgl-project/sglang
output_dir: ~/workspace/osmind-packets   # SQLite cache lives here
vault: ~/workspace/Note                   # digests + decision-log mirror
```

`llm` and `external_agents` are no longer required. Set `GITHUB_TOKEN` for higher rate limits.

Cron a daily digest:

```cron
0 9 * * * cd ~/workspace/osmind && .venv/bin/osmind digest
```

Then triage from Claude Code: "看看 slime 有没有我能做的 issue" → the `issue-radar` skill drives the CLI, judges against my resources, and writes decisions back.

## Legacy

The old TUI / Learning-Pack / Contribution-Radar shape is tagged `v0-tui`.
