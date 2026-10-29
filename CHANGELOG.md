# Changelog

## 1.6.0

- Three more languages are read: Go (`.go`), Java (`.java`) and Rust (`.rs`). Go keeps backtick raw strings and runes
  as content and treats directives such as `//go:build` and `//nolint:x` as code, judging a `// reason` after one as a
  trailing comment. Java reads text blocks. Rust nests block comments and reads raw, byte and C strings, and tells
  lifetimes and labels from character literals. A block comment, string or raw string that never closes is exit code 2.
- Multi-line doc comments (Javadoc, Rust `///` and `//!`, Go package comments) are C1 blocks in these files, as
  docstrings and JSDoc are.
- Both `.pre-commit-hooks.yaml` ids match the new files.
- Findings move only for files of these languages, which were skipped before. Nothing moves for any other file.
- The language icons in the README now render on PyPI.

## 1.5.0

- Four more languages are read: Ruby (`.rb`, `.rake`, `.gemspec`, and the names `Gemfile` and `Rakefile`), TOML
  (`.toml`), Dockerfile (`Dockerfile`, `Containerfile` and `.dockerfile`) and Makefile (`Makefile`, `makefile`,
  `GNUmakefile` and `.mk`). Ruby follows heredocs and `=begin` / `=end` blocks, TOML follows multi-line strings,
  Dockerfile reads parser directives and follows heredocs, and Makefile reads recipes as shell and `define` blocks as
  content. A heredoc, `=begin` block, TOML multi-line string, `define`, make reference or recipe quote that never
  closes is exit code 2.
- Both `.pre-commit-hooks.yaml` ids match the new files.
- Findings move only for files of these languages, which were skipped before. Nothing moves for any other file.

## 1.4.0

- `--hook --agent NAME`: the write-time hook can read the event of another coding agent. `--agent` takes `claude`
  (the default, unchanged), `codex`, `windsurf` or `gemini`, and is a usage error without `--hook`. The three
  adapters are built from each agent's documentation and are not yet verified live: no agent has been seen blocking
  a write. Copilot, Cursor, Kiro and Antigravity have no adapter, because their payloads are undocumented.
- Guard and capture scripts: `integrations/guard/` turns a missing command or any failure into exit 2, and
  `integrations/capture/` records an agent's events to `AGENT_COMMENT_LINT_CAPTURE` so a new adapter can be built.
- `PATCH_NOT_APPLIED`: a Codex patch or a Windsurf or Gemini edit that does not apply to the file on disk is blocked
  with "the edit does not apply exactly to the file on disk, so it cannot be judged". So is a Codex patch that
  releases before 0.162.0 would write differently from later ones.
- No finding moves.

## 1.3.0

- End-of-session check: a new check at Stop, in the plugin only. A snapshot taken at session start lets it judge only
  the uncommitted lines changed since the session started, so switching branches, pulls, rebases and resets during
  the session bring in no old line, nor does a merge, rebase or cherry-pick stopped on a conflict. Lines the session
  commits are left to pre-commit and CI. Known limits: edits a human makes during the session, a session resumed
  days later, two sessions in one checkout, generated files a build changes, and lines brought in uncommitted by
  `git checkout <rev> -- <path>`, `git restore --source`, `git merge --squash`, `git cherry-pick -n`,
  `git stash pop`, or by `git am` or `git revert` stopped on a conflict or `git revert -n`. No finding in any other
  mode moves.
- `--staged` and `agent-comment-lint-staged`: `--staged` judges only the lines staged for the next commit, read from
  the index, so a partly staged file is judged as it will be committed. The new pre-commit id
  `agent-comment-lint-staged` runs it. The existing `agent-comment-lint` id is unchanged, so no verdict moves.
- Session-start guidance: the plugin adds two lines of comment guidance at session start. Moves no finding.
- Committed settings: the hook and the end-of-session check read the settings file as committed at HEAD, so an
  exclusion an agent adds to the file does not excuse the write that prompted it. Moves findings in hook mode only,
  where a new or edited settings file is not yet committed. Outside git, before the first commit, and with
  `--config`, the file on disk is still read.

## 1.2.0

- Platforms: runs on macOS, Linux and native Windows, with CI on all three. The hook wrapper looks for Python as
  `AGENT_COMMENT_LINT_PYTHON`, then `python3`, `python` and `py -3`, and takes the first that is 3.9 or newer.
  On Windows, the root containment check compares paths without regard to case. Moves nothing in the findings.
- Hook, changed lines: before the diff, the hook trims the lines both versions share, so a small edit to a large
  file of repeated lines no longer comes back as a wide changed range, and old findings inside that wrong range no
  longer block a clean write. A one-line edit to a 50,000-line file is judged well under a second. Moves findings
  of every rule (C1, C3, C5, C7) in every language, in hook mode only, and rarely. `--diff`, `--all` and `--files`
  are unchanged.
- Hook, teaching message: a blocked write quotes the offending comment, with the lines numbered as the engine
  numbers them, and gives one Fix line per rule. It says that splitting a comment across blank lines, writing the
  file another way, or excluding the path is not a fix, and a blocked Write is told to re-send only the comment
  lines. Moves no finding.
- C3: the opt-in `agent-context` pack flags `Task 8`, `step 3 of the plan`, `per the spec`, `per the review`,
  `as requested`, `as discussed`, `as agreed`, `the user asked`, `the user requested` and an upper-case notes file
  such as `PLAN.md`. Off unless a settings file names it, so no existing finding moves.
- GitHub Action: findings appear as inline annotations on the changed lines, and the job summary lists all of them.
  GitHub shows at most 10 annotations per step. Moves no finding.
- Settings: the settings file accepts `$schema`, and the repository publishes
  `schema/agent-comment-lint.schema.json` for editor completion. Moves no finding.
- PyPI: releases publish to PyPI through trusted publishing, so `uv tool install agent-comment-lint==1.2.0` and
  `pipx install agent-comment-lint==1.2.0` work.

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
