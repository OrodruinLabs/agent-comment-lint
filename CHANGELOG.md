# Changelog

## 1.1.0

- C1 no longer counts a comment line that holds no letter or digit in any script, such as a ruler like `// ----`,
  `// ════`, `#####` or `//////`. Such a line does not end the block either, so a title framed by rulers is one
  line of prose. Moves C1 only, in every language: findings only disappear, and a C1 finding that remains reports
  the span and count of its prose lines only. A `/* ==== */` block with two prose lines between its rulers is now
  `2-3: 2-line`, not `1-4: 4-line`.

## 1.0.0

First public release.

- Rules C1 (one prose line per comment block), C3 (no governance references), C5 (assertion messages of at most two
  lines) and C7 (commented lines of at most 120 characters).
- Languages: C#, JavaScript, TypeScript, JSX, CSS, shell, YAML, HCL and Python.
- Modes `--diff`, `--all`, `--files`, `--stdin-path` and `--hook`, with `--json`, `--root`, `--config` and `--version`.
- Settings: path exclusions, governance packs (`azure-boards`, `decision-ids`, `task-ids`) and extra patterns.
- Channels: command line, pre-commit hook, GitHub Action, Claude Code plugin.
