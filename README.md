# osmind

A TUI for open source contributors. Discover issues that fit your skills, learn from PRs with Socratic guidance, and accumulate notes in your Obsidian vault.

## Setup

```bash
pip install -e ".[dev]"
cp profile.yaml.example profile.yaml
# edit profile.yaml
export GITHUB_TOKEN=your_token
osmind
```

## Keybindings

| Key | Action |
|-----|--------|
| `d` | Discover tab |
| `l` | Learn tab |
| `r` | Review tab |
| `f` | Fetch issues (Discover) |
| `c` | Launch Claude Code on selected issue |
| `x` | Launch Codex on selected issue |
| `Ctrl+S` | Save note (Learn) |
| `q` | Quit |
