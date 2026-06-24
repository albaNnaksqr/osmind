# osmind

A stateless contribution radar, packaged as a Claude Code **skill**.

Ask it ("跑一下 osmind" / "看看有什么能贡献的") and it fetches recent open issues from
the repos I follow, judges which are actually worth contributing to — against my
GPU/time resources, my interests, and objective facts (is someone already on it,
how busy, how stale) — and writes a short ranked shortlist as a Markdown report
plus a macOS notification. It always slips in 1–2 picks *outside* my interests so
I don't get stuck in my own bubble.

Personal tool. One user, one profile. No database, no memory of past decisions —
every run is a fresh judgment of what's live right now.

## Why a skill (not a program)

Once osmind went stateless, it stopped needing to be a program. A stateless
"fetch → judge → present" pipeline is exactly what an agent does natively: the
skill is the instructions, Claude Code is the runtime and the judge. That's
*better* judgment than the old fixed-prompt LLM call — the agent can `gh issue
view`, read the linked PR, even grep a local checkout — and there's almost no code
to maintain. It also means no secrets to manage: GitHub auth is `gh`'s job
(keychain), and there's no separate LLM key because the agent is the judge.

The pipeline lives in [`SKILL.md`](SKILL.md): `gh` fetch → collect signals →
judge → Markdown report + macOS notify. Reports land in `output_dir/reports/`,
never the Obsidian vault — a triage sweep is inbox-grade, not knowledge.

## Setup

```bash
gh auth login          # one-time; token goes to the macOS keychain
```

Copy [`profile.yaml.example`](profile.yaml.example) to `~/.config/osmind/profile.yaml`
and fill in interests / skills / resources / watched repos / output_dir. No keys.

Install the skill (symlink so git stays the source of truth):

```bash
ln -s ~/workspace/osmind ~/.claude/skills/osmind
```

Then in Claude Code: *"跑一下 osmind"*.

### Optional: scheduled push

This skill is pull. To push on a schedule, point a launchd job at a headless run
twice a week:

```bash
claude -p "run the osmind skill" --allowedTools "Bash,Read,Write"
```

## Legacy

Earlier forms are recoverable by tag:
- `v0-tui` — the TUI / Learning-Pack / Contribution-Radar shapes and the stateful
  decision-memory version.
- `v1-stateless-cli` — the stateless Python CLI (`osmind report` / `osmind profile`)
  with a baked-in DeepSeek judgment call, before this pure-skill rewrite.
