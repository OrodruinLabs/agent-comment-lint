<h1 align="center">agent-comment-lint</h1>

<p align="center"><em>Stops AI coding agents from bloating your code comments.</em></p>

<p align="center">
  <a href="https://github.com/OrodruinLabs/agent-comment-lint/actions/workflows/ci.yml"><img src="https://github.com/OrodruinLabs/agent-comment-lint/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://github.com/OrodruinLabs/agent-comment-lint/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT" /></a>
  <img src="https://img.shields.io/badge/python-3.9%E2%80%933.13-3776AB" alt="Python 3.9 to 3.13" />
  <img src="https://img.shields.io/badge/dependencies-none-brightgreen" alt="No dependencies" />
  <img src="https://img.shields.io/badge/Claude_Code-Plugin-7c3aed" alt="Claude Code plugin" />
</p>

---

AI coding agents comment the way they chat: three lines restating what the next line does, and a pointer to the
ticket or plan they were working from. The restatement drifts from the code, and the pointer rots when the document
moves.

**Your CLAUDE.md asks; this enforces.**

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
| :--- | :--- |
| C1 | A comment has more than one line of prose. Consecutive `//` or `#` lines, a multi-line `/* */` and a Python docstring each count as one comment. One-line tags such as `@param` do not count, and neither do rulers like `// ----` or other lines without a letter or digit. |
| C3 | A comment names a ticket, pull request, decision record, plan or doc path, such as `ADR-9`, `PR 519`, `work item 1234`, `docs/x.md` or `CLAUDE.md`. |
| C5 | An assertion message built with `+ "..."` spans more than two lines. |
| C7 | A line that carries a comment is over 120 characters. |

The numbers skip because C2, C4 and C6 need a compiler or human judgment, and this tool does not check them.

## Supported languages

<div align="center">
<table>
  <tr>
    <td align="center" width="16%"><img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.16.0/icons/csharp/csharp-original.svg" width="32" height="32" alt=""><br><sub>C#</sub></td>
    <td align="center" width="16%"><img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.16.0/icons/javascript/javascript-original.svg" width="32" height="32" alt=""><br><sub>JavaScript</sub></td>
    <td align="center" width="16%"><img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.16.0/icons/typescript/typescript-original.svg" width="32" height="32" alt=""><br><sub>TypeScript</sub></td>
    <td align="center" width="16%"><img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.16.0/icons/css3/css3-original.svg" width="32" height="32" alt=""><br><sub>CSS</sub></td>
    <td align="center" width="16%"><img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.16.0/icons/bash/bash-original.svg" width="32" height="32" alt=""><br><sub>Shell</sub></td>
    <td align="center" width="16%"><img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.16.0/icons/yaml/yaml-original.svg" width="32" height="32" alt=""><br><sub>YAML</sub></td>
  </tr>
  <tr>
    <td align="center" width="16%"><img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.16.0/icons/terraform/terraform-original.svg" width="32" height="32" alt=""><br><sub>Terraform / HCL</sub></td>
    <td align="center" width="16%"><img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.16.0/icons/python/python-original.svg" width="32" height="32" alt=""><br><sub>Python</sub></td>
    <td align="center" width="16%"><img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.16.0/icons/ruby/ruby-original.svg" width="32" height="32" alt=""><br><sub>Ruby</sub></td>
    <td align="center" width="16%"><img src="https://cdn.jsdelivr.net/gh/OrodruinLabs/agent-comment-lint@b0946286fae704dde9abb4a318e1e57c403f5f7f/docs/icons/toml.svg" width="32" height="32" alt=""><br><sub>TOML</sub></td>
    <td align="center" width="16%"><img src="https://cdn.jsdelivr.net/gh/devicons/devicon@v2.16.0/icons/docker/docker-original.svg" width="32" height="32" alt=""><br><sub>Dockerfile</sub></td>
    <td align="center" width="16%"><img src="https://cdn.jsdelivr.net/gh/OrodruinLabs/agent-comment-lint@b0946286fae704dde9abb4a318e1e57c403f5f7f/docs/icons/gnu.svg" width="32" height="32" alt=""><br><sub>Makefile</sub></td>
  </tr>
</table>
</div>

JSX and TSX are included. Other files are skipped, and so are dependency and build folders such as
`node_modules`, `dist` and `.venv`. The extensions and file names each language covers are in
[the reference](https://github.com/OrodruinLabs/agent-comment-lint/blob/main/docs/reference.md#scope).

## Supported agents

<div align="center">
<table>
  <tr>
    <td align="center" width="25%"><img src="https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@1.95.0/icons/claude-color.svg" width="32" height="32" alt=""><br><sub><b>Claude Code</b><br>Supported</sub></td>
    <td align="center" width="25%"><img src="https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@1.95.0/icons/codex-color.svg" width="32" height="32" alt=""><br><sub><b>Codex CLI</b><br>Preview</sub></td>
    <td align="center" width="25%"><img src="https://cdn.jsdelivr.net/gh/OrodruinLabs/agent-comment-lint@b0946286fae704dde9abb4a318e1e57c403f5f7f/docs/icons/windsurf.svg" width="32" height="32" alt=""><br><sub><b>Windsurf / Devin</b><br>Preview</sub></td>
    <td align="center" width="25%"><img src="https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@1.95.0/icons/gemini-color.svg" width="32" height="32" alt=""><br><sub><b>Gemini CLI</b><br>Preview</sub></td>
  </tr>
  <tr>
    <td align="center" width="25%"><img src="https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@1.95.0/icons/copilot-color.svg" width="32" height="32" alt=""><br><sub><b>GitHub Copilot</b><br>Planned</sub></td>
    <td align="center" width="25%"><img src="https://cdn.jsdelivr.net/gh/OrodruinLabs/agent-comment-lint@b0946286fae704dde9abb4a318e1e57c403f5f7f/docs/icons/cursor.svg" width="32" height="32" alt=""><br><sub><b>Cursor</b><br>Planned</sub></td>
    <td align="center" width="25%"><img src="https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@1.95.0/icons/kiro-color.svg" width="32" height="32" alt=""><br><sub><b>Kiro</b><br>Planned</sub></td>
    <td align="center" width="25%"><img src="https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@1.95.0/icons/antigravity-color.svg" width="32" height="32" alt=""><br><sub><b>Antigravity</b><br>Planned</sub></td>
  </tr>
</table>
</div>

**Preview** adapters are built from the agent's hook documentation and have not yet been seen blocking a write live.
**Planned** agents wait for one captured hook event, because their docs do not say what a file write looks like.
The details for each agent are in [the reference](https://github.com/OrodruinLabs/agent-comment-lint/blob/main/docs/reference.md#other-coding-agents).

## Setup

Pick where it runs; every channel runs the same check. The snippets pin `v1.5.0`. Keep a pin, so a new release never
changes your results without a commit of yours.

### Claude Code

```
/plugin marketplace add OrodruinLabs/agent-comment-lint
/plugin install agent-comment-lint@agent-comment-lint
```

macOS, Linux and Windows are supported. The plugin finds Python as `AGENT_COMMENT_LINT_PYTHON`, `python3`, `python`,
then `py -3`. A write that adds a bad comment is blocked, and Claude sees why. Old comments the write
leaves alone never block it. When Claude stops, the plugin also checks the comments written any other way, such as
through Bash, on the lines changed since the session started and not yet committed. To turn it on for a whole team, see [Claude Code setup](https://github.com/OrodruinLabs/agent-comment-lint/blob/main/docs/reference.md#claude-code).

### Other coding agents

For Codex CLI, Windsurf / Devin and Gemini CLI, install the command as under [Command line](#command-line), then copy
the agent's template from `integrations/` and the guard scripts at the `v1.5.0` tag. The steps for each agent are in
[the reference](https://github.com/OrodruinLabs/agent-comment-lint/blob/main/docs/reference.md#other-coding-agents).

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
      - uses: OrodruinLabs/agent-comment-lint@v1.5.0
```

Only the lines the pull request changes are checked. Keep `fetch-depth: 0`, or the step cannot see what changed and
fails. Findings appear as annotations on the changed lines. GitHub shows at most 10 per step, and the job summary
lists them all. The inputs are in [the reference](https://github.com/OrodruinLabs/agent-comment-lint/blob/main/docs/reference.md#github-actions).

### pre-commit

```yaml
repos:
  - repo: https://github.com/OrodruinLabs/agent-comment-lint
    rev: v1.5.0
    hooks:
      - id: agent-comment-lint-staged
```

This checks only the lines you stage, as the index holds them, so a repository with old findings can turn it on today.
To judge each staged file whole instead, use `id: agent-comment-lint`, and fix or exclude old findings first.

The staged id is for commit time. Under `pre-commit run --all-files`, in pre-commit.ci or at a pre-push stage nothing is
staged, so it judges nothing. In CI, use the GitHub Action (or `--diff`), or the whole-file id with `--all-files`.

### Command line

```
uv tool install agent-comment-lint==1.5.0
pipx install agent-comment-lint==1.5.0
```

To install from the repository instead:

```
uv tool install git+https://github.com/OrodruinLabs/agent-comment-lint@v1.5.0
pipx install git+https://github.com/OrodruinLabs/agent-comment-lint@v1.5.0
```

`uvx agent-comment-lint` runs it without installing, which suits CI and trials.

```
agent-comment-lint --diff origin/main    # only what the branch changes
agent-comment-lint --all                 # every covered file in the repository
agent-comment-lint --files a.ts b.py     # the named files
```

| Exit code | Meaning |
| :--- | :--- |
| 0 | Clean. |
| 1 | At least one violation. |
| 2 | Could not scan. Never treated as a pass. |

## Configuration

Optional. Add `.agent-comment-lint.json` at the repository root. Settings can only make the check stricter: there
are no limits to change and no way to silence one comment inline. Every entry states its reason.

| Setting | What it does |
| :--- | :--- |
| `$schema` | Optional. Lets editors check and complete the file. |
| `exclude` | Paths that are never checked, such as vendored or generated code. |
| `governance.packs` | Turns on reference packs, below. |
| `governance.extra` | Adds your own reference patterns, as regular expressions. |

```json
{
  "$schema": "https://raw.githubusercontent.com/OrodruinLabs/agent-comment-lint/v1.5.0/schema/agent-comment-lint.schema.json",
  "exclude": [{ "path": "vendor/", "reason": "third-party code" }],
  "governance": {
    "packs": ["azure-boards"],
    "extra": [{ "pattern": "\\bWEB-\\d+", "reason": "the web team's ticket ids" }]
  }
}
```

The Claude Code hook and the end-of-session check read this file as committed, so a new exclusion reaches them once a
human commits it. Outside git, before the first commit, and with `--config`, they read the file on disk.

### Reference packs

C3 always refuses the common shapes shown in [What it checks](#what-it-checks). A pack adds the reference shapes of
one tracker or convention. Packs are off by default because the same shapes mean other things in many codebases, so
turn on only the ones your team uses.

| Pack | Turn it on if you use | It refuses |
| :--- | :--- | :--- |
| `agent-context` | AI agents that cite a plan, a chat or a notes file | `Task 8`, `step 3 of the plan`, `per the spec`, `as requested`, `the user asked`, `PLAN.md` |
| `azure-boards` | Azure Boards | `AB#4321`, `ADO #795`, `ADO 795` |
| `decision-ids` | numbered decisions | `D-7`, `D-12b`, `D7` |
| `task-ids` | task ids shaped prefix, dash, letter, number | `WEB-T022`, `AUTH-F053` |

## Documentation

[The reference](https://github.com/OrodruinLabs/agent-comment-lint/blob/main/docs/reference.md) has everything else:
- every reference shape C3 refuses
- each mode and exit code
- team setup for Claude Code
- what each language's lexer can and cannot tell apart
- the known false positives

## License

MIT. See [LICENSE](https://github.com/OrodruinLabs/agent-comment-lint/blob/main/LICENSE).
