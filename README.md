<h1 align="center">agent-comment-lint</h1>

<p align="center"><em>Stops AI coding agents from bloating your code comments.</em></p>

<p align="center">
  <a href="https://github.com/OrodruinLabs/agent-comment-lint/actions/workflows/ci.yml"><img src="https://github.com/OrodruinLabs/agent-comment-lint/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT" /></a>
  <img src="https://img.shields.io/badge/python-3.9%E2%80%933.13-3776AB" alt="Python 3.9 to 3.13" />
  <img src="https://img.shields.io/badge/dependencies-none-brightgreen" alt="No dependencies" />
  <img src="https://img.shields.io/badge/Claude_Code-Plugin-7c3aed" alt="Claude Code plugin" />
</p>

---

AI coding agents comment the way they chat: three lines restating what the next line does, and a pointer to the
ticket, plan or decision record they were working from. The restatement drifts from the code, and the pointer rots as
soon as the document moves.

agent-comment-lint holds every comment to one line of prose, with no ticket or plan references and no line over 120
characters. In Claude Code it blocks the write before the comment lands and shows the agent the report, so the agent
can rewrite the comment and try again. The same engine gates your commits and pull requests.

```
src/a.ts:12: C1: 3-line prose block (limit 1)
src/a.ts:40: C3: governance reference 'ADR-0009'
agent-comment-lint: 2 violation(s) in 1 of 57 file(s) scanned.
```

## Why agent-comment-lint?

- **Stops bloat at write time.** The Claude Code plugin blocks a `Write` or `Edit` that adds a bad comment, so it
  never reaches your diff.
- **One verdict everywhere.** The command line, pre-commit, GitHub Actions and the plugin all run the same engine.
- **Judges only what changed.** `--diff` and the plugin report only findings on lines you add or change, so an existing
  codebase can adopt it today.
- **Fails closed.** A file it cannot scan is exit code 2, never a silent pass.
- **Nothing to loosen.** No configurable limits and no inline suppression. Settings can only exclude paths or add
  references to refuse.
- **Zero dependencies.** Python 3.9 or newer, standard library only. It runs from a plain checkout.

## Install

Pin a tag in every channel, so that a new release never changes your verdicts without a commit of yours.

### Command line

```
uv tool install git+https://github.com/OrodruinLabs/agent-comment-lint@v1.0.0
pipx install git+https://github.com/OrodruinLabs/agent-comment-lint@v1.0.0
```

### pre-commit or prek

```yaml
repos:
  - repo: https://github.com/OrodruinLabs/agent-comment-lint
    rev: v1.0.0
    hooks:
      - id: agent-comment-lint
```

The hook judges the whole of each staged file, not only its changed lines. A repository with old findings fixes them,
or excludes their paths, before it turns the hook on.

### GitHub Actions

```yaml
on: pull_request
jobs:
  comments:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: OrodruinLabs/agent-comment-lint@v1.0.0
```

`mode` is `diff` (the default: the lines the pull request changes) or `all`. `base` overrides the ref `--diff`
compares against, and `args` passes more flags, such as `--config`. Without `fetch-depth: 0` the merge base is
missing and the step exits 2.

### Claude Code plugin

```
/plugin marketplace add OrodruinLabs/agent-comment-lint
/plugin install agent-comment-lint@agent-comment-lint
```

On Claude Code 2.1.275 or later one line does both: `/plugin install agent-comment-lint --marketplace OrodruinLabs/agent-comment-lint`.

The plugin registers a PreToolUse hook on `Write`, `Edit` and `MultiEdit`. It needs `python3` on `PATH`, or the
interpreter named by `AGENT_COMMENT_LINT_PYTHON`. A write that adds a finding is blocked, and Claude sees the report.
Writes that only keep old findings go through.

To offer the plugin to everyone who opens a repository, commit this to its `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "agent-comment-lint": { "source": { "source": "github", "repo": "OrodruinLabs/agent-comment-lint" } }
  },
  "enabledPlugins": { "agent-comment-lint@agent-comment-lint": true }
}
```

Without the plugin, an installed command does the same job. Register this command as the PreToolUse hook. The guard
turns a missing command into exit 2, because Claude Code lets a write through on any other failure:

```
command -v agent-comment-lint >/dev/null || { echo "Blocked: agent-comment-lint is not installed" >&2; exit 2; }; agent-comment-lint --hook
```

Enable either the plugin or the command, not both, or every write is judged twice.

## Quick start

```
agent-comment-lint --diff origin/main    # only what the branch changes
agent-comment-lint --all                 # every covered file in the repository
agent-comment-lint --files a.ts b.py     # the named files
```

Exit code 0 is clean, 1 is at least one violation, and 2 means it could not scan. `--json` prints one JSON document
instead of text. Without an install, `python3 check-agent-comment-lint.py` from a checkout takes the same arguments.

Covered: C#, JavaScript, TypeScript (with JSX), CSS, shell, YAML, HCL and Python.

## The rules

| Rule | In plain words |
| --- | --- |
| C1 | A comment block holds at most one line of prose. Consecutive `//`, `///` or `#` lines are one block, and so are a multi-line `/* */` comment and a Python docstring. A complete one-line tag such as `@param ...` does not count. |
| C3 | No comment names a ticket, pull request, decision record, plan or doc path: `ADR-9`, `PR 519`, `work item 1234`, `docs/x.md`, `CLAUDE.md`. |
| C5 | An assertion message concatenated with `+ "..."` covers at most two lines. |
| C7 | A line that carries a comment is at most 120 characters long. |

The numbers skip because C2, C4 and C6 need a compiler or human judgment, and this engine does not check them.

## Per-repository settings

A repository may add `.agent-comment-lint.json` at its root to exclude paths or refuse more references. Every entry
states its reason:

```json
{
  "exclude": [{ "path": "vendor/", "reason": "third-party code" }],
  "governance": {
    "packs": ["azure-boards"],
    "extra": [{ "pattern": "\\bWEB-\\d+", "reason": "the web team's ticket ids" }]
  }
}
```

Settings can only make the rules stricter.

## Documentation

[The reference](docs/reference.md) has the details:
- every rule, and the full list of references C3 refuses
- the modes and exit codes
- the settings file
- what each language's lexer can and cannot tell apart
- the known false positives

## License

MIT. See [LICENSE](LICENSE).
