# osmind

**osmind** is a local-first Contribution Packet generator for developers who want to understand and contribute to open-source projects.

It watches GitHub repositories you care about, recommends PRs and issues that match your interests, and turns selected items into Markdown Contribution Packets. Each packet gives you recommendation evidence, continue/stop criteria, a first inspection path, key files, validation hints, and an optional Codex or Claude prompt.

```
┌─ osmind ─────────────────────────────────────────────────────┐
│ [Discover]  [Packs]  [Review]                      q: Quit   │
├──────────────────────────────────────────────────────────────┤
│ Repo: sgl-project/sglang              Filter: all  ▼         │
│                                                              │
│  Action  Why                         #      Title            │
│  Do now  strong fit + resources OK   #2341  Add Qwen3MoE... │
│  Defer   resource risk               #2298  Tokenizer leak  │
│  Defer   resource blocked            #2187  DeepSeek V4...  │
│                                                              │
│  推荐动作: Do now — strong fit + resources OK                │
│  涉及模型适配，你有 SGLang 经验，资源允许先做本地验证。       │
└──────────────────────────────────────────────────────────────┘
```

## Why

Most large open source projects are hard to enter — the roadmap is dense, every issue assumes context you don't have yet, and it's unclear which PRs are worth reading to build that context.

osmind solves this by:
- **Matching issues to your profile and resources** — it knows your skills, interests, GPU/time constraints, and surfaces the issues you're most likely to be able to act on
- **Generating durable Contribution Packets** — selected issues and PRs become Markdown files with context, recommendation evidence, continue/stop criteria, key files, validation hints, and suggested next actions
- **Building a knowledge base** — packs accumulate in your Obsidian vault, linked to repos and modules; over time you build a real mental model of the codebase

## Workflow

1. Configure watched repositories in `profile.yaml`.
2. Run `osmind`.
3. Use Discover to open your opportunity queue, update from GitHub, or re-rank with your current profile.
4. Press `g` to generate a Contribution Packet.
5. Press `o` to open the packet in your editor or Obsidian.
6. Press `y`, `l`, or `n` to mark Continue, Defer, or Discard.
7. Read the pack alongside GitHub or a local checkout.
8. Use Packs and Review to revisit generated material.

## How it works

osmind has four modes:

### Discover

Turns open issues from your watched repos into an opportunity queue. Press `f` to open the current queue, `u` to update from GitHub and rank again, and `s` to re-rank with your current `profile.yaml` without calling GitHub. Each issue is scored by a local or remote LLM. The list leads with the recommended action and the reason, so a topic can be highly relevant but still be deferred if your configured GPUs or time budget make it hard to reproduce.

The default Discover queue is `Active`: issues you have not deferred or discarded, plus previously deferred/discarded issues whose upstream content or configured resources changed. The status line shows how many issues are visible, which action filter is active, when the repo was last fetched, when issues were last ranked, how many are still unranked, how many already have packets, and how many items are deferred, discarded, or changed. Press `a` to cycle the visible queue through `Active`, `Do now`, `Review`, `Rec Defer`, `Skip`, `Packeted`, `Deferred`, `Discarded`, `Changed`, and `All`.

Open an issue detail view to see the recommendation and source evidence side by side. The left `Analysis` pane keeps the recommended action, resource explanation, next step, and continue/stop criteria visible; the right `Source` pane contains the Chinese summary, original issue text, and comments. Press `Tab` to switch panes. Press `g` on an issue to generate a Contribution Packet, or `o` to open an existing packet for the selected issue. Press `y`, `l`, or `n` to mark the selected issue as Continue, Defer, or Discard; osmind writes the decision to the packet frontmatter, appends it to the Decision Log, records the current resource profile, and updates the local index. Deferred and discarded issues leave the Active queue until GitHub updates the issue or your `resources` config changes. Press `c` or `x` to launch **Claude Code** or **Codex** directly with the issue context pre-loaded.

### Packs

Lists generated Contribution Packets from the local SQLite cache. You can open packets, inspect their status, decision, and confidence, mark Continue/Defer/Discard decisions, and regenerate material when the source item changes.

### Review

osmind reads generated Contribution Packets and asks Socratic review questions. Your answers are appended back into the packet's `## Notes` section so the Markdown file remains the durable learning record. In Review, press `Delete` to remove the most recent saved Review answer from the current or selected packet.

### Settings

Shows the effective runtime health of the local setup: GitHub token presence, LLM endpoint and model, notes vault, cache path, configured resources, watched repos, and whether the external agent commands are on `PATH`.

## Installation

Requires Python 3.11+.

```bash
git clone https://github.com/yourname/osmind
cd osmind
pip install -e .
```

## Configuration

```bash
cp profile.yaml.example profile.yaml
```

Edit `profile.yaml`:

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
  - repo: sgl-project/sglang

notes_vault: ~/workspace/Note  # your Obsidian vault path

llm:
  base_url: http://localhost:30000/v1  # SGLang local endpoint, or any OpenAI-compatible API
  model: Qwen3.5-27B
  api_key: placeholder

external_agents:
  claude_code: claude
  codex: codex
```

`resources` is part of recommendation scoring. For example, if an issue matches your interests but likely requires a much larger GPU setup than `4x RTX 4090`, osmind should mark resource fit as blocked or risky and lower the priority.

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
<notes_vault>/osmind/.cache/osmind.log
```

## LLM backend

osmind uses any **OpenAI-compatible** API for issue ranking and Socratic questions. Point `llm.base_url` at whatever you're running:

| Backend | `base_url` |
|---------|-----------|
| SGLang (local) | `http://localhost:30000/v1` |
| OpenAI | `https://api.openai.com/v1` |
| Ollama | `http://localhost:11434/v1` |
| Any other compatible server | your endpoint |

For the ranking and Socratic use case, a 7B–27B local model is sufficient.

## Keybindings

| Key | Action |
|-----|--------|
| `d` | Discover tab |
| `p` | Packs tab |
| `r` | Review tab |
| `t` | Settings tab |
| `f` | Open the current opportunity queue, fetching only if nothing is loaded yet (Discover) |
| `u` | Update from GitHub and rank again (Discover) |
| `s` | Re-rank with the current profile without calling GitHub (Discover) |
| `a` | Cycle the Discover action filter |
| `Tab` | Switch between Analysis and Source panes in issue detail (Discover) |
| `g` | Generate Contribution Packet for selected issue (Discover) |
| `o` | Open Contribution Packet for selected issue or selected packet |
| `y` | Mark selected issue or packet as Continue |
| `l` | Mark selected issue or packet as Defer |
| `n` | Mark selected issue or packet as Discard |
| `Delete` | Remove the most recent saved Review answer from the current or selected packet (Review) |
| `c` | Launch Claude Code on selected issue |
| `x` | Launch Codex on selected issue |
| `q` | Quit |

## Tech stack

- [Textual](https://github.com/Textualize/textual) — terminal UI framework
- [PyGithub](https://github.com/PyGithub/PyGithub) — GitHub API
- [openai](https://github.com/openai/openai-python) — LLM client (OpenAI-compatible)
- Contribution Packets stored as plain Markdown with YAML frontmatter — no new tools required if you already use Obsidian
