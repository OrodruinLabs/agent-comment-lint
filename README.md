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
ticket or plan they were working from. The restatement drifts from the code, and the pointer rots when the document
moves.

agent-comment-lint holds every comment to one line, with no ticket or plan references. In Claude Code it blocks the
write before the comment lands and shows the agent why, so the agent can rewrite it. The same check runs in CI, in
pre-commit and from the command line.

```
src/a.ts:12: C1: 3-line prose block (limit 1)
src/a.ts:40: C3: governance reference 'ADR-0009'
agent-comment-lint: 2 violation(s) in 1 of 57 file(s) scanned.
```

## What it checks

| Rule | Fails when |
| --- | --- |
| C1 | A comment has more than one line of prose. Consecutive `//` or `#` lines, a multi-line `/* */` and a Python docstring each count as one comment. One-line tags such as `@param` do not count. |
| C3 | A comment names a ticket, pull request, decision record, plan or doc path, such as `ADR-9`, `PR 519`, `work item 1234`, `docs/x.md` or `CLAUDE.md`. |
| C5 | An assertion message built with `+ "..."` spans more than two lines. |
| C7 | A line that carries a comment is over 120 characters. |

The numbers skip because C2, C4 and C6 need a compiler or human judgment, and this tool does not check them.

## Supported languages

| Language | Extensions | Comments read |
| --- | --- | --- |
| C# | `.cs` | `//`, `///`, `/* */` |
| JavaScript and TypeScript, with JSX | `.js` `.jsx` `.mjs` `.cjs` `.ts` `.tsx` `.mts` `.cts` | `//`, `/* */`, `{/* */}` |
| CSS | `.css` | `/* */` |
| Shell | `.sh` | `#` |
| YAML | `.yml` `.yaml` | `#` |
| HCL and Terraform | `.tf` `.tfvars` `.hcl` | `#`, `//`, `/* */` |
| Python | `.py` | `#`, docstrings |

Other files are skipped, and so are dependency and build folders such as `node_modules`, `dist` and `.venv`.

## Setup

Pick where it runs; every channel runs the same check. The snippets pin `v1.0.0`. Keep a pin, so a new release never
changes your results without a commit of yours.

### Claude Code

```
/plugin marketplace add OrodruinLabs/agent-comment-lint
/plugin install agent-comment-lint@agent-comment-lint
```

Needs `python3` on `PATH`. A write that adds a bad comment is blocked, and Claude sees why. Old comments the write
leaves alone never block it. To turn it on for a whole team, see [Claude Code setup](docs/reference.md#claude-code).

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

Only the lines the pull request changes are checked. Keep `fetch-depth: 0`, or the step cannot see what changed and
fails. The inputs are in [the reference](docs/reference.md#github-actions).

### pre-commit

```yaml
repos:
  - repo: https://github.com/OrodruinLabs/agent-comment-lint
    rev: v1.0.0
    hooks:
      - id: agent-comment-lint
```

This checks each staged file whole, not only its changed lines, so fix or exclude old findings before you turn it on.

### Command line

```
uv tool install git+https://github.com/OrodruinLabs/agent-comment-lint@v1.0.0
pipx install git+https://github.com/OrodruinLabs/agent-comment-lint@v1.0.0
```

```
agent-comment-lint --diff origin/main    # only what the branch changes
agent-comment-lint --all                 # every covered file in the repository
agent-comment-lint --files a.ts b.py     # the named files
```

| Exit code | Meaning |
| --- | --- |
| 0 | Clean. |
| 1 | At least one violation. |
| 2 | Could not scan. Never treated as a pass. |

## Configuration

Optional. Add `.agent-comment-lint.json` at the repository root. Settings can only make the check stricter: there
are no limits to change and no way to silence one comment inline. Every entry states its reason.

| Setting | What it does |
| --- | --- |
| `exclude` | Paths that are never checked, such as vendored or generated code. |
| `governance.packs` | Turns on reference packs, below. |
| `governance.extra` | Adds your own reference patterns, as regular expressions. |

```json
{
  "exclude": [{ "path": "vendor/", "reason": "third-party code" }],
  "governance": {
    "packs": ["azure-boards"],
    "extra": [{ "pattern": "\\bWEB-\\d+", "reason": "the web team's ticket ids" }]
  }
}
```

### Reference packs

C3 always refuses the common shapes shown in [What it checks](#what-it-checks). A pack adds the reference shapes of
one tracker or convention. Packs are off by default because the same shapes mean other things in many codebases, so
turn on only the ones your team uses.

| Pack | Turn it on if you use | It refuses |
| --- | --- | --- |
| `azure-boards` | Azure Boards | `AB#4321`, `ADO #795`, `ADO 795` |
| `decision-ids` | numbered decisions | `D-7`, `D-12b`, `D7` |
| `task-ids` | task ids shaped prefix, dash, letter, number | `WEB-T022`, `AUTH-F053` |

## Documentation

[The reference](docs/reference.md) has everything else:
- every reference shape C3 refuses
- each mode and exit code
- team setup for Claude Code
- what each language's lexer can and cannot tell apart
- the known false positives

## License

MIT. See [LICENSE](LICENSE).
