# TODO

## Near-term
- [x] Add a tokenizer for input sentences that tokenizes by characters listed in `alphabet.csv`.
- [x] Add support for running `snc2fst eval/compile .`:
  - Scan the current directory for `snc2fst.toml`.
  - Read paths for `alphabet.csv`, `rules.toml`/`rules.json`, and `input.toml`/`input.json` from that config.
  - If config entries are missing (or config is absent), fall back to discovering those files in the current directory.
- [x] Add underspecified segment support via `snc2fst.toml` `[segments]` DSL (e.g., `intersect`, `sym`) with configurable allowed ops.
- Add a less painful UX/tooling workflow for authoring underspecified segments (builder/validator/export), beyond manual DSL editing.

## Long-term
- Add a `gui` command that opens an ImGui interface for working with this project.
