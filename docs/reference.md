# agent-comment-lint reference

The full contract: what each rule judges, every mode and exit code, the settings file, and what
the lexers can and cannot tell apart. The [README](../README.md) covers the basic setup.

## Contents

- [Setup details](#setup-details): [Claude Code](#claude-code), [GitHub Actions](#github-actions),
  [pre-commit](#pre-commit)
- [The rules](#the-rules)
- [Governance references (C3)](#governance-references-c3)
- [Scope](#scope)
- [Running it](#running-it)
- [Exit codes](#exit-codes)
- [Per-repository settings](#per-repository-settings)
- [What the lexers know and do not know](#what-the-lexers-know-and-do-not-know)
- [Known false positives](#known-false-positives)
- [The write-time hook](#the-write-time-hook)
- [Versions](#versions)
- [Developing](#developing)

## Setup details

### Claude Code

The plugin registers a PreToolUse hook on `Write`, `Edit` and `MultiEdit`. It runs on macOS, Linux and Windows. It
looks for Python as `AGENT_COMMENT_LINT_PYTHON` (when set, the only candidate), then `python3`, `python` and `py -3`,
and takes the first that is Python 3.9 or newer. With none, the write is blocked with exit 2. A write that adds a finding is blocked, and Claude sees the report.
Writes that only keep old findings go through.

On Claude Code 2.1.275 or later one line installs it:
`/plugin install agent-comment-lint --marketplace OrodruinLabs/agent-comment-lint`.

To offer the plugin to everyone who opens a repository, commit this to its `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "agent-comment-lint": { "source": { "source": "github", "repo": "OrodruinLabs/agent-comment-lint" } }
  },
  "enabledPlugins": { "agent-comment-lint@agent-comment-lint": true }
}
```

Without the plugin, an installed command does the same job. Install it with `uv tool install agent-comment-lint==1.2.0`
or `pipx install agent-comment-lint==1.2.0` (`uvx agent-comment-lint` is for CI and trials). Register this command as the PreToolUse hook. The guard
turns a missing command into exit 2, because Claude Code lets a write through on any other failure:

```
command -v agent-comment-lint >/dev/null || { echo "Blocked: agent-comment-lint is not installed" >&2; exit 2; }; agent-comment-lint --hook
```

Enable either the plugin or the command, not both, or every write is judged twice.

### GitHub Actions

| Input | Meaning |
| --- | --- |
| `mode` | `diff` (the default: the lines the pull request changes) or `all`. |
| `base` | The ref `--diff` compares against. Defaults to the pull request's target branch. |
| `args` | More flags, such as `--config`. |

Without `fetch-depth: 0` on the checkout the merge base is missing, and the step exits 2.

To post the findings as review comments instead, pipe the command through reviewdog. The step names `shell: bash`,
which runs with `-o pipefail`, so a "could not scan" exit 2 is not hidden by reviewdog's own status. The checkout needs
`fetch-depth: 0` for `--diff`.

```yaml
- shell: bash
  run: agent-comment-lint --diff origin/${{ github.base_ref }} | reviewdog -efm="%f:%l: %m" -reporter=github-pr-review -filter-mode=added
```

### pre-commit

The hook works with pre-commit and prek. It has two ids. `agent-comment-lint-staged` judges only the lines staged for
the commit, read from the index, so a partly staged file is judged as it will be committed; it suits a repository with
old findings. `agent-comment-lint` judges the whole of each staged file. A repository that uses it fixes its old
findings, or excludes their paths, before it turns the hook on.

## The rules

| Rule | In plain words |
| --- | --- |
| C1 | A comment block holds at most one line of prose. A run of consecutive `//`, `///` or `#` lines is one block. So is a `/* */` comment that spans lines, and so is a Python docstring. A complete one-line tag (`<summary>...</summary>`, `<inheritdoc/>`, `@param ...`) does not count. A line with no letter or digit in any script, such as a ruler (`// ----`, `# ====`, `//////`), is decoration: it neither counts as prose nor ends the block, so a title between two rulers is one line of prose. A `/* */` comment that opens and closes on one line always passes. In C# and HCL a `/* */` comment that opens after code on its line is scored less fully: see [What the lexers know and do not know](#what-the-lexers-know-and-do-not-know). |
| C3 | No comment names a governance reference: a decision record, a task, an acceptance criterion, a work item, a pull request or a planning document. The list is below. |
| C5 | An assertion message concatenated with `+ "..."` covers at most two lines. The rule is shaped for C# and applies wherever that shape appears. |
| C7 | A line that carries a comment is at most 120 characters long, counting indentation and code. |

Every block is scored. There is no mode that reports only a file's worst block.

Rules C2 (inherit, never restate), C4 (necessity) and C6 (production strings are untouchable) need a compiler or
human judgment. This engine does not check them.

## Governance references (C3)

A comment explains the code. A pointer to a ticket, a plan or a decision record rots as soon as that document moves,
so C3 refuses it. Every repository is judged by the core list. A repository can add packs and patterns of its own in
its settings file. Nothing can remove a core pattern.

**Core, always on**

| Kind | Shapes |
| --- | --- |
| Decisions | `ADR-9` |
| Requirements and plans | `PRD-1`, `TRD-12`, `FEAT-xyz`, `TEST-PLAN`, `DEF-3`, `PATCH-2` |
| Tasks and test cases | `TASK-12`, `TC-12` |
| Acceptance criteria | `AC-12`, `AC-F5.6`, `AC5` |
| Work items and pull requests | `PR 519`, `PR-519`, `work item 1234`, `story 716`, `user story 716`, `bug #42`, `task #42`, `issue #42`, `ticket #42`, `thread 1234` |
| Documents | any `docs/...` path, `CLAUDE.md`, `AGENTS.md` |

**Packs, opt-in by name**

| Pack | Shapes |
| --- | --- |
| `agent-context` | `Task 8`, `step 3 of the plan`, `per the spec` (or `per the code review`), `as requested`, `as discussed`, `as agreed`, `the user asked`, `the user requested`, and an upper-case notes file such as `PLAN.md` (not `README.md`, `CHANGELOG.md`, `LICENSE.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CLAUDE.md` or `AGENTS.md`) |
| `azure-boards` | `AB#4321`, `ADO #795`, `ADO 795` |
| `decision-ids` | `D-7`, `D-12b`, and `D7` outside a run of hex bytes |
| `task-ids` | a prefix of two to five capitals, a dash, one capital and two or more digits: `WEB-T022`, `AUTH-F053`, `DATA-P002a` |

A bare `#123` is not a reference: colours, HTML entities and upstream issue numbers share that shape.
Names such as `SHA-256`, `RFC-7807` and `UTF-16` are not references.
The exact patterns are in `agent_comment_lint/governance.py`.

## Scope

| Language | Extensions | Comments read |
| --- | --- | --- |
| C# | `.cs` | `//`, `///`, `/* */` |
| JavaScript and TypeScript | `.ts` `.tsx` `.js` `.jsx` `.mjs` `.cjs` `.mts` `.cts` | `//`, `/* */`, JSX `{/* */}` |
| CSS | `.css` | `/* */` |
| Shell | `.sh` | `#` |
| YAML | `.yml` `.yaml` | `#` |
| HCL | `.tf` `.tfvars` `.hcl` | `#`, `//`, `/* */` |
| Python | `.py` | `#`, docstrings |

Never judged, in any repository: files under `node_modules`, `bin`, `obj`, `.terraform`, `dist`, `build`, `coverage`,
`.git`, `.claude`, `generated`, `Migrations`, `.venv`, `venv`, `__pycache__` or `.pytest_cache`, and any
`.terraform.lock.hcl`.

Not covered: SQL, HTML, XML, Markdown, Dockerfile, TOML and JSON with comments.

## Running it

Written for Python 3.9 or newer, with no package beyond the standard library. The pipeline runs the tests on every
version from 3.9 to 3.13.

Files, standard input and the settings file are read as UTF-8. A leading byte-order mark is skipped. `--hook` refuses
standard input that is not UTF-8 instead of replacing the bytes it cannot read.

```
agent-comment-lint --diff origin/main    # only what the branch changes
agent-comment-lint --staged              # only the lines staged for the next commit
agent-comment-lint --all                 # every covered file in the repository
agent-comment-lint --files a.ts b.py     # the named files
agent-comment-lint --stdin-path a.ts     # the text on standard input, judged as a.ts
agent-comment-lint --hook                # a Claude Code PreToolUse event on standard input
agent-comment-lint --version             # the installed version
```

Without an install, `python3 check-agent-comment-lint.py` from a checkout takes the same arguments, and so does
`python3 -m agent_comment_lint`. On Windows, use `py -3` or `python` for `python3`.

| Mode | What it judges |
| --- | --- |
| `--diff BASE` | Files changed by the commits since the merge base with `BASE`. A finding is reported when its lines overlap a changed line, so a block that grows is reported from its first line. A renamed file is judged on its changed lines only. A changed file that git treats as binary (a `-diff` attribute, a NUL byte) has no changed lines to read, so the whole file is judged: every line of it counts as changed. A file whose content did not change, because only its mode or its name changed, is not read at all, whether git treats it as text or as binary. Only committed changes count: commit before you run it. |
| `--staged` | The lines staged for the next commit, with the text read from the index, so a partly staged file is judged as it will be committed. Unstaged edits are ignored. Before the first commit every staged line counts. Selection, binary files and the line count check work as in `--diff`; a staged file that is not UTF-8 text cannot be judged, and is not passed. |
| `--all` | Tracked files and new files that are not ignored, as git lists them. Outside a repository it walks the directory instead. Finding no covered file is exit code 2, not a clean run. |
| `--files` | The files named. A named file that is out of scope or excluded is not judged. Needs no git. |
| `--stdin-path` | A proposed file body, for an editor or write-time hook. The file on disk is not read. A fragment of a file may not lex; exit code 2 then means "no verdict", and the hook decides what to do with it. Needs no git. |
| `--hook` | The write in a Claude Code PreToolUse event (`Write`, `Edit`, `MultiEdit`) read from standard input. The whole file the write would leave is judged, and a finding counts only where its lines overlap a line the write adds or changes, as `--diff` does. Exit code 0 lets the write through and prints nothing. Any finding, a file that cannot be scanned, a file on disk that is not UTF-8, or input that is not the event is exit code 2, which blocks the write, with the report on standard error. Without `--root`, a path in another worktree of the same repository is judged from that worktree's top, with its settings file. Other tools, uncovered or excluded paths, other paths outside the root, and an edit the tool itself would refuse are let through. `--json` is a usage error with it. |

Options: `--json` prints one JSON document instead of text. `--root DIR` sets the repository root (default: the git
top level of the working directory). `--config FILE` names the settings file.

What each mode does when git cannot answer (no git program, a `GIT_DIR` that names no repository, a stale `.git`
file, a repository git refuses to read):

| Mode | When git cannot answer |
| --- | --- |
| `--diff`, `--staged` | Exit code 2, always. There are no changed lines without git. |
| `--all` | Exit code 2 where a `.git` entry in the directory or a parent, or `GIT_DIR`, claims a repository. The tree is not walked instead. Where nothing claims one, the directory is walked. |
| `--files`, `--stdin-path`, `--hook` | A verdict all the same. The root is the working directory, or `--root`, so paths are reported from there and the settings file is looked for there. With `--root`, git is not asked at all. |

Output is one line per finding, ordered by path, line and rule, then one summary line:

```
src/a.ts:12: C1: 3-line prose block (limit 1)
src/a.ts:40: C3: governance reference 'ADR-0009'
agent-comment-lint: 2 violation(s) in 1 of 57 file(s) scanned.
```

The JSON document has `version`, `mode`, `exit_code`, `files_scanned`, `counts` (by rule), `findings` (each with
`path`, `line`, `end_line`, `rule` and `message`), `errors` and `unresolved_lines`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Clean. |
| 1 | At least one violation. |
| 2 | Could not scan. The cases are listed below. |

Exit code 2 is never downgraded. These are exit code 2, each with a message that names the cause:

- Bad arguments, or a `--root` that is not a directory.
- A malformed settings file, or a `--config` file that does not exist. That includes an unknown governance pack and a
  governance pattern that is not a valid regular expression or that matches empty text. `--hook` reads the settings file only for a
  covered path inside the root, so a write it never judges is let through whatever the settings file holds.
- A file that cannot be read.
- A file that cannot be lexed. A string, template literal, raw string, triple-quoted string or heredoc that never
  closes stops the scan with the file and the line, because nothing below it can be judged honestly. So does a `/*`
  that never closes in JavaScript, TypeScript or CSS.
- `--diff` with a base that does not resolve. Git's own reason is printed. It is not "0 findings".
- `--diff` when the changed lines read from git's diff do not add up to git's own count of added lines for a judged
  file. The engine asks git for a fixed diff format whatever the user's git settings are. If the answer still does
  not add up, the file is not passed as "no changed lines".
- `--diff` when a changed file that git treats as binary is not UTF-8 text, such as a UTF-16 source file, and its
  content changed. It cannot be judged, and it is not passed.
- `--staged` when a staged file is not UTF-8 text, or its blob cannot be read from the index.
- `--diff` when git fails, or when its count of added lines or its list of changed files cannot be read.
- `--all` in a repository that git cannot read or without a git program. The tree is not walked instead.
- `--all` that finds no covered file. A mistyped root or an empty checkout must not pass a gate.

`--diff`, `--staged`, `--files` and `--stdin-path` may judge no file and exit 0: a change can touch no covered file.

## Per-repository settings

A repository may add `.agent-comment-lint.json` at its root. It can exclude paths and add governance references. Every
entry states its reason:

```json
{
  "$schema": "https://raw.githubusercontent.com/OrodruinLabs/agent-comment-lint/v1.2.0/schema/agent-comment-lint.schema.json",
  "exclude": [
    { "path": "public/mockServiceWorker.js", "reason": "generated by the mock library" },
    { "path": "vendor/", "reason": "third-party code" }
  ],
  "governance": {
    "packs": ["azure-boards"],
    "extra": [
      { "pattern": "\\bWEB-\\d+", "reason": "the web team's ticket ids" }
    ]
  }
}
```

- `$schema` is optional and ignored by the check. It lets editors validate and complete the file.
- `exclude[].path` is relative to the repository root. `*` and `?` match inside one directory, `**` crosses
  directories, and a final `/` takes the whole tree.
- `governance.packs` names packs from the table above.
- `governance.extra[].pattern` is a Python regular expression, searched in each comment's text. It is
  case-sensitive unless it says `(?i)`. A pattern that matches empty text is refused.
- Any other key, an entry without a reason, an unknown pack or an invalid pattern is exit code 2.

Settings can only make the policy stricter. No limit is configurable: the prose budget, the line length and the core
governance list are the policy. There is no inline suppression.

## What the lexers know and do not know

- JavaScript and TypeScript are lexed across lines. Strings, template literals (tagged ones and nested `${ }`
  included) and regex literals are content, so `//` or `/*` inside them opens no comment.
- A `/` opens a regex literal at the start of the file, after an operator, an opening bracket, a comma, a semicolon,
  or one of `return`, `typeof`, `instanceof`, `in`, `of`, `new`, `delete`, `void`, `throw`, `case`, `do`, `else`,
  `yield`, `await`. It also opens one after `}`, which ends a block far more often than a value. After a name, a
  number, a string, `)`, `]` or `<` it divides. A regex must close on its own line, and its closing `/` may not be
  followed by `/` or `*`. Otherwise the first `/` divides.
- In JavaScript, TypeScript and CSS the lexer finds every `/* */` comment that spans lines. It is one block wherever
  it opens, also after code on the same line.
- JSX is not parsed. In `.tsx` and `.jsx` a quote that does not close on its line is taken as text, so an apostrophe
  in JSX text is fine. JSX text that holds `//` or `/*` still reads as a comment. A `/*` in JSX text with no `*/`
  after it is exit code 2.
- C#, shell, YAML, HCL and Python are read one line at a time. A quoted
  string that does not close on its line leaves that line unjudged. The JSON report counts those lines as
  `unresolved_lines`. C# raw strings, heredocs and Python triple-quoted strings are followed across lines.
- In C# and HCL a line that starts with `*` counts as the continuation of a block comment.
- In every language with `/* */`, what follows a closing `*/` on its line is read as a line of its own. A `//` or
  `#` comment there starts the next block, and a `/*` there opens one. No block is open there, so a `*` that starts
  it is code. In C# and HCL this holds also for the close of a block that opened after code.
- In C# and HCL a `/* */` comment that spans lines is one block when it opens its line. When it opens after code on
  its line, only its lines that start with `*` are scored. A `/*` that never closes is not refused there: a line at
  a time, the engine cannot tell a comment opener from a `/*` inside a multi-line verbatim string.
- A `<<` inside shell arithmetic `(( ))` is a shift, not a heredoc. `<<<` is a herestring.
- Python text that parses is never refused. A triple quote that never closes is refused only when the text does not
  parse.
- A comment block can be split by blank lines into separate one-line blocks, and each passes C1. Joining such runs
  flagged many legitimately separate comments, so it is not done. The write-time hook's message tells the agent that
  splitting is not a fix.

## Known false positives

Each one is pinned by a test (`tests/test_known_false_positives.py`), so changing one is a decision and not an
accident.

| Where | What is reported | Example |
| --- | --- | --- |
| C# and HCL | A code line that starts with `*` counts as comment prose, so a multiplication wrapped over two lines is a C1 block. | `var x = a` / `    * b` / `    * c;` |
| Every language | `docs/` matches anywhere in a comment, also inside a web address. | `// https://developer.mozilla.org/en-US/docs/Web/API/fetch` is C3 |
| Shell, YAML, HCL | Any `#` outside quotes starts a comment, also inside a parameter expansion. | `x=${y#docs/prefix}` is C3. A line over 120 characters that holds `$#` is C7 |
| C# | Lines inside a multi-line verbatim string `@"..."` are judged as code. | `// ...` lines inside one are a C1 block |
| Python, with the `agent-context` pack on | `as requested` and `per the spec` match ordinary prose in a comment. Pinned by `tests/test_known_false_positives.py`. | `# calling CloseHandle as requested in [1]` and `# Map conditions (per the spec) to signals` are C3 |

## The write-time hook

`--hook` reads the event Claude Code sends a PreToolUse hook. The file the write would leave is judged whole, and a
finding counts only where it overlaps a line the write adds or changes.

- The report on standard error quotes each offending comment and says how to fix it, then closes with what not to
  try. A `Write` also gets a line telling it to re-send with only the comment lines changed. For example:

  ```
  Blocked: agent-comment-lint rejects this write.
  Only the lines this write adds or changes are judged; comments elsewhere in the file are fine.
  a.ts:1: C1: 2-line prose block (limit 1)
      // one
      // two
    Fix: Keep one line that says why the code is this way; put the rest in the commit message or the PR description.
  agent-comment-lint: 1 violation(s) in 1 of 1 file(s) scanned.
  Fix the comment and retry the same tool call.
  Splitting the comment across blank lines, or writing the file another way (Bash, a script, another tool), does not satisfy the policy.
  Adding an exclusion to .agent-comment-lint.json is not the fix: exclusions are for generated and third-party code.
  ```

  An excerpt shows at most 6 lines of the comment, each cut at 120 characters.
- A crash inside the hook is also exit code 2 with that header, never exit code 1, which Claude Code does not block on.
- The plugin's hook entry sets `"onFailure": "block"`, so a hook that times out blocks the write.
- Known limit: Claude Code also matches curly quotes against straight ones and tries escape variants of
  `old_string`. The hook matches exactly, plus line endings, so such an edit is let through as one the tool would
  refuse.
- Known limit: the changed lines are found after trimming the lines a write leaves untouched at the start and end
  of the file. A write that changes lines far apart across a very large, repetitive file is still quadratic: about
  6 s at 10,000 lines, and near 30,000 lines a `replace_all` can pass the 60 s hook timeout. Exclude big generated
  files.

## Versions

Releases follow semantic versioning, with one rule on top: any change that can move findings is at least a minor
release, and the changelog says which rules or languages it moves. A patch release never changes a verdict. Pin a
tag, and read the changelog before you move the pin.

## Developing

```
python3 -m unittest discover -s tests     # the tests
python3 check-agent-comment-lint.py --all     # the engine over this repository
```

| Path | Responsibility |
| --- | --- |
| `check-agent-comment-lint.py` | Entry point that runs from a checkout with no install. |
| `agent_comment_lint/lexers/` | One lexer per language family behind one contract (`base.py`): text in, one `Line` per source line out. |
| `agent_comment_lint/rules.py` | C1, C3, C5 and C7 as pure functions over lexed lines. |
| `agent_comment_lint/governance.py` | The core list, the packs, and the matcher a repository's settings build. |
| `agent_comment_lint/engine.py` | One file: pick the lexer, lex, apply the rules. |
| `agent_comment_lint/diff.py` | Changed line ranges from a unified diff. |
| `agent_comment_lint/config.py` | The settings file and the default skips. |
| `agent_comment_lint/report.py` | Text and JSON output, exit codes. |
| `agent_comment_lint/gitio.py` | The only code that runs git, and reads its answers. |
| `agent_comment_lint/hook.py` | The write a Claude Code event proposes, and the lines it touches. |
| `agent_comment_lint/cli.py` | Arguments and file reading. |
| `hooks/` | The Claude Code plugin's hook and its shell wrapper. |
| `tests/test_known_false_positives.py` | The known false positives, pinned. |
