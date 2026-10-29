# Where each agent fixture came from

A captured event replaces a documented one. Until then, each line says what the fixture was built from.

- `codex-write.json`: documented (developers.openai.com/codex/hooks + codex-rs apply_patch.rs), constructed 2026-10-29; replace with a capture
- `codex-edit.json`: documented (developers.openai.com/codex/hooks + codex-rs apply_patch.rs and parser.rs), constructed 2026-10-29; replace with a capture
- `codex-delete.json`: documented (developers.openai.com/codex/hooks + codex-rs apply_patch.rs and parser.rs), constructed 2026-10-29; replace with a capture
- `codex-heredoc.json`: documented (developers.openai.com/codex/hooks + codex-rs parser.rs lenient heredoc), constructed 2026-10-29; replace with a capture
- `codex-read.json`: documented (developers.openai.com/codex/hooks: shell commands reach hooks as `Bash` with `tool_input.command`), constructed 2026-10-29; replace with a capture
- `codex-pathless.json`: `codex-write.json` with `tool_input.command` removed, constructed 2026-10-29; rebuild it from the write capture
