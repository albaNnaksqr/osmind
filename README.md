# osmind

**osmind** is a local-first Contribution Packet generator for developers who want to understand and contribute to open-source projects.

It watches GitHub repositories you care about, recommends PRs and issues that match your interests, and turns selected items into Markdown Contribution Packets. Each packet gives you recommendation evidence, continue/stop criteria, a first inspection path, key files, validation hints, and an optional Codex or Claude prompt.

```
┌─ osmind ─────────────────────────────────────────────────────┐
│ [Discover]  [Packs]  [Review]                   Ctrl+Q: Quit │
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
3. Use Discover to review the cached opportunity queue, or press `u` to choose between reading cache and fetching fresh GitHub data.
4. Press `Enter` to inspect an issue, then press `w` when you want to start work; osmind generates or updates the Contribution Packet and marks it Continue.
5. Press `Space` when you want to remove an item from the active queue as Defer or Discard.
6. Press `o` to open the packet in your editor or Obsidian.
7. Read the pack alongside GitHub or a local checkout.
8. Use Packs and Review to revisit generated material.

## How it works

osmind has four modes:

### Discover

Turns open issues from your watched repos into an opportunity queue. Discover shows the cached queue when it exists; press `u` to choose `Read Cache` or `Fetch + Rank`. If there is no cache for the selected repo, `u` fetches from GitHub directly. Each issue is scored by a local or remote LLM. The list leads with the recommended action and the reason, so a topic can be highly relevant but still be deferred if your configured GPUs or time budget make it hard to reproduce.

The default Discover queue is `Active`: issues you have not deferred or discarded, plus previously deferred/discarded issues whose upstream content or configured resources changed. The status line shows how many issues are visible, which action filter is active, when the repo was last fetched, when issues were last ranked, how many are still unranked, how many already have packets, and how many items are deferred, discarded, or changed. Press `a` to cycle the visible queue through `Active`, `Do now`, `Review`, `Rec Defer`, `Skip`, `Packeted`, `Deferred`, `Discarded`, `Changed`, and `All`.

Open an issue detail view to see the recommendation and source evidence side by side. The left `Analysis` pane starts with a structured decision panel: `Recommendation`, `Decision Factors`, and `Evidence` show the action, reason tag, next step, priority, fit, resource fit, actionability, configured resources, and source signals before the continue/stop criteria. The right `Source` pane contains a Chinese `Issue Brief` with `Why It May Fit You`, `Risks And Missing Evidence`, `First 30 Minutes`, `Validation Path`, and `Agent Prompt`, followed by the original issue text and comments. Press `Tab` to switch panes. Press `w` to generate or update the Contribution Packet, mark it Continue, and open the Start Work panel. Press `Space` to choose Defer or Discard; osmind writes the decision to the packet frontmatter, appends it to the Decision Log, records the current resource profile, and updates the local index. Deferred and discarded issues leave the Active queue until GitHub updates the issue or your `resources` config changes. Press `o` to open an existing packet for the selected issue.

### Packs

Lists generated Contribution Packets from the local SQLite cache. You can inspect their status, decision, and confidence, then use the same decision model as Discover: `w` marks Continue and opens Start Work; `Space` opens a small Defer/Discard menu. Issue packets include the same `Recommendation Snapshot` table that Discover shows, plus the structured brief sections and saved agent prompt when a brief is available, so the Markdown file keeps the action, resource fit, configured resources, first validation path, and evidence that led to the decision. Press `Enter` to read a packet inside the TUI with a section list and rendered Markdown, or `o` to open the Markdown file externally.

### Review

osmind reads generated Contribution Packets and asks Socratic review questions. Your answers are appended back into the packet's `## Notes` section so the Markdown file remains the durable learning record. The right pane lists saved Review Q/A entries for the selected packet; press `v` to focus that list, `Delete` to remove the selected answer, or `e` to load the selected answer into the input for rewriting.

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
| `u` | Load cached opportunities or fetch from GitHub and rank again (Discover) |
| `a` | Cycle the Discover action filter |
| `Enter` | Inspect selected issue in Discover, or read selected packet in Packs |
| `Tab` | Switch between Analysis and Source panes in issue detail (Discover) |
| `Esc` / `q` | Return from detail, packet reader, or Start Work views |
| `Space` | Decide Defer or Discard for selected issue or packet |
| `w` | Start Work; generates or updates the packet and marks Continue |
| `o` | Open Contribution Packet for selected issue or selected packet |
| `v` | Focus saved Review answers for the selected packet (Review) |
| `e` | Rewrite the selected saved Review answer (Review) |
| `Delete` | Remove the selected saved Review answer, or the latest answer when no answer row is selected (Review) |
| `Ctrl+Q` | Quit |

## Tech stack

- [Textual](https://github.com/Textualize/textual) — terminal UI framework
- [PyGithub](https://github.com/PyGithub/PyGithub) — GitHub API
- [openai](https://github.com/openai/openai-python) — LLM client (OpenAI-compatible)
- Contribution Packets stored as plain Markdown with YAML frontmatter — no new tools required if you already use Obsidian
