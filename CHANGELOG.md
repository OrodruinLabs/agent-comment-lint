# Changelog

## 1.0.0

First public release.

- Rules C1 (one prose line per comment block), C3 (no governance references), C5 (assertion messages of at most two
  lines) and C7 (commented lines of at most 120 characters).
- Languages: C#, JavaScript, TypeScript, JSX, CSS, shell, YAML, HCL and Python.
- Modes `--diff`, `--all`, `--files`, `--stdin-path` and `--hook`, with `--json`, `--root`, `--config` and `--version`.
- Settings: path exclusions, governance packs (`azure-boards`, `decision-ids`, `task-ids`) and extra patterns.
- Channels: command line, pre-commit hook, GitHub Action, Claude Code plugin.
