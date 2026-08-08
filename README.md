# snc2fst

## Installation

```bash
conda install -c conda-forge mazadegan::snc2fst
```

## Rule DSL

Rules are written in `config.toml` under `[[rules]]`.  `Inr` describes the
target window, `Trm` describes the trigger/terminator window, `Dir` is `L` or
`R`, and `Out` is the replacement expression.

```toml
[[rules]]
Id = "R1"
Dir = "L"
Inr = [["-Syllabic"], ["+Strident"]]
Trm = [[]]
Out = "(INR[1] &E INR[2])"
```

`Inr` and `Trm` are sequences of natural classes.  Each inner list describes
one segment position:

- `["+F", "-G"]` matches a segment that is `+F` and `-G`.
- `[]` matches any segment.
- `"*F"` matches either `+F` or `-F`, but not a segment where `F` is
  unspecified. It can be combined with ordinary feature requirements, as in
  `["*F", "+G"]`.

A natural-class sequence matches a word position by position. For example,
`Inr = [["+F"], ["-G"]]` matches exactly two adjacent segments: the first must
be `+F`, and the second must be `-G`. The same idea is used inside expressions
with bracket syntax: `[{+F} {-G}]` is a two-position natural-class sequence,
and `(in? TRM [{+F} {-G}])` is true only when `TRM` has that shape. Use
`Trm = []` for no trigger window; use `Trm = [[]]` for a one-segment trigger
that can be any segment.

`Out` and optional `Cnd` expressions are written over the currently matched
windows:

- `INR` and `TRM` refer to the whole target and trigger windows.
- `INR[1]` selects one segment. Indices are 1-based.
- `INR[1:3]` selects an inclusive slice, here positions 1 through 3.
- Parentheses concatenate expressions, so `(INR[2] INR[1])` metathesizes a
  two-segment target and `(INR[1:4] INR[2:4])` duplicates a slice.
- `&A` inserts the named segment `A` from the alphabet.
- `{+F -G}` creates an underspecified segment with those feature values.

Supported operations are:

- `(unify INR[1] {+F})` unifies a segment with the given feature values.
- `(subtract INR[1] {-G})` removes matching feature values from a segment.
- `(proj TRM[1] (Voice Back))` keeps only the named features from a segment.
- `(in? TRM [{+F} {-G}])` tests whether a word belongs to a natural-class
  sequence.
- `(if CONDITION THEN ELSE)` chooses between two expressions.

Whitespace is ignored, and `;` starts a line comment inside `Out` or `Cnd`.
Feature bundles and natural-class sequences are space-separated, not
comma-separated: write `{+F -G}` and `[{+F} {-G}]`.

## Developer Notes

### Setup

```bash
pip install -e .
```

### Releasing a new version

1. Bump the version in `pyproject.toml` and `conda-recipe/meta.yaml`.

2. Build the conda package:

```bash
conda-build conda-recipe -c mazadegan -c conda-forge -c defaults
```

3. Test the local build before uploading:

```bash
conda install ~/miniforge3/envs/snc2fst/conda-bld/noarch/snc2fst-<version>-*.conda
```

4. Upload to anaconda channel:

```bash
anaconda login
anaconda upload ~/miniforge3/envs/snc2fst/conda-bld/noarch/snc2fst-<version>-*.conda
```

## License

Apache 2.0. See [LICENSE](LICENSE).
