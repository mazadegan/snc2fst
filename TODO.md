# TODO

## Near-term
- Add a tokenizer for input sentences that tokenizes by characters listed in `alphabet.csv`.
- Add support for running `snc2fst eval/compile .`:
  - Scan the current directory for `snc2fst.toml`.
  - Read paths for `alphabet.csv`, `rules.toml`/`rules.json`, and `input.toml`/`input.json` from that config.
  - If config entries are missing (or config is absent), fall back to discovering those files in the current directory.
- Add a less painful way to specify underspecified segments in `alphabet.csv` (possibly via intersection-based notation/workflow).

## Long-term
- Add a `gui` command that opens an ImGui interface for working with this project.
