# snc2fst

`snc2fst` compiles Search & Change rules into FSTs over a
ternary-feature alphabet and provides CLI tools for validation, compilation,
and evaluation.

This project compiles canonicalized/merged transducers.

## Quickstart

```
conda env create -f environment.yml
conda activate snc2fst
snc2fst --help
```


## Direction handling

The compiler emits a single canonical **LEFT** machine. For **RIGHT** rules,
`snc2fst eval` applies a reversal wrapper (reverse input, run the
machine, then reverse output). This keeps compilation consistent while still
allowing both directions at runtime.

## Feature encoding

Features have ternary polarity:

- `0` = unspecified
- `+` = plus
- `-` = minus

A bundle over `V` is a tuple of ternary values in the same order as in `V`. 
Labels are encoded in base‑3 with label 0 reserved for epsilon.

## Alphabet format

Alphabet files are CSV/TSV feature tables:

- first row: empty leading cell, then symbol names
- first column: feature names
- cells: `+`, `-`, or `0` (unspecified)

Example:

```csv
  ,A,B,C
F1,+,-,0
F2,0,+,-
```

## Setup (Conda)

### Prerequisites

- Conda installed (Miniconda, Anaconda, or Mambaforge). Conda is the supported
  install path.

### Create and activate the environment

From the project root:

```
conda env create -f environment.yml
conda activate snc2fst
```

If you change dependencies later, update the environment with:

```
conda env update -f environment.yml --prune
```

### Python versions

Conda manages Python versions per environment. To use a different Python
version, create a separate env or update this one:

```
conda create -n snc2fst-py311 python=3.11
conda activate snc2fst-py311
```

Or update the current env in place:

```
conda install -n snc2fst python=3.12
```

### Editable install (already included)

`environment.yml` installs the project in editable mode via `pip -e .`, so the
`snc2fst` CLI is available immediately and changes to `src/` are reflected
without reinstallation.

### Verify the install

```
snc2fst --help
```

### Conda install

```
conda install mazadegan::snc2fst
```

## CLI quickstart

### Generate sample files

```
snc2fst init samples/
```

## Example rules.toml

```toml
id = "sample_rules"

[[rules]]
id = "spread_f1_right"
dir = "RIGHT"
inr = [["+", "F1"]]
trm = [["+", "F2"]]
cnd = []
out = "(proj TRM (F1))"
```

### Out DSL

The `out` field is a tiny DSL that composes feature bundles from `INR` and `TRM`
using `bundle`, `proj`, `unify`, and `subtract`. It exists so rules can describe
the Out function declaratively without having to evaluate user-generated Python 
or having a huge JSON schema that’s horrifying to look at.

Examples:

```
(proj TRM (Voice))
(unify (subtract (proj TRM *) (proj TRM (Voice))) (proj INR (Voice)))
(bundle (- Voice))
```

Signatures:

```
(bundle (<+|-> <Feature>) ...)
(proj <INR|TRM|expr> (<Feature> ...|*))
(unify <expr> <expr>)
(subtract <expr> <expr>)
```

Notes:

- Bare `INR`/`TRM` are allowed and refer to the restricted bundle over `V`.
- Use `(proj ...)` to select features explicitly.
- `(proj TRM *)` expands V and P to the full alphabet feature set (larger FST).
- `(proj INR *)` expands V to the full alphabet feature set.

### Validate files

Rules validation requires an alphabet:

```
snc2fst validate rules samples/rules.toml samples/alphabet.csv
```

Validate an alphabet file:

```
snc2fst validate alphabet samples/alphabet.csv
```

Validate input words:

```
snc2fst validate input samples/input.toml samples/alphabet.csv
```

### Compile a rule to AT&T + symtab

> Uses `pynini`/`pywrapfst`.

```
snc2fst compile samples/rules.toml samples/alphabet.csv samples/rule.att
```

Compile and also emit a binary FST (requires `pynini`):

```
snc2fst compile samples/rules.toml samples/alphabet.csv samples/rule.att --fst
```

Optimize the compiled FST before writing output:

```
snc2fst compile samples/rules.toml samples/alphabet.csv samples/rule.att --optimize
```

When the rules file contains multiple rules, omit `--rule-id` to compile all
of them. In that case, `output` is treated as a directory and each rule is
written as `{rule_id}.att`, `{rule_id}.sym`, and (if `--fst` is set)
`{rule_id}.fst`.

`compile` requires the alphabet argument.

Show progress bar when generating large FSTs:

```
snc2fst compile samples/rules.toml samples/alphabet.csv /tmp/rule.att --progress
snc2fst compile samples/rules.toml samples/alphabet.csv /tmp/rule.att -p
```

Guard against accidental blow‑ups (default --max-arcs is 5 million):

```
snc2fst compile samples/rules.toml samples/alphabet.csv /tmp/rule.att --max-arcs 1000000
```

### Evaluate input words

Input format is TOML: a table with an `inputs` array, where each word is a list
of segment symbols from the alphabet. JSON files are still accepted.

Rules files include a top-level `id` plus a `rules` array:

```toml
id = "rules_id"

[[rules]]
id = "rule_1"
dir = "LEFT"
inr = []
trm = []
cnd = []
out = "(subtract INR (proj INR (F1)))"
```

### Build CLI docs

The CLI reference is built with Sphinx.

```
python -m pip install -e ".[docs]"
# make sure to use the env python
python -m sphinx -b html docs docs/_build/html
```

Example `input.toml`:

```toml
inputs = [
  ["0", "A", "B", "C", "D"],
  ["J", "K", "L"],
  ["T", "U", "V", "W", "X", "Y", "Z"],
]
```

Example `output.json` (default):

```json
[
  ["D", "A", "B", "C", "D"],
  ["J", "K", "L"],
  ["T", "U", "V", "W", "X", "Y", "Z"]
]
```

By default, `eval` applies **all rules in order**, feeding each rule's output
into the next rule's input. Use `--rule-id` to evaluate a single rule.

The output is a table with the original inputs and one row per rule:

```json
{
  "id": "rules_id",
  "inputs": [["0", "A"], ["B"]],
  "rows": [
    {"rule_id": "rule_1", "outputs": [["0", "A"], ["B"]]}
  ]
}
```

Example with `--include-input`:

```json
{
  "id": "rules_id",
  "inputs": [
    ["0", "A", "B", "C", "D"],
    ["J", "K", "L"],
    ["T", "U", "V", "W", "X", "Y", "Z"]
  ],
  "rows": [
    {
      "rule_id": "spread_f1_right",
      "input": [
        ["0", "A", "B", "C", "D"],
        ["J", "K", "L"],
        ["T", "U", "V", "W", "X", "Y", "Z"]
      ],
      "output": [
        ["D", "A", "B", "C", "D"],
        ["J", "K", "L"],
        ["T", "U", "V", "W", "X", "Y", "Z"]
      ]
    }
  ]
}
```

```
snc2fst eval samples/rules.toml samples/alphabet.csv samples/input.toml --output samples/out.json
```

If `--output` is omitted, the default is `<rules_id>.out.<format>` next to the rules file.

Include input + output in the result:

```
snc2fst eval samples/rules.toml samples/alphabet.csv samples/input.toml --output samples/out.json --include-input
```

Strict symbol mapping (error if output bundle has no matching symbol in alphabet):

```
snc2fst eval samples/rules.toml samples/alphabet.csv samples/input.toml --output samples/out.json --strict
```

Use the Pynini backend and compare to the reference evaluator (`--compare` implies `--pynini`):

```
snc2fst eval samples/rules.toml samples/alphabet.csv samples/input.toml --output samples/out.json --pynini --compare
```

Select an output format (default: `json`):

```
snc2fst eval samples/rules.toml samples/alphabet.csv samples/input.toml --format txt
snc2fst eval samples/rules.toml samples/alphabet.csv samples/input.toml --format csv
snc2fst eval samples/rules.toml samples/alphabet.csv samples/input.toml --format tsv
```

### Inspect V and P

Print the feature sets used to build the machine:

```
snc2fst eval samples/rules.toml samples/alphabet.csv samples/input.toml --output samples/out.json --dump-vp
snc2fst validate rules samples/rules.toml samples/alphabet.csv --dump-vp
```

## License

Apache-2.0. See `LICENSE`.

## Testing

Make sure your conda environment is active:

```
conda activate snc2fst
```

Run the full test suite (stress tests excluded by default):

```
pytest
```

Run the smoke test:

```
pytest -m smoke
```

Include stress tests:

```
pytest --stress-test
```

Show the stress-test progress bar (pytest captures output unless `-s` is used):

```
pytest --stress-test -s
```

Adjust stress-test sizes:

```
pytest --stress-test \
  --stress-rules 50 \
  --stress-words 400 \
  --stress-max-len 20
```

## Backends

`eval` can run two backends:

- **reference** (default): direct S&C interpreter
- **Pynini** (`--pynini`): OpenFst via Pynini/pywrapfst
Use `--compare` to cross‑check outputs.

## Performance tips

- Keep `|V|` and `|P|` small; arc count scales as `(1 + 3^|P|) * 3^|V|`.
- If you hit the arc limit, reduce features or raise the arc limit using `--max-arcs`.

## Troubleshooting

- **"Evaluation requires an alphabet"** → provide the `alphabet` argument.
- **"Unknown symbol"** → input contains symbols not in the alphabet.
- **"--max-arcs exceeded"** → reduce features or raise `--max-arcs`.
