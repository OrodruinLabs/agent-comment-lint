# agent-comment-lint: next-level roadmap (1.2.0 to 1.5.0)

Date: 2026-10-29. Status: design, awaiting the owner's approval. Starting point: v1.1.0 on `main` (commit `c7ccae4`).

This document describes what to build across four releases. It is written for a builder who will turn it into
implementation plans without talking to the owner. Where a choice was the owner's, it says so. Where a choice was made
on the owner's behalf, it is marked **(designer's call)** and can be overturned. Everything else under "Left to the
builder" is the builder's to decide.

The evidence behind each item (code measurements, links, the CPython precision run) is in the joint architect and
researcher report this design came from. Its key numbers are repeated here so this document stands alone.

## 1. Intent

agent-comment-lint stops AI coding agents from bloating code comments. It does that with a deterministic block before
the write lands, and with the same rules in pre-commit and CI. Research done for this design found:

- The problem is real and growing. The open Claude Code issue "Claude verbose code comments by default — ignores
  instructions to stop" has 252 thumbs-up. Its reporters say a CLAUDE.md rule "does not reliably suppress it".
- The most distinctive agent failure is a comment that points at the chat, the plan or the task: "(Task 8)",
  "step 3 of the plan", "as requested", "see INTERNAL_NOTES.md". A sample found such comments in 13.8% of commits Claude
  co-authored, against 0.5% of commits from 2021. v1.1.0 catches one of six real examples.
- An established rival exists: `comment-checker` gets about 80k npm downloads a month through a popular agent
  toolkit. It checks after the write lands, flags every comment in a full-file write, old ones included, and lets the
  write through when it can't parse its input. It does not check ticket or plan references, and it has no pre-commit
  or CI form.
- Agents that are blocked without guidance route around the hook, for example by writing the file through Bash.

So "next level" means four things, one per release:

1. **1.2.0:** the hook blocks only what it should, teaches the fix on the first retry, and catches plan and chat
   references. The tool also becomes easy to install and easy to see in a pull request.
2. **1.3.0:** the routes around the hook close, and pre-commit adoption no longer needs a clean-up first.
3. **1.4.0:** the same block works in other coding agents.
4. **1.5.0 onward:** Go, Java, Rust and other shops can use the tool at all.

**Success looks like this:**

- A blocked agent fixes the comment on its next try instead of working around the hook.
- A team adopts the tool in an existing repository the same day, without cleaning up old comments.
- The tool installs with one command.
- The tool runs in the agents and languages a typical team uses, on macOS, Linux and Windows alike.

## 2. Goals, non-goals, anti-goals

**Goals:** the items in sections 4 to 7, delivered in the release order of section 3.

**Non-goals.** These are decided out of this roadmap:

- **A rule for edit narration** ("now uses", "previously", "no longer", "changed from"). **Owner's decision: leave out.**
  Those words appear legitimately in code written before agents existed: "previously" in 77 CPython standard library
  comments, "no longer" in 86. The plan and chat references that matter are covered by the `agent-context` pack
  (item 4.3).
- A baseline or ratchet file, inline suppression, or configurable limits. Each one breaks E4. The changed-lines modes
  already act as a ratchet.
- Rules for comments that restate the next line, for commented-out code, or for a TODO without an owner. They need
  judgment or produce too many false positives, and with no suppression each false positive costs a team a whole
  excluded path.
- JSON output instead of exit 2 for Claude Code, and automatic rewriting of comments.
- A PostToolUse (after-the-write) mode, or a per-write comment budget.
- Joining comment runs separated by blank lines into one C1 block. On CPython it flagged 94 pairs, and all 10 sampled
  pairs were legitimately separate comments.
- SARIF and GitLab Code Quality output. Deferred, not rejected: SARIF on private repositories needs paid GitHub Code
  Security.
- Parallel `--all`. Deferred: the engine already runs at about 35k lines a second.
- Homebrew, and linting code fences inside Markdown.
- Outward-facing listings: Anthropic's plugin directory, the community marketplace, awesome-claude-code, SchemaStore.
  Each is a separate owner action after the release it depends on.
- An eval suite that measures the fix rate with and without the plugin. A good follow-up, but not part of this roadmap.

**Anti-goals.** Each of these is a failure even if everything technically works:

- Anything that loosens a rule or lets a repository loosen one.
- A Claude Code hook that fails open: a crash, a missing interpreter or a timeout that lets the write through.
- A message that blames the agent without telling it what to do. That is what drives agents to route around the hook.
- Promising fail-closed behaviour for an agent whose hook system can't guarantee it.
- A feature that works on one operating system and silently fails open on another.
- A verdict that changes in a patch release, or a release whose changelog doesn't say which rules or languages it
  moves.
- Any run-time dependency outside the standard library.
- Making Claude chase or rewrite the human's own comments when the human didn't ask (see item 5.1).

## 3. Constraints and release rules

The non-negotiables in `CLAUDE.md` hold for every item, in particular:

- **E1:** Python 3.9 or newer, standard library only, and `check-agent-comment-lint.py` still works from a plain
  checkout.
- **E2 and E3:** exit codes 0, 1 and 2. Exit 2 is never downgraded. In hook mode and in the shell wrapper, every non-zero
  verdict and every crash is exit 2.
- **E4:** settings can only exclude paths or add governance packs and patterns.
- **E5 and E6:** the repository's own comments follow the policy, and code lines stay at 120 characters or fewer.
- **E7:** the test comes first and is seen failing.
- **E8:** one version, in `__init__.py` and `.claude-plugin/plugin.json`.

**Every operating system (owner's decision).** Everything in this roadmap works on macOS, Linux and Windows,
native Windows included, not only WSL. That covers the engine, the CLI, the Claude Code plugin, the Action, the
pre-commit hooks and every agent template. Item 4.8 lays the foundation in 1.2.0, so every later item is built and
tested on all three.

**E3 is reworded (owner's decision).** It now reads: "In hook mode, every rejected write reaches the agent through
that agent's documented block signal, and every crash or failure to scan is exit 2." For Claude Code the block
signal stays exit 2 with the report on stderr, so nothing changes there. The new wording matters only if a live
capture shows that an agent reads its block reason only from JSON on exit 0 (section 6). Update `CLAUDE.md` when
the first such adapter lands, not before.

Also:

- The finding line `path:line: RULE: message` stays byte for byte. `tests/test_packaging.py:62` pins it, and the
  problem matcher (item 4.4) depends on it.
- A change that can move findings is at least a minor release, and its changelog entry names the rules or languages
  it moves.

**Release order. Owner's decision: "as suggested".**

| Release | Items | Moves findings? |
| --- | --- | --- |
| 1.2.0 | 4.8 every operating system (first), 4.1 the hook's changed lines, 4.2 the teaching message, 4.3 the `agent-context` pack, 4.4 PR annotations, 4.5 PyPI, 4.6 `$schema` and a schema, 4.7 documentation | Yes, in hook mode only and rarely (4.1) |
| 1.3.0 | 5.1 the end-of-session check, 5.2 `--staged`, 5.3 session-start guidance, 5.4 hooks read committed settings | Yes, in hook mode only, where a settings file has uncommitted changes (5.4) |
| 1.4.0 | 6 adapters for other agents | No |
| 1.5.0 onward | 7 new languages | Yes, once per language |

**Adapters ship before new languages (designer's call; the owner didn't object).** Adapters cost less, and the rival
already supports several agents. The counter-argument stands: a missing language shuts a whole shop out. The builder
may split 1.4.0 and 1.5.0 into smaller minor releases.

## 4. Release 1.2.0

### 4.1 The hook judges only the lines a write really changes

**Today:** `hook.changed_ranges` (`agent_comment_lint/hook.py:82-85`) runs `difflib.SequenceMatcher` over the whole file
before and after the write. That causes two problems:

- **Wrong ranges.** On a 9,999-line file with many repeated lines, a one-line insert came back as changed range
  `(2, 5000)`. Old findings inside that range then block a clean write, which breaks the promise that old comments never
  block.
- **Speed.** It took 2.8 s at 5k lines and 7.4 s at 10k. Somewhere near 28k lines of repetitive content it would pass
  the 60 s hook timeout, and with `onFailure: "block"` that file could no longer be written at all.

**Required behaviour:**

- A line that is identical before and after the write, and lies outside the region the write touched, is never
  reported as changed.
- Agents often pad `old_string` with neighbouring unchanged lines, sometimes an old comment, to make it unique. Those
  padding lines are not changed lines. Today's hook already gets this right (verified), and that must hold.
- A one-line edit to a 50,000-line file is judged in under one second **(designer's call on the number)**.

**Known-good approach:** before diffing, trim the lines the two versions share at the start and at the end, then diff
only what's left. A prototype took about 4 ms where the full diff took seconds. For Edit and MultiEdit the builder may
instead diff each `old_string` against its `new_string` and offset the result. Either is fine if the behaviour above
holds.

**Moves findings:** yes, in hook mode only and rarely. Over 10 historical revisions of this repository, the trimmed and
full diffs differed once. Name it in the changelog.

**Docs:** remove the "Known limit: the changed-line diff is quadratic…" note at `docs/reference.md:291-292`, or narrow
it if a worst case remains.

### 4.2 A block message that teaches the fix

**Today:** a blocked agent sees `x.ts:1: C1: 2-line prose block (limit 1)` and a summary. For an Edit, that line number
refers to the file after the write, which the agent never saw whole. The agent matches by text, so it needs the text.

**Required behaviour (hook mode only; the text and JSON output of other modes is unchanged):**

1. **The first line stays** `Blocked: agent-comment-lint rejects this write.`, followed by one line saying that only
   the lines this write adds or changes are judged, so comments elsewhere in the file are fine.
2. **Each finding line keeps its current form** (pinned). Under it come:
   - the offending comment lines, indented and taken from the text the write would leave, capped at 6 lines of 120
     characters **(designer's call on the caps)**;
   - one line saying how to fix that rule.
3. **The closing lines say:**
   - fix the comment and retry the same tool call;
   - splitting the comment across blank lines, or writing the file another way (Bash, a script, another tool), does
     not satisfy the policy;
   - for a Write: re-send the Write with only the comment lines changed;
   - adding an exclusion to the settings file is not the fix, because exclusions are for generated and third-party
     code. From 1.3.0 such an exclusion has no effect until a human commits it (5.4).
4. **"Could not scan" errors keep their current form.** The header from point 1 still comes first.
5. **The channel doesn't change:** exit 2, everything on stderr, nothing on stdout.

**Draft fix lines per rule (designer's call; the builder may tighten the wording, not the intent):**

| Rule | Fix line |
| --- | --- |
| C1 | Keep one line that says why the code is this way; put the rest in the commit message or the PR description. |
| C3 | Remove the reference; say what the code needs, not where the decision was recorded. |
| C5 | Shorten the assertion message to at most two lines. |
| C7 | Shorten the comment, or move it onto its own line above the code. |

**Where it lives:** the renderer needs the judged text to quote from, so it should
live with the hook path (`cli._hook_verdict`, `cli.py:331-337`) or in a hook-specific function in `report.py`.
`report.as_text` must not change for other modes.

**Tests:** `tests/test_hook.py` and `tests/test_packaging.py` (through the wrapper). Pin the header, one excerpt, the
fix line per rule and the closing lines.

### 4.3 An opt-in governance pack for plan and chat references: `agent-context`

**What:** a fourth entry in `governance.PACKS` (`agent_comment_lint/governance.py:38-42`), named `agent-context`, with
these shapes:

- `Task 8`: the word followed by a number without `#`. `task #8` is already core.
- `step 3 of the plan`, `step 3 in the plan`.
- `per the plan`, `per the spec`, `per review`, `per the code review`.
- `as requested`, `as discussed`, `as agreed`.
- `the user asked`, `the user requested`.
- An uppercase notes file name: `PLAN.md`, `INTERNAL_NOTES.md`, `TODO.md`. `README`, `CHANGELOG`, `LICENSE`,
  `CONTRIBUTING`, `SECURITY` and `CODE_OF_CONDUCT` are exempt. `CLAUDE.md` and `AGENTS.md` are already core.

**Precision bar:** the architect ran these shapes over 149,996 comments in the CPython standard library, written before
agents:

- Zero hits for `Task N`, `step N of the plan` and uppercase `.md`.
- One hit each for `per … review/plan/spec`, `as requested` and `the user asked`. The last one was the end-user sense.

The builder pins the six real agent examples as true positives:

- "Task #1775" (already caught by core)
- "The user asked for it gone."
- "now reads useDataTypes() itself (Task 8)"
- "(moved to ./phaseStepper.ts …)"
- "See INTERNAL_NOTES.md section 4"
- "Step 3 of the plan"

The "(moved to …)" example is edit narration, which is out of scope, so it is expected to stay clean. The test should
say so. The builder also pins a handful of the legitimate CPython hits as true negatives where the pattern can avoid
them, and as known false positives in `tests/test_known_false_positives.py` where it can't.

**Case:** case-insensitive for the multi-word phrases. Capital `T` only for `Task N`, unless corpus evidence supports
more **(designer's call)**.

**Opt-in only in this roadmap.** Moving any of these shapes into core would move findings, so it is a later, separate
decision **(designer's call)**.

**Docs:** the pack tables in README and `docs/reference.md`, and the settings examples.

### 4.4 Inline pull request annotations

**Today:** the Action prints plain text (`action.yml:25-35`). Reviewers see a failed check, not annotations on the
offending lines.

**What:**

- Ship a GitHub problem matcher file with the Action, using the pattern `^(.+?):(\d+): (C\d+): (.+)$` with file,
  line, code and message. The architect tested it against real output: it matches findings and skips the summary and
  "could not scan" lines.
- The composite step registers the matcher (`::add-matcher::`) before the run and removes it after. The current
  `exec` lines need restructuring so the removal runs and the exit code is kept.
- GitHub shows at most 10 error annotations per step and drops the rest silently. When there are findings, the step
  also writes the full text report to `$GITHUB_STEP_SUMMARY` **(designer's call)**.
- README: a reviewdog recipe that needs no code change:
  `reviewdog -efm="%f:%l: %m" -reporter=github-pr-review -filter-mode=added`. It gives inline review comments with no
  cap.

**Must not change:** the Action's exit codes, its inputs, or the self-gate job in `.github/workflows/ci.yml`.

### 4.5 Publish to PyPI with trusted publishing

**Why:** a one-command install (`uv tool install agent-comment-lint`, `pipx install agent-comment-lint`) and a one-line
trial (`uvx agent-comment-lint --diff origin/main`). Section 6 needs it, because other agents' hooks call an installed
command. The name `agent-comment-lint` was unclaimed on PyPI and npm on 2026-10-28.

**What:**

- `release.yml` gets a publish job after the existing release job. It uses `pypa/gh-action-pypi-publish` with OIDC
  (`id-token: write`) in a GitHub environment named `pypi`, and uploads the `dist/` the release job already builds,
  passed between jobs as an artifact. That action attaches PEP 740 attestations by default.
- The first PyPI release is 1.2.0. 1.1.0 is not back-published **(designer's call)**.
- README install section:
  - PyPI first, pinned (`agent-comment-lint==1.2.0`); the git URLs stay as an alternative.
  - Hooks call the installed bare command. `uvx` is for CI and trials only, because it resolves the package on every
    call and adds latency to every write.

**Owner actions, outward-facing, in the plan as explicit stop-and-ask steps:**

- Create a pending trusted publisher on pypi.org: owner `OrodruinLabs`, repository `agent-comment-lint`, workflow
  `release.yml`, environment `pypi`.
- Create the `pypi` environment in the GitHub repository settings.
- Push the `v1.2.0` tag, which publishes.

### 4.6 Accept `$schema`, and publish a schema for the settings file

**Today:** `config.parse` (`agent_comment_lint/config.py:105`) rejects any key other than `exclude` and `governance`, so
an editor-friendly `"$schema"` line makes the file invalid (exit 2).

**What:**

- `parse` accepts a top-level `$schema` whose value is a string, and ignores it. Any other unknown key is still exit 2.
- Ship a JSON Schema for `.agent-comment-lint.json` in the repository: the two keys, required reasons, the pack names
  as an enum, and the optional `$schema`.
- A test checks that the schema's pack enum equals `governance.PACKS`, so the schema can't drift from the code.
- README and `docs/reference.md` show a `$schema` line that points at the raw file on a version tag.

**Left to the builder:** the schema draft version (draft-07 has the widest editor support) and the file location.

### 4.7 Documentation for 1.2.0

- A short positioning line near the top of README: "Your CLAUDE.md asks; this enforces." Don't name the rival
  **(designer's call)**.
- A known gap, in `docs/reference.md`: a C1 block can be split by blank lines into separate one-line blocks, and each
  passes. Joining such runs was measured and rejected (section 2). The teaching message (4.2) and the end-of-session
  check (5.1) are the answer. It can't be pinned as a test the way the known false positives are, so it is documented
  instead.
- A changelog entry naming what 4.1 moves.

### 4.8 Every operating system: macOS, Linux and Windows

**Owner's decision:** the tool must work on every operating system. Today:

- CI runs only on Ubuntu.
- The Claude Code wrapper is POSIX `sh` and looks only for `python3`.
- Some tests assume POSIX paths.
- The README tells Windows users nothing.

Do this item first in 1.2.0, so every later item is built and tested on all three systems.

**Required behaviour:**

- **CI.**
  - The suite and `--all` run on `windows-latest` and `macos-latest` as well as Ubuntu. On those two, Python 3.9
    and 3.13 are enough; the full 3.9 to 3.13 matrix stays on Ubuntu **(designer's call)**.
  - The install smoke test, including a dirty hook event exiting 2, runs on all three.
  - The Action's self-test runs on a Windows runner and a macOS runner.
- **Paths.** Output and exclusion matching use `/` on every operating system, so a report and a settings file mean
  the same thing everywhere. The hook accepts Windows `file_path` values: drive letters, backslashes, and case
  differences that the file system ignores.
- **Line endings.** A file with Windows line endings is judged the same as with `\n`. The hook's existing handling
  stays.
- **Finding Python.** The Claude Code wrapper tries `AGENT_COMMENT_LINT_PYTHON`, then `python3`, then `python`,
  then `py -3`. It accepts only an interpreter that actually runs and is 3.9 or newer, which rejects the Windows Store
  `python3` stub. If none is found, the write is blocked, as today.
- **The plugin on Windows.** Check how Claude Code on native Windows runs a plugin's hook command: through Git
  Bash, `cmd` or PowerShell. Ship whatever wrapper keeps E3 there. A missing interpreter, a missing project directory
  and a crash are all blocked writes.
- **The Action.** The Action finds the interpreter on all three runner types instead of assuming `python3`.
- **Tests.** A test is skipped on Windows only when it covers genuinely POSIX-only behaviour, and the skip says why.

**Owner action, a stop-and-ask step:** one live blocked write through the Claude Code plugin on a Windows machine
before README claims Windows support.

**Moves findings:** no; verdicts on Linux and macOS stay the same.

**Docs:** README states the supported operating systems and the interpreter lookup order.

## 5. Release 1.3.0

### 5.1 An end-of-session check that judges only what changed during the session

**Today:** the plugin's PreToolUse matcher covers only `Write|Edit|MultiEdit` (`hooks/hooks.json:6`). A file written
through Bash (`tee`, a heredoc, `python -c`) or through an MCP file tool never reaches the check, and agents do this
after being blocked a few times. Both holes were verified:

- A Bash tool event passes `--hook` with exit 0.
- `--diff HEAD` on a working tree with two violating files reports "clean, 0 file(s) scanned", because `diff_span`
  covers only `BASE...HEAD` (`gitio.py:71-79`).

**Owner's decision:** the check judges only what changed since the session started, not everything uncommitted. A
human's own half-written files and old comments must not keep Claude working.

**Required behaviour:**

- **Snapshot at session start.** A plugin `SessionStart` entry records the working tree's state for that
  session's `session_id`:
  - tracked files, staged and unstaged;
  - every untracked, non-ignored covered file, with the content it had.

  The snapshot lives outside the working tree, so it adds no untracked noise, and old snapshots are cleaned up. The
  mechanism is left to the builder; `git stash create` plus blob ids of untracked files is one known-good shape.
- **Check at stop.** A plugin `Stop` entry judges every covered file whose content differs from the session's
  snapshot, on the lines changed since the snapshot:
  - a file new since the snapshot is judged whole;
  - a file unchanged since the snapshot is never read, so a broken file the session never touched can't block;
  - a file that changed during the session and can't be scanned blocks, under E2.
- **On findings, exit 2 with the 4.2 teaching report**, opening with a line like "Before you finish: …". Claude Code
  then keeps Claude working.
- **No snapshot, no check.** If the session has no snapshot (the plugin was installed mid-session, a resumed
  session, or taking the snapshot failed), the Stop check lets the session end. The write-time hook remains the main
  guard. Taking the snapshot never blocks or slows a session start in a way the user notices.
- **Outside a git repository** there is no snapshot, so the session ends normally. Where a repository is claimed but
  git fails at stop, the check blocks (exit 2).
- **Scope.** The project directory's own working tree only. Sibling worktrees aren't covered **(designer's call)**.
- **Known, documented limit:** edits a human makes in their editor during the session count as session changes.
- **On by default** for every plugin user **(designer's call)**.
- **`onFailure` does not apply to Stop hooks**, so the wrapper's "every failure is exit 2" rule carries E3 here.
  The wrapper from 4.8 already does that on every operating system.
- **No bypass is built on `stop_hook_active`.** Claude Code caps forced continuations at 8 in a row.
- **Every operating system**, like everything else (4.8).

**Interface (left to the builder):** one way is for `--hook` to dispatch on the event's `hook_event_name`
(`PreToolUse`, `SessionStart`, `Stop`), so the plugin keeps a single entry point. A separate CLI mode is also fine.
Don't add a general `--uncommitted` mode unless the design needs it.

### 5.2 A `--staged` mode and a second pre-commit hook id

**Today:** the pre-commit hook judges each staged file whole (`.pre-commit-hooks.yaml:1-7`), so the README tells teams
to fix or exclude old findings first. That is the main obstacle to adoption.

**What:**

- **A `--staged` mode.** Changed ranges come from `git diff --cached` in the pinned shape. The text comes from the
  index (`git show :path`), not the working tree, so a partially staged file is judged as it will be committed, also
  from a plain git hook outside pre-commit.
- **A new hook id `agent-comment-lint-staged`** with `entry: agent-comment-lint --staged`, `pass_filenames: false`, and
  the same `files:` filter, so it is skipped when no covered file is staged.
- **The existing `agent-comment-lint` id is unchanged**, so no verdict moves. README recommends the staged id for
  existing repositories.
- **Shared plumbing:** builds on the git work from 5.1. If 5.1 lands first, this item is small.

### 5.3 One or two lines of guidance at session start

**What:** a `SessionStart` entry in the plugin's `hooks/hooks.json` that adds one or two positive lines to Claude's
context. Draft **(designer's call)**:

> Comments here are at most one line and say why the code is the way it is. Notes for reviewers go in the commit
> message or the PR description, not in code.

**Constraints:**

- The guidance is static text with no Python call, so it can't slow down or break a session start. The 5.1
  snapshot is a separate `SessionStart` entry.
- Kept to two lines: context files add cost and can lower success rates.
- Claude Code re-sends this context after compaction and `/clear`.

**Release placement (designer's call):** 1.3.0, alongside the other `hooks.json` changes.

### 5.4 The hook and the end-of-session check read committed settings

**Today:** `_run_hook` loads `.agent-comment-lint.json` from the working tree. The hook lets `.json` writes through.
So a blocked agent can add an exclusion for the file it is writing, give a reason, and pass on its retry.

**Owner's decision:** in the Claude Code hook and the end-of-session check, settings come from the committed file at
`HEAD`. An exclusion an agent adds takes effect only once a human commits it, which is how CI already behaves.

**Required behaviour:**

- `--hook` and the Stop check read the settings file as committed at `HEAD` in the judged root.
- No committed settings file means the defaults, even if one exists on disk.
- A committed file that is malformed is exit 2, as today.
- **Outside git, or where `HEAD` doesn't exist yet,** the file on disk is read, as today **(designer's call:**
  there is nothing committed to prefer).
- **An explicit `--config FILE`** in the hook command is read from disk, because a human set it.
- `--diff`, `--all`, `--files`, `--stdin-path` and `--staged` keep reading the file on disk.

**Moves findings:** yes, in hook mode only, where the settings file has uncommitted changes. Name it in the
changelog.

**Docs:** `docs/reference.md` and README say that a new exclusion reaches the hook only after it is committed.

## 6. Release 1.4.0: hook adapters for other agents

**What:** `--hook` gains `--agent NAME`, defaulting to `claude` so nothing changes for Claude Code. `hook.target`
(`hook.py:15-28`) becomes a normalizer: each agent's event turns into a list of writes, each a path plus either a full
text or edits. One event can carry several files (a Codex patch). The judging path after that is shared.

**Order, and what each agent sends (from the research, dated 2026-10-28):**

| Order | Agent | Pre-write event | Payload | Fail-closed on a crash or timeout |
| --- | --- | --- | --- | --- |
| 1 | Copilot (CLI and cloud agent) | `preToolUse`, or `PreToolUse` with a Claude-shaped payload | `toolName` / `toolArgs`, or Claude's own | Partial: errors block, timeouts let the write through |
| 2 | Windsurf / Devin | `pre_write_code` | `tool_info.file_path`, `edits[{old_string, new_string}]`, mapping onto the MultiEdit path | No |
| 3 | Kiro | `PreToolUse`, `fs_write` | `command` (`create`, `str_replace`, `insert`, `append`), `path`, `file_text`, `old_str`, `new_str` | Undocumented |
| 4 | Cursor | `preToolUse`, matcher `Write` | `file_path`, `content`; the edit shape is unverified | Yes, with `failClosed: true` |
| 5 | Codex CLI | `PreToolUse`, `apply_patch` | patch text in `tool_input.command` | Undocumented |
| 6 | Gemini CLI | `BeforeTool`, `write_file\|replace` | `file_path`, `content`; or `old_string`, `new_string`, `allow_multiple` | No |

**For each agent:**

- A normalizer with tests built from a captured or documented event.
- A config template in the repository, under a directory such as `integrations/<agent>/`. For Copilot's cloud agent
  that is a `.github/hooks/*.json` template.
- A README section. Every template calls the installed command (item 4.5) behind a guard that turns a missing
  command into a block on every operating system. That means a POSIX shell guard for macOS and Linux and a
  PowerShell or `cmd` guard for Windows, or one cross-platform launcher. The builder chooses; either way it is tested
  on all three.

**Rules that apply across agents:**

- **Be honest about fail-closed.** README carries the table's last column, per agent and per operating system. Fail-closed is promised only
  where the agent offers a setting for it. That's the anti-goal in section 2.
- **Verify before building output shims.** Cursor and Copilot document a JSON field as the channel to the model, not
  stderr. Capture one real blocked write in each and check whether the stderr report reaches the model. Build a JSON
  output shim for that agent only if it doesn't. Under the reworded E3 (section 3), a shim may signal a rejected
  write with the agent's documented JSON on exit 0 if the capture shows that is how the agent reads the reason.
  Crashes and failures to scan stay exit 2. Capture a real Cursor edit payload before writing its edit normalizer.
- **Codex patches.** Hunks carry no line numbers, the parser accepts lenient markers, and the patch can arrive wrapped
  in a heredoc (grammar: `codex-rs/apply-patch/src/parser.rs`). The invariant follows E2: a patch the engine cannot
  apply and judge is never let through, unless Codex itself would refuse it. When unsure, block with a message that
  names the cause.
- **Gemini comes last**, because the consumer CLI moved to Antigravity on 2026-06-18. Confirm the event names there
  before building.

**Live captures are owner steps (designer's call).** Some of these agents need paid accounts. Every live capture and
every live blocked write is a stop-and-ask step for the owner in the plan. An agent with no capture yet is deferred, and
README does not claim support for it.

**Left to the builder:** splitting 1.4.0 into several minor releases, including by which captures are available.

## 7. Release 1.5.0 onward: more languages

**What:**

- **One configurable character lexer for the C family**, modeled on `lexers/javascript.py`, not on the
  line-at-a-time `linescan.py`. Each language becomes a small `Family` describing:
  - line and block comment markers, with nesting where the language allows it (Rust, Swift, Kotlin);
  - string kinds: Go raw strings in backticks, Rust `r#"…"#`, Java, Kotlin and Swift text blocks;
  - character literals, without misreading Rust lifetimes (`'a`);
  - doc-comment markers.
- **Hash-comment languages through or alongside `lexers/hashlike.py`**, each with its own edge cases:
  - **Ruby:** `#{}` inside strings, `=begin`/`=end`, `<<~` heredocs.
  - **TOML:** `#` inside strings.
  - **Dockerfile:** `#` is a comment only at the start of a line, and `# syntax=` parser directives exist.
  - **Makefile:** files are named without an extension (`Dockerfile`, `Makefile`), so `family_for` needs a name match,
    not only a suffix match.
- **A test that the `files:` regex in `.pre-commit-hooks.yaml` matches `EXTENSIONS` exactly.** Nothing enforces that
  today.

**Order (designer's call):**

1. The cheap hash-comment languages (Ruby, TOML, Dockerfile, Makefile).
2. The C-family lexer with Go, Java and Rust.
3. Kotlin, Swift and C/C++.

**Doc comments under C1.** Each new language's doc comments follow the same principle the existing languages use:

- A complete one-line tag doesn't count as prose: Javadoc and KDoc `@param` lines, as JSDoc's do today.
- Everything else in a doc comment block is prose under C1.

Where a language's own convention forces several prose lines, as with Go package docs, Rust crate docs and doctest
examples, that is a policy call the builder brings back to the owner rather than settling alone. See section 9,
question 2.

**Moves findings:** yes, once per language. Each language is at least a minor release, with a changelog entry naming
it, and the README scope table and logo grid updated.

## 8. Verification for every release

- The full suite on Python 3.9 to 3.13 on Linux, and on Windows and macOS as 4.8 sets out, and
  `check-agent-comment-lint.py --all` clean.
- `claude plugin validate .` passes.
- The versions in `__init__.py` and `plugin.json` agree, and the changelog entry names what moved.
- Hook items: a live test in Claude Code. A violating write is blocked with the new message, and the retry passes.
- 1.3.0: the Stop check catches a violating file written through Bash during the session, and ignores a violating
  file that was already uncommitted before the session started.
- Windows: one live blocked write in Claude Code on Windows per release that touches the hook (an owner step).
- 1.4.0: one live blocked write per agent before its README section claims support.
- 1.2.0: the first PyPI publish is checked with `uvx agent-comment-lint==1.2.0 --version`.

## 9. Owner decisions and open questions

Decided on 2026-10-29:

1. **Edit narration:** leave out (section 2).
2. **Release order:** as suggested (section 3).
3. **End-of-session check:** judges only what changed since the session started; no snapshot means no check (5.1).
4. **Settings:** the hook and the Stop check read committed settings (5.4).
5. **Operating systems:** everything works on macOS, Linux and Windows (4.8, and section 6 templates).
6. **E3:** reworded so a rejected write reaches each agent through its documented block signal, and crashes stay
   exit 2 (section 3).

Ruled on 2026-10-29 by the builder, under the owner's standing instruction to decide rather than ask. The owner can
override this before v1.6.0 is tagged:

7. **Doc comments in new languages (section 7): C1 applies unchanged.** A doc comment block holds one prose line.
   A complete one-line `@tag` doesn't count, as with JSDoc. Lines inside a fenced example are not exempt, because
   exempting them would not help in practice: a Rust `# Examples` heading is itself a second prose line, so the
   block would fail either way. Multi-line Javadoc, Go package docs and Rust `///` docs are blocked, as Python
   docstrings and JSDoc already are. The order stays Go, Java and Rust, then Kotlin, Swift and C/C++.

## 10. Left to the builder

- **Code structure:**
  - module boundaries;
  - where the hook renderer lives;
  - the normalizer's shape;
  - the lexer's configuration format;
  - file locations for the matcher, the schema and the integration templates.
- **Release mechanics:**
  - the exact wording of messages, within the intents above;
  - how releases 1.4.0 onward are split;
  - test layout.
