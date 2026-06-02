# osmind

**osmind** is a local-first workflow entry point and context router for developers who want to understand and contribute to open-source projects.

It watches GitHub repositories you care about, recommends PRs and issues that match your interests, and turns selected items into Markdown Contribution Packets. Each packet gives you recommendation evidence, continue/stop criteria, a first inspection path, key files, validation hints, and an optional Codex or Claude prompt, so you can route the next step to a human editor, Codex, Claude, or another agent without losing context.

```
┌─ osmind ─────────────────────────────────────────────────────┐
│ [Discover]  [Packs]  [Settings]                 Ctrl+Q: Quit │
├──────────────────────────────────────────────────────────────┤
│ Repo: sgl-project/sglang              Filter: all  ▼         │
│                                                              │
│  Action    #      Title                                      │
│  Do now    2341   Add Qwen3MoE fused MoE tests              │
│  Inspect   2298   Tokenizer cache growth on long prompts    │
│  Defer     2187   DeepSeek V4 routing needs H20 cluster     │
│                                                              │
│  推荐动作: Do now — strong fit + resources OK                │
│  涉及模型适配，你有 SGLang 经验，资源允许先做本地验证。       │
└──────────────────────────────────────────────────────────────┘
```

## Why

Most large open source projects are hard to enter — the roadmap is dense, every issue assumes context you don't have yet, and it's unclear which PRs are worth reading to build that context.

osmind solves this by:
- **Matching issues to your profile and resources** — it knows your skills, interests, GPU/time constraints, and surfaces the issues you're most likely to be able to act on
- **Routing work through durable Contribution Packets** — selected issues and PRs become Markdown files with context, recommendation evidence, continue/stop criteria, key files, validation hints, and suggested next actions for people or agents
- **Grounding packets in your local checkout** — when a watched repo has a local `path`, packets include likely source/test files and repo-derived first steps before you hand the work to an agent
- **Building a knowledge base** — packs accumulate in your Obsidian vault, linked to repos and modules; over time you build a real mental model of the codebase

## Workflow

1. Create `profile.yaml` with `osmind init`.
2. Run `osmind doctor` to check your profile, output directory, GitHub token, LLM config, and external agent commands.
3. Run `osmind`.
4. Use Discover to inspect the cached opportunity queue, or press `u` to choose between reading cache and fetching fresh GitHub data.
5. Press `Enter` to inspect an issue.
6. Press `Space` and choose Start Work when you want to generate or update the Contribution Packet and mark it Continue.
7. Press `Space` when you want to remove an item from the active queue as Defer or Discard.
8. Press `o` to open the packet in your editor or Obsidian.
9. Use Packs to revisit generated material, then continue in your editor, Codex, Claude, or another agent.

## How it works

osmind has three visible modes:

### Discover

Turns open issues from your watched repos into an opportunity queue. Discover shows the cached queue when it exists; press `u` to choose `Read Cache` or `Fetch + Rank`. If there is no cache for the selected repo, `u` fetches from GitHub directly. Each issue is scored by a local or remote LLM. The list leads with the recommended action and the reason, so a topic can be highly relevant but still be deferred if your configured GPUs or time budget make it hard to reproduce.

The default Discover queue is `Active`: issues you have not deferred or discarded, plus previously deferred/discarded issues whose upstream content or configured resources changed. The status line shows how many issues are visible, which action filter is active, when the repo was last fetched, when issues were last ranked, how many are still unranked, how many already have packets, and how many items are deferred, discarded, or changed. Use the action-filter dropdown to switch between `Active`, `Do now`, `Inspect`, `Rec Defer`, `Skip`, `Packeted`, `Deferred`, `Discarded`, `Changed`, and `All`.

The table keeps the top-level queue scannable: `Action`, issue number, and title are the primary columns. The selected row summary and detail panes carry the deeper `why`, resource fit, evidence, and original source text.

Open an issue detail view to see the recommendation and source evidence side by side. The left `Analysis` pane starts with a structured decision panel: `Recommendation`, `Decision Factors`, and `Evidence` show the action, reason tag, next step, priority, fit, resource fit, actionability, configured resources, and source signals before the continue/stop criteria. The right `Source` pane contains a Chinese `Issue Brief` with `Why It May Fit You`, `Risks And Missing Evidence`, `First 30 Minutes`, `Validation Path`, and `Agent Prompt`, followed by the original issue text and comments. Press `Tab` to switch panes. Press `Space` to choose Start Work, Defer, or Discard; Start Work generates or updates the Contribution Packet, marks it Continue, and opens the Start Work panel. Defer and Discard write the decision to the packet frontmatter, append it to the Decision Log, record the current resource profile, and update the local index. Deferred and discarded issues leave the Active queue until GitHub updates the issue or your `resources` config changes.

### Packs

Lists generated Contribution Packets from the local SQLite cache. You can inspect their status, decision, and confidence. Press `Enter` to read a packet inside the TUI with a section list and rendered Markdown, `Space` to open a small Defer/Discard menu, or `o` to open the Markdown file externally. Issue packets include the same `Recommendation Snapshot` table that Discover shows, plus the structured brief sections and saved agent prompt when a brief is available, so the Markdown file keeps the action, resource fit, configured resources, first validation path, and evidence that led to the decision.

### Settings

Shows the effective runtime health of the local setup: GitHub token presence, LLM endpoint and model, output directory, cache path, configured resources, watched repos, and whether the external agent commands are on `PATH`.

## Installation

Requires Python 3.11+.

```bash
git clone https://github.com/yourname/osmind
cd osmind
pip install -e .
```

## Quick Start

Create a profile, check your local setup, then launch the TUI:

```bash
osmind init
osmind doctor
osmind
```

In Discover, press `u` to load or fetch opportunities, `Enter` to view the issue brief and original text, and `Space` → Start Work when you are ready to generate a Contribution Packet.

## Configuration

```bash
osmind init
```

You can also copy `profile.yaml.example` and edit it manually:

```yaml
interests:
  - RL post-training
  - SGLang inference optimization

skills:
  - Python
  - distributed training

resources:
  gpus: "4x RTX 4090"
  time: part-time

watching:
  - repo: THUDM/slime
    path: ~/workspace/slime        # optional local checkout for repo-grounded packets
    issue_limit: 100               # optional; defaults to 30
  - repo: sgl-project/sglang
    path: ~/workspace/sglang

output_dir: ~/workspace/osmind-packets  # where packets, cache, and logs are written

llm:
  base_url: http://localhost:30000/v1  # SGLang local endpoint, or any OpenAI-compatible API
  model: Qwen3.5-27B
  api_key: placeholder

external_agents:
  claude_code: claude
  codex: codex
```

Existing configs that use `notes_vault` still work; new configs should prefer `output_dir`.

`resources` is part of recommendation scoring. For example, if an issue matches your interests but likely requires a much larger GPU setup than `4x RTX 4090`, osmind should mark resource fit as blocked or risky and lower the priority.

`watching[].path` is optional. When it points at a local checkout, Start Work packets include repo-grounded matches, likely source/test files, and first steps based on what osmind found in that checkout. Without a local path, osmind still works from GitHub issue metadata and generated briefs.

`watching[].issue_limit` is optional and controls how many open issues osmind fetches from GitHub for that repo before ranking. It defaults to `30`.

Set your GitHub token:

```bash
export GITHUB_TOKEN=ghp_...
```

Run:

```bash
osmind
```

## Logs

Runtime errors shown in the TUI are also written with traceback details to:

```text
<output_dir>/osmind/.cache/osmind.log
```

## LLM backend

osmind uses any **OpenAI-compatible** API for issue ranking and issue brief generation. Point `llm.base_url` at whatever you're running:

| Backend | `base_url` |
|---------|-----------|
| SGLang (local) | `http://localhost:30000/v1` |
| OpenAI | `https://api.openai.com/v1` |
| Ollama | `http://localhost:11434/v1` |
| Any other compatible server | your endpoint |

For ranking and brief generation, a 7B–27B local model is sufficient.

## Keybindings

| Key | Action |
|-----|--------|
| `d` | Discover tab |
| `p` | Packs tab |
| `t` | Settings tab |
| `u` | Update the Discover queue from cache or GitHub |
| `Enter` | Inspect selected issue in Discover, or read selected packet in Packs |
| `Tab` | Switch between Analysis and Source panes in issue detail (Discover) |
| `Esc` / `q` | Return from detail, packet reader, or Start Work views |
| `Space` | Decide selected issue (Start Work, Defer, Discard) or selected packet (Defer, Discard) |
| `o` | Open Contribution Packet for selected issue or selected packet |
| `Ctrl+Q` | Quit |

## Tech stack

- [Textual](https://github.com/Textualize/textual) — terminal UI framework
- [PyGithub](https://github.com/PyGithub/PyGithub) — GitHub API
- [openai](https://github.com/openai/openai-python) — LLM client (OpenAI-compatible)
- Contribution Packets stored as plain Markdown with YAML frontmatter — no new tools required if you already use Obsidian
