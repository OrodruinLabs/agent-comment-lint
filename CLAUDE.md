# agent-comment-lint

A zero-dependency gate that stops AI coding agents from bloating code comments, shipped four ways from this one repository: a command (`pyproject.toml`), a
pre-commit hook (`.pre-commit-hooks.yaml`), a GitHub Action (`action.yml`) and a Claude Code plugin
(`.claude-plugin/`, `hooks/`).

`docs/reference.md` is the contract: the rules, the modes, the exit codes, the settings file, and what the lexers
know. `README.md` summarises it. Read the reference before you change behaviour. When behaviour changes, update both
in the same pull request.

## Commands

```
python3 -m unittest discover -s tests                         # full suite, about two minutes
python3 -m unittest discover -s tests -p 'test_cli.py' -k X   # one file, optionally one class or test
python3 check-agent-comment-lint.py --all                     # the engine over this repository
python3 check-agent-comment-lint.py --diff origin/main        # only what the branch changes (commit first)
claude plugin validate .                                      # the plugin and marketplace manifests
```

- `python3 -m unittest tests.test_cli` fails with "No module named 'support'". Use `discover -p` instead.
- CI runs the suite on Python 3.9 to 3.13. To run one version locally: `uv run --no-project --python 3.9 python -m
  unittest discover -s tests`.

## Non-negotiables

| # | Rule |
|---|---|
| **E1** | Python 3.9 or newer, standard library only at run time. `check-agent-comment-lint.py` keeps working from a plain checkout with no install. |
| **E2** | Exit codes are 0 clean, 1 violations, 2 could not scan. Exit 2 is never downgraded to a pass. Anything the engine cannot judge honestly is exit 2 with a message that names the cause. |
| **E3** | In `--hook` mode, and in `hooks/agent-comment-lint-hook.sh`, any non-zero verdict and any crash is exit 2. Claude Code treats every other exit code as "let it through". |
| **E4** | No configurable limits and no inline suppression. Settings can only exclude paths, or add governance packs and patterns, each with a reason. Nothing in settings can loosen a rule. |
| **E5** | Comments in this repository follow the policy it enforces: at most one prose line per block, no governance references, lines with a comment at most 120 characters. `--all` must be clean. |
| **E6** | Code lines in `agent_comment_lint/` and `tests/` stay at 120 characters or fewer, even though C7 only judges commented lines. |
| **E7** | Every behaviour change comes with a test written first and seen failing. The known false positives in `tests/test_known_false_positives.py` are pinned on purpose: changing one is a decision, not a fix. |
| **E8** | One version, in `agent_comment_lint/__init__.py`, repeated in `.claude-plugin/plugin.json`. `tests/test_packaging.py` and the release workflow check they agree. |

## Releasing

1. Bump `__version__` and `.claude-plugin/plugin.json` together, and add the changelog entry.
2. A change that can move findings is at least a minor release, and its changelog entry names the rules or languages
   it moves.
3. Before the first tag that publishes to PyPI, do the one-time setup. On pypi.org create a pending trusted publisher
   (owner `OrodruinLabs`, repository `agent-comment-lint`, workflow `release.yml`, environment `pypi`). In the GitHub
   repository settings create the `pypi` environment, ideally with a required reviewer. If an upload fails, re-run the
   failed `pypi` job; the GitHub release and tag stay.
4. Merge, then tag `vX.Y.Z` on `main`. `release.yml` checks the versions, runs the suite, builds, and creates the
   GitHub release.
