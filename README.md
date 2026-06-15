# osmind

A scheduled contribution-radar for the open-source repos I follow.

osmind watches a few GitHub repos and, on a schedule, pushes me a ranked list of issues actually worth contributing to — judged against my GPU/time resources, my interests, and objective facts (is someone already on it, how crowded is it, how stale). It deliberately slips in 1-2 picks *outside* my interests so I don't get stuck in my own bubble. Output is a Markdown report plus a macOS notification.

This is a personal tool. One user, one profile.

## How it's built

Two layers, split at a CLI boundary:

- **osmind (a program)** — eyes + memory. Deterministic GitHub fetch, objective-signal collection, and a durable SQLite store of every issue and every decision I've made (continue/defer/discard, with reasons and a resource snapshot). It also runs the **resurface rule**: an issue I parked comes back when its upstream content changes or my resources change.
- **the LLM (judgment)** — called *inside* the scheduled report to rank contributability. Not a cheap baked-in scorer over issue text: it sees the objective signals and my decision history too.

The reasoning behind this shape is in [`docs/superpowers/specs/2026-06-12-personal-watcher-shape.md`](docs/superpowers/specs/2026-06-12-personal-watcher-shape.md).

## The report

`osmind report` (cron, e.g. Mon/Thu) does the whole loop:

1. **sync** — fetch watched repos, update the store, apply the resurface rule.
2. **collect signals** — for each active candidate, fetch objective facts: linked open PRs, assignees, comment/participant counts, staleness.
3. **judge** — one LLM call ranks the candidates against my resources + interests + the signals + my prior decisions, and picks 1-2 serendipity items outside my interests.
4. **write + notify** — a Markdown report at `output_dir/reports/YYYY-MM-DD.md`, and a macOS notification with the headline.

Reports land in osmind's own output dir, **not** my Obsidian vault — a triage sweep is inbox-grade, not knowledge. Only issues I actually decide to work on graduate into the vault as project notes, by hand.

If the LLM is unreachable, the report degrades to a raw candidate list instead of crashing — cron stays alive.

## CLI

```bash
osmind report                     # the scheduled loop above (--no-notify to skip the notification)
osmind sync                       # just refresh the store
osmind queue --filter active      # active / undecided / continue / resurfaced / deferred / discarded / all
osmind show <repo>#<n>            # body, comments, decision log
osmind decide <repo>#<n> defer --reason "no H20 cluster"
osmind profile
```

All take `--json`. `decide` mirrors a line into the vault at `Sources/Issue_Radar/Decision_Log.md` for grep-ability; the SQLite store stays canonical.

## The resurface rule

The memory an agent session can't hold. An issue I deferred or discarded re-enters the active queue (and so the next report) when either

- its upstream content hash changes (new comments, edited body, label change), or
- my configured `resources` change (e.g. I get more GPUs).

So a report can tell me "you skipped #2187 three weeks ago for lack of a cluster — a repro just landed and no one's on it."

## Setup

```bash
pip install -e .          # deps: PyGithub, PyYAML (LLM calls go over stdlib urllib)
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
output_dir: ~/workspace/osmind-packets   # SQLite cache + reports/ live here
vault: ~/workspace/Note                   # only the decision-log mirror
llm:                                       # required for `osmind report`
  base_url: http://localhost:30000/v1
  model: Qwen3.5-27B
  api_key: sk-your-key-here
```

Set `GITHUB_TOKEN` (sync/report fetch the API). Schedule the report Mon/Thu with launchd (or cron):

```cron
0 9 * * 1,4 cd ~/workspace/osmind && GITHUB_TOKEN=... .venv/bin/osmind report
```

## Legacy

The old TUI / Learning-Pack / Contribution-Radar shape is tagged `v0-tui`.
