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
- [The end-of-session check](#the-end-of-session-check)
- [Other coding agents](#other-coding-agents)
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

Without the plugin, an installed command does the same job. Install it with `uv tool install agent-comment-lint==1.5.0`
or `pipx install agent-comment-lint==1.5.0` (`uvx agent-comment-lint` is for CI and trials). Register this command as the PreToolUse hook. The guard
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

The staged id judges only staged lines, so it is for commit time. Under `pre-commit run --all-files`, in pre-commit.ci
or at a pre-push stage nothing is staged, and it passes without judging anything. For CI, use the GitHub Action (or
`--diff`), or the whole-file `agent-comment-lint` id with `--all-files`.

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
| Ruby | `.rb` `.rake` `.gemspec`, and the names `Gemfile` and `Rakefile` | `#`, `=begin` / `=end` |
| TOML | `.toml` | `#` |
| Dockerfile | `.dockerfile`, and the names `Dockerfile` and `Containerfile` | `#` at the start of a line |
| Makefile | `.mk`, and the names `Makefile`, `makefile` and `GNUmakefile` | `#` |

Never judged, in any repository: files under `node_modules`, `bin`, `obj`, `.terraform`, `dist`, `build`, `coverage`,
`.git`, `.claude`, `generated`, `Migrations`, `.venv`, `venv`, `__pycache__` or `.pytest_cache`, and any
`.terraform.lock.hcl`.

Not covered: SQL, HTML, XML, Markdown and JSON with comments.

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
agent-comment-lint --hook                # a Claude Code hook event on standard input: PreToolUse, SessionStart, Stop
agent-comment-lint --version             # the installed version
```

Without an install, `python3 check-agent-comment-lint.py` from a checkout takes the same arguments, and so does
`python3 -m agent_comment_lint`. On Windows, use `py -3` or `python` for `python3`.

| Mode | What it judges |
| --- | --- |
| `--diff BASE` | Files changed by the commits since the merge base with `BASE`. A finding is reported when its lines overlap a changed line, so a block that grows is reported from its first line. A renamed file is judged on its changed lines only. A changed file that git treats as binary (a `-diff` attribute, a NUL byte) has no changed lines to read, so the whole file is judged: every line of it counts as changed. A file whose content did not change, because only its mode or its name changed, is not read at all, whether git treats it as text or as binary. Only committed changes count: commit before you run it. |
| `--staged` | The lines staged for the next commit, with the text read from the index, so a partly staged file is judged as it will be committed. Unstaged edits are ignored. Before the first commit every staged line counts. Selection, binary files, the line count check and bytes that are not UTF-8 work as in `--diff`: a text file is judged with such bytes replaced, and a file git treats as binary that is not UTF-8 text cannot be judged, and is not passed. |
| `--all` | Tracked files and new files that are not ignored, as git lists them. Outside a repository it walks the directory instead. Finding no covered file is exit code 2, not a clean run. |
| `--files` | The files named. A named file that is out of scope or excluded is not judged. Needs no git. |
| `--stdin-path` | A proposed file body, for an editor or write-time hook. The file on disk is not read. A fragment of a file may not lex; exit code 2 then means "no verdict", and the hook decides what to do with it. Needs no git. |
| `--hook` | A Claude Code hook event read from standard input. A `SessionStart` event records a snapshot of the working tree and a `Stop` event judges what changed since: see [The end-of-session check](#the-end-of-session-check). Any other event is read as a PreToolUse event, whose proposed write (`Write`, `Edit`, `MultiEdit`) is judged. The whole file the write would leave is judged, and a finding counts only where its lines overlap a line the write adds or changes, as `--diff` does. Exit code 0 lets the write through and prints nothing. Any finding, a file that cannot be scanned, a file on disk that is not UTF-8, or input that is not the event is exit code 2, which blocks the write, with the report on standard error. Without `--root`, a path in another worktree of the same repository is judged from that worktree's top, with its settings file. Other tools, uncovered or excluded paths, other paths outside the root, and an edit the tool itself would refuse are let through. `--json` is a usage error with it. |

Options: `--json` prints one JSON document instead of text. `--root DIR` sets the repository root (default: the git
top level of the working directory). `--config FILE` names the settings file. `--agent NAME`, with `--hook` only,
names the agent whose event is read: see [Other coding agents](#other-coding-agents).

What each mode does when git cannot answer (no git program, a `GIT_DIR` that names no repository, a stale `.git`
file, a repository git refuses to read):

| Mode | When git cannot answer |
| --- | --- |
| `--diff`, `--staged` | Exit code 2, always. There are no changed lines without git. |
| `--all` | Exit code 2 where a `.git` entry in the directory or a parent, or `GIT_DIR`, claims a repository. The tree is not walked instead. Where nothing claims one, the directory is walked. |
| `--files`, `--stdin-path` | A verdict all the same. The root is the working directory, or `--root`, so paths are reported from there and the settings file is looked for there. With `--root`, git is not asked at all. |
| `--hook` | A PreToolUse write gets a verdict all the same, from the working directory or `--root`. The settings file is read through git, as committed at HEAD, even with `--root`; where git names no work tree, the file on disk is read instead. `SessionStart` records no snapshot, and the `Stop` check lets the session end. Once a snapshot is found, a git failure at stop is exit code 2. |

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
- `--staged` when a staged file that git treats as binary is not UTF-8 text, or a blob cannot be read from the index.
- `--diff` when git fails, or when its count of added lines or its list of changed files cannot be read.
- `--all` in a repository that git cannot read or without a git program. The tree is not walked instead.
- `--all` that finds no covered file. A mistyped root or an empty checkout must not pass a gate.

`--diff`, `--staged`, `--files` and `--stdin-path` may judge no file and exit 0: a change can touch no covered file.

## Per-repository settings

A repository may add `.agent-comment-lint.json` at its root. It can exclude paths and add governance references. Every
entry states its reason:

```json
{
  "$schema": "https://raw.githubusercontent.com/OrodruinLabs/agent-comment-lint/v1.5.0/schema/agent-comment-lint.schema.json",
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

The write-time hook and the end-of-session check read the file as committed at HEAD, so an exclusion an agent adds
reaches them only after a human commits it. Outside git, before the first commit, and with `--config`, they read the
file on disk. Every other mode reads it from disk. The file must be a regular file, not a symlink.

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
- Ruby is read one line at a time. A string that does not close on its line leaves that line unjudged. Heredoc
  payload (`<<ID`, `<<-ID`, `<<~ID`, quoted identifiers) is content, and a `=begin` / `=end` block is one comment
  block. A plain `<<ID` ends at a terminator in column zero, while `<<-ID` and `<<~ID` may be indented. An
  unterminated heredoc or `=begin` is exit code 2. It does not know character literals, percent literals, regex
  literals, a second heredoc on one line, backtick heredocs or `__END__`.
- TOML is read across lines. Basic, literal and multi-line strings are content, so a `#` inside them opens no
  comment, and a comment after a closing triple quote is read. A multi-line string that never closes is exit code 2.
- A Dockerfile line is a comment only when `#` is its first non-blank character, so a `#` after an instruction is
  shell text. A comment inside a continued instruction is judged. Parser directives (`syntax`, `escape`, `check`)
  above the first comment, blank line or instruction are not prose, and `escape` sets the continuation character.
  Heredoc payload of `RUN`, `COPY` and `ADD` (also after `ONBUILD`) is content. An unterminated heredoc is exit
  code 2.
- A Makefile line is make syntax, where a `#` that is not escaped as `\#`, and not inside a `$( )` or `${ }`
  reference, starts a comment and quotes do not protect it. A tab line is a recipe, read like shell: a `#` starts a
  comment only where a word could start. A comment that ends in a backslash continues onto the next line. A
  `define` block, nested ones counted, is content. A `define` that never closes, a reference that never closes
  and a recipe quote that never closes are exit code 2. It does not read `.RECIPEPREFIX` or the recipe after `;`.
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
| Makefile | The text after `;` on a rule line is read as make syntax, so quotes do not protect a hash. `.RECIPEPREFIX` is not read, so a recipe behind a custom prefix is make syntax too. | `all: ; echo "# docs/x"` is C3 |
| Ruby | A `#` in a character literal, a percent literal or a regex literal starts a comment, also the `#{ }` that opens an interpolation in a regex. | `x = ?#docs/prefix`, `%w[a #docs/prefix]` and `/#docs/prefix/ =~ s` are C3 |
| Ruby | Only the first heredoc opened on a line is followed, and a backtick heredoc is not one. The payload of the others reads as code. | `foo(<<~A, <<~B)` leaves the payload of `B` judged |
| Ruby | `__END__` is not known to end the source, so the data section after it is read for comments. | `# see ADR-7` after `__END__` is C3 |
| Ruby | A space before `<<` and a word after it is taken as a heredoc opener, also for an append, and an unterminated one is exit code 2. | `puts x if a <<b` is exit code 2 |
| Makefile | A comment written inside a `define` block is content, so it is never judged. | `# see ADR-7` between `define` and `endef` is not reported |
| C# | Lines inside a multi-line verbatim string `@"..."` are judged as code. | `// ...` lines inside one are a C1 block |
| Python, with the `agent-context` pack on | `as requested` and `per the spec` match ordinary prose in a comment. Pinned by `tests/test_known_false_positives.py`. | `# calling CloseHandle as requested in [1]` and `# Map conditions (per the spec) to signals` are C3 |

## The write-time hook

`--hook` reads the event Claude Code sends a PreToolUse hook. The file the write would leave is judged whole, and a
finding counts only where it overlaps a line the write adds or changes.

- The settings come from the file as committed at HEAD in the judged root, not from the working tree, so adding an
  exclusion does not excuse the write that prompted it. A committed file that is malformed or not UTF-8 is exit code
  2. Outside git, before the first commit, and with `--config`, the file on disk is read.
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
  Adding an exclusion to .agent-comment-lint.json is not the fix: exclusions are for generated and third-party code, and a new one has no effect here until a human commits it.
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

## The end-of-session check

A file written through Bash or another tool never reaches the write-time hook. The plugin closes that hole when
Claude stops. A `SessionStart` entry records a snapshot of the working tree, and a `Stop` entry judges what changed
since. Both run the same wrapper and `--hook`, which dispatches on the event's `hook_event_name`.

- What is judged: lines changed since the session started and not yet committed. A line counts only where it differs
  both from the snapshot and from HEAD, so switching branches, pulls, rebases and resets during the session bring in
  no old line. While a merge, rebase or cherry-pick is stopped on a conflict, or a merge is held by `--no-commit`, a
  line must also differ from the commit being brought in (`MERGE_HEAD`, `REBASE_HEAD` or `CHERRY_PICK_HEAD`), so the
  other side's lines are not judged either. A file created during the session and absent from HEAD is judged whole.
  A file unchanged since the snapshot is never read, so an old comment or a broken file in it cannot block. Lines
  the session commits are left to pre-commit (the `agent-comment-lint-staged` id) and CI. Before the first commit,
  every line changed since the snapshot counts.
- A file that changed during the session and cannot be scanned blocks, as exit code 2. So does one that is not
  UTF-8 text, as at write time.
- On findings the hook exits 2 with the same teaching report, opening "Before you finish:", and Claude keeps working.
- The snapshot is a git tree built from a temporary index. It writes no ref, no index and nothing in the working
  tree, only git objects and a file under `git rev-parse --git-path agent-comment-lint/sessions`. Files older than
  seven days there are removed. The snapshot and the check both run while a merge, rebase or cherry-pick is stopped
  on a conflict: a covered file is read from disk as it stands, and an unmerged file the policy does not cover is
  left out of the tree.
- No snapshot means no check. The session ends normally when the plugin was installed mid-session, taking the snapshot
  failed, the directory is not a git work tree, git refuses to read the repository, or the snapshot's objects were
  pruned (`git gc --prune=now`). The snapshot is the first one recorded for the session id, so a resumed or compacted
  session with none gets one at that moment, and the check covers changes from then on. A pruned snapshot is not
  replaced until its file is deleted. Once a snapshot is found, a git failure at stop blocks.
- How to reset: delete `$(git rev-parse --git-path agent-comment-lint/sessions)/<session id>`, or start a new session.
- Known limits:
  - Edits a human makes during the session count as the session's own until they are committed.
  - A session resumed later still judges from its first snapshot, kept for at least seven days, so everything left
    uncommitted since it first started counts.
  - Two sessions in one checkout each judge what the other changes while both are open.
  - Generated files a build changes during the session are judged. Exclude them in the committed settings.
  - Some git commands bring in another commit's lines uncommitted and leave no head the check can compare them
    against, so those lines are judged until they are committed: `git checkout <rev> -- <path>`,
    `git restore --source`, `git merge --squash`, `git cherry-pick -n`, `git stash pop`, `git am` stopped on a
    conflict, and `git revert` stopped on a conflict or run with `-n`.
  - Only the project directory's own working tree is covered, not sibling worktrees.
- Claude Code caps forced continuations at 8 in a row, and nothing here tries to get around that.

## Other coding agents

`--hook --agent NAME` reads the write event of another coding agent. `NAME` is `claude` (the default), `codex`,
`windsurf` or `gemini`. `--agent` without `--hook` is a usage error. `--agent claude` behaves as `--hook` always has.
The same rules judge the same changed lines, and a rejected write exits 2 with the same teaching report on stderr.
These agents get no end-of-session check, so a file they write through their shell is never judged.

Each adapter is built from the agent's documentation and has not been verified live: no agent has been seen blocking
a write. The README marks these "Preview". Copilot, Cursor, Kiro and Antigravity, marked "Planned", have no
adapter yet; [Agents without an adapter yet](#agents-without-an-adapter-yet) says why.

These hooks are a guardrail against careless comments, not a security boundary against an agent that sets out to
switch them off: the guards and hook configs sit in folders the agent can write to, and Codex's `commandWindows` runs
`git` through cmd's lookup, which searches the current directory first.

Install the command first (`uv tool install agent-comment-lint==1.5.0` or `pipx install agent-comment-lint==1.5.0`),
then copy the template and the guard scripts from the `v1.5.0` tag, so they match the installed version.

### The guard scripts

`integrations/guard/agent-comment-lint-guard.sh` (POSIX) and `agent-comment-lint-guard.cmd` (Windows) take the agent
name as their one argument and run `agent-comment-lint --hook --agent NAME`. They guarantee that a missing command, or
any exit other than 0, becomes exit 2 with a reason on stderr, so a crash blocks the write where the agent treats exit
2 as a block. They cannot stop an agent that lets a write through when its own hook runner crashes or times out.

### The capture scripts

`integrations/capture/capture-event.sh` and `capture-event.cmd` append standard input to the file named by
`AGENT_COMMENT_LINT_CAPTURE`, then exit 0, so they never block. Without the variable they say so on stderr and exit 0.
Register one as an agent's hook to record real events for a new adapter.

### PATCH_NOT_APPLIED

When a Codex patch or a Gemini or Windsurf edit does not apply exactly to the file on disk, the write is blocked with
"the edit does not apply exactly to the file on disk, so it cannot be judged".

A Codex patch is blocked the same way when Codex releases before 0.162.0 would write other lines than later ones,
because the hook cannot tell which release runs it. That happens when a context line matches the file only loosely
(other whitespace or punctuation, or a lone carriage return). It also happens when a hunk with no context adds lines
at the end of a file that ends in an empty line, or where another hunk adds lines too. Context lines copied exactly
from the file usually avoid it. In a file with Windows or mixed line endings, a line copied exactly can still be
blocked when a line before it matches it once the whitespace at its end is ignored.

### Codex CLI

- Event: `PreToolUse` for `apply_patch`. `tool_input.command` is the patch text.
- Mapping: each Add is judged as a new file. Each Update is applied to the file on disk and judged on the changed
  lines. A moved file is judged at its destination, on the lines changed relative to its source. When the policy
  does not judge the source (another file type, a skipped folder or an excluded path), or reads it as another
  language (`.css` to `.ts`, `.py` to `.sh`, or `.ts` to `.tsx`), every line of the destination counts as changed.
  A Delete is not judged. Relative paths resolve against the event's `cwd`. A patch Codex itself would refuse is
  blocked, with its reason. Context that matches nothing is blocked as above.
- Install, per project: put `agent-comment-lint` on PATH, copy `integrations/codex/hooks.json` to
  `<repo>/.codex/hooks.json`, copy the guard scripts to `<repo>/.codex/`, and review and trust the hook with `/hooks`.
  Codex loads a project's `.codex/` only for a trusted project, and records trust against the hook's hash, so a new
  or changed hook is skipped until it is trusted again. Keep the hook sync, with no `async: true`.
- How the guard is found: Codex runs the hook in the session's cwd and sets no project variable. The template finds
  the repository root with `git rev-parse --show-toplevel`, so a session in a subdirectory works. Codex runs the
  POSIX form in the user's login shell (`$SHELL -lc`), which works in sh, bash, zsh, and fish 3.4 or newer. With
  any other login shell, such as pwsh or nushell, every patch goes through. Do not use a user-level
  `~/.codex/hooks.json`, which would block every patch in a repository with no guard.
- Block channel: exit 2 with the report on stderr. Codex blocks the call and gives the text to the model.
- Crash and timeout: Codex has no fail-closed setting, so none is promised. A crash of Codex's hook runner, a timeout
  (600 s by default), any exit other than 0 or 2, or exit 2 with empty stderr lets the patch through. The guard
  always writes a reason. A missing guard, a session outside a git work tree, or git missing from PATH exits 2 on
  both OS forms.
- Known limits:
  - A patch sent as a shell command (`apply_patch <<'EOF'` through the shell tool) reaches hooks as `Bash` and is
    not judged. Codex calls hooks a guardrail, not a complete enforcement boundary.
  - A patch with two operations on one path is blocked, as Codex refuses it too. So is an Update of a file an earlier
    Move wrote.
  - A move between sibling worktrees fails closed.
  - On Windows, a repository under a non-ASCII path may block every patch. Unverified.
  - Case-only or symlink aliases of one path are not caught.

### Windsurf and Devin

- Event: `pre_write_code`. `tool_info.file_path` and `edits` (each with `old_string` and `new_string`) describe the
  write.
- Mapping: each edit is applied in order to the file on disk and the result is judged on the changed lines. An empty
  `old_string` is taken as a new file. On an existing file it blocks.
- Install: copy `integrations/windsurf/hooks.json` to `.devin/hooks.json`, and the guard scripts next to it in
  `.devin/`. The legacy `.windsurf/hooks.json` is read only when `.devin/hooks.json` is absent or defines no hooks.
  The template has a POSIX `command` and a `powershell` form. The PowerShell form is unverified on Windows.
- Block channel: exit 2, with stderr shown to the agent. There is no JSON channel. `show_output` also shows the
  output to the user in the Cascade panel.
- Crash and timeout: a crash of Windsurf's hook runner, or any exit other than 2, lets the write through, on every
  OS. The guard turns a failure of agent-comment-lint into 2. No timeout is documented.
- Known limits:
  - A custom `working_directory`, or a user-level install, leaves the guard unfound, so every write is blocked.
  - The shape of a new-file write is a guess, and needs a capture.
  - Hooks do not run in Restricted Mode.
  - The Devin CLI has its own hook system (`.devin/hooks.v1.json`), which is not covered.

### Gemini CLI

- Event: `BeforeTool`, matched on `write_file` and `replace`. `write_file` carries `file_path` and `content`.
  `replace` carries `file_path`, `old_string`, `new_string` and `allow_multiple`.
- Mapping: a `write_file` is judged as the new content. A `replace` is applied to the file on disk and judged on
  the changed lines. A relative `file_path` resolves against the event's `cwd`.
- Install: merge the hooks of `integrations/gemini/settings.json` (Windows: `settings.windows.json`) into
  `.gemini/settings.json`, and copy the guard scripts to `.gemini/`. Gemini fingerprints a project hook by its name
  and command, and warns as untrusted before running a changed one.
- Block channel: exit 2, with stderr sent to the agent as the reason, and the turn continues. The JSON
  `decision: "deny"` on exit 0 exists and is not used.
- Crash and timeout: any other exit continues with a warning. The default timeout is 60000 ms. What a timeout does is
  not documented, so none is promised. Non-JSON output on stdout means allow.
- Known limits:
  - Google replaced Gemini CLI with Antigravity CLI for consumer users on 2026-06-18, so this adapter serves
    Code Assist Standard and Enterprise.
  - The template finds the guard through `GEMINI_PROJECT_DIR`, which may be the session's directory and not the
    project root. A session in a subdirectory without a guard there fails closed, and a user-level install would too.
  - Whether `file_path` is absolute is undocumented.
  - One settings file holds one form, and each form fails on the other system. Gemini runs a hook through
    PowerShell on Windows, where the POSIX form lets the write through: Windows PowerShell 5.1 cannot parse it
    (exit 1, with a warning), and pwsh 7 exits 0, with no warning, when Git's `sh` is not on PATH, which is Git
    for Windows' default. On macOS and Linux the Windows form fails to parse and blocks every write.
  - So a team that mixes systems must not commit the POSIX form for everyone. Commit the guard scripts in
    `.gemini/`, and let each person merge the form for their system into their user-level
    `~/.gemini/settings.json`: the check is then set up per machine. That user-level hook blocks every write in a
    project without the guards.
  - Windows uses `settings.windows.json`, which has not been run on Windows.

### Agents without an adapter yet

An adapter needs to know which field of the hook event holds the file path and which holds the new text. For these
agents the docs do not say, so an adapter written today would rest on guesses. Each waits for one captured event.

- GitHub Copilot: the argument names of its `create` and `edit` tools are undocumented.
- Cursor: the input of its `Write` tool is undocumented.
- Kiro: the argument names of the V3 write tools are undocumented. The 2.x shape is known only from the source of its
  predecessor, the Amazon Q Developer CLI.
- Antigravity: the write tools' arguments are documented, but its exit codes are not, so how a hook blocks a write is
  unknown.

To contribute a capture, set `AGENT_COMMENT_LINT_CAPTURE` to a file, register
`integrations/capture/capture-event.sh` (`capture-event.cmd` on Windows) as the agent's before-write hook, and ask the
agent to create, edit and read a file. The script appends each event to that file and never blocks.

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
