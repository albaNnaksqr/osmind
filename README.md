# osmind

**osmind** is a local-first Contribution Packet generator for developers who want to understand and contribute to open-source projects.

It watches GitHub repositories you care about, recommends PRs and issues that match your interests, and turns selected items into Markdown Contribution Packets. Each packet gives you recommendation evidence, continue/stop criteria, a first inspection path, key files, validation hints, and an optional Codex or Claude prompt.

```
┌─ osmind ─────────────────────────────────────────────────────┐
│ [Discover]  [Packs]  [Review]                      q: Quit   │
├──────────────────────────────────────────────────────────────┤
│ Repo: sgl-project/sglang              Filter: all  ▼         │
│                                                              │
│  ★★★  #2341  Add Qwen3MoE model support            [feat]   │
│  ★★☆  #2298  Tokenizer memory leak on long seqs    [bug]    │
│  ★☆☆  #2187  Refactor engine batch scheduler       [refac]  │
│                                                              │
│  推荐理由: 涉及模型适配，你有 SGLang PR 经验，改动主要在     │
│  model/ 目录，预估 200 行                                    │
└──────────────────────────────────────────────────────────────┘
```

## Why

Most large open source projects are hard to enter — the roadmap is dense, every issue assumes context you don't have yet, and it's unclear which PRs are worth reading to build that context.

osmind solves this by:
- **Matching issues to your profile** — it knows your skills and interests, scores every open issue, and surfaces the ones you're most likely to be able to work on
- **Generating durable Contribution Packets** — selected issues and PRs become Markdown files with context, recommendation evidence, continue/stop criteria, key files, validation hints, and suggested next actions
- **Building a knowledge base** — packs accumulate in your Obsidian vault, linked to repos and modules; over time you build a real mental model of the codebase

## Workflow

1. Configure watched repositories in `profile.yaml`.
2. Run `osmind`.
3. Use Discover to refresh issues and choose an item.
4. Press `g` to generate a Contribution Packet.
5. Press `o` to open the packet in your editor or Obsidian.
6. Read the pack alongside GitHub or a local checkout.
7. Use Packs and Review to revisit generated material.

## How it works

osmind has three modes:

### Discover

Fetches open issues from your watched repos. Each issue is scored against your `profile.yaml` (interests, skills, available compute) by a local or remote LLM. Results are sorted by match score with a one-sentence explanation of why each issue fits you.

Press `g` on an issue to generate a Contribution Packet, or `o` to open an existing packet for the selected issue. Press `c` or `x` to launch **Claude Code** or **Codex** directly with the issue context pre-loaded.

### Packs

Lists generated Contribution Packets from the local SQLite cache. You can open packets, inspect their status, decision, and confidence, and regenerate material when the source item changes.

### Review

osmind reads generated Contribution Packets and asks Socratic review questions. Your answers are appended back into the packet's `## Notes` section so the Markdown file remains the durable learning record.

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
| `f` | Fetch issues (Discover) |
| `g` | Generate Contribution Packet for selected issue (Discover) |
| `o` | Open Contribution Packet for selected issue or selected packet |
| `c` | Launch Claude Code on selected issue |
| `x` | Launch Codex on selected issue |
| `q` | Quit |

## Tech stack

- [Textual](https://github.com/Textualize/textual) — terminal UI framework
- [PyGithub](https://github.com/PyGithub/PyGithub) — GitHub API
- [openai](https://github.com/openai/openai-python) — LLM client (OpenAI-compatible)
- Contribution Packets stored as plain Markdown with YAML frontmatter — no new tools required if you already use Obsidian
