# snc2fst

## Overview

`snc2fst` is a tool for writing and compiling phonological rules in the Search & Change (S&C) framework. Rules are written in a small DSL, validated against a feature alphabet, and compiled to finite-state transducers via OpenFST/pynini.

## Installation

```bash
conda install mazadegan::snc2fst
```

## Quick Start

Initialize a new grammar project with:

```bash
snc init
```

This creates three files in the current directory:

- `config.toml`:the grammar configuration (rules, alphabet path, tests path)
- `alphabet.csv`:the feature alphabet
- `tests.tsv`:input/output test pairs

For a blank project, a setup wizard prompts for metadata:

```
Grammar title: My Grammar
Language name or ISO 639-3 code: Turkish
Description (optional): ...
Sources/references (optional):enter one per line, blank line to finish:
  Source: ...
```

Full language names (`Turkish`) are accepted and automatically resolved to their ISO 639-3 code, or you can enter the code directly (`tur`).

### Starting from a starter project

To start from one of the built-in starter projects instead:

```bash
snc init --pick                          # interactive menu
snc init --from iloko_plural             # by name
```

Available starters: `english_past_tense`, `english_plural`, `georgian_laterals`, `iloko_plural`, `turkish_k_deletion`, `votic_vowel_harmony`.

## GUI

You can open a project in the web GUI with:

```bash
snc gui .
```

from inside a project directory, or pass a project path directly.

The GUI provides a project workspace for authoring rules, editing `alphabet.csv` and `tests.csv`/`tests.tsv`, exploring natural classes, and running `eval` and `compile` without leaving the editor.

## Commands

### `snc validate`

```bash
snc validate config.toml
```

Validates the grammar configuration, alphabet, and test file. Checks that all features referenced in rules exist in the alphabet, all `Out` expressions are well-formed, and:if `compilable = true` in `[meta]`:that all rules can be compiled to FSTs. Exits non-zero on failure.

### `snc eval`

```bash
snc eval config.toml              # run all test cases
snc eval config.toml "kaldiŋ"     # evaluate a single word
```

Applies rules to test cases and reports pass/fail. By default uses the evaluator; `--fst` transduces via compiled FSTs in the `transducers/` directory instead.

| Flag | Description |
|------|-------------|
| `--fst` | Use compiled FSTs instead of the evaluator |
| `--format txt\|latex` | Render results as a formatted table |
| `-o FILE` | Write output to a file |
| `--no-warn` | Suppress alphabet underspecification warnings |

### `snc compile`

```bash
snc compile config.toml
```

Compiles all rules to FSTs and writes them to `transducers/` (or a directory of your choice with `-d`).

| Flag | Description |
|------|-------------|
| `-d DIR` | Output directory (default: `transducers/`) |
| `--format fst\|att` | Output format: OpenFST binary or AT&T text (default: `fst`) |
| `--max-arcs N` | Abort if any FST exceeds N arcs before optimization (default: 1,000,000) |
| `--no-optimize` | Skip rmepsilon / determinize / minimize |
| `-v` | Print full tracebacks on error |

### `snc export`

```bash
snc export config.toml            # print to stdout as plain text
snc export config.toml -f latex -o output.tex
```

Exports the alphabet and all rules in a human-readable format. Plain text uses DSL-style notation; LaTeX uses mathematical notation suitable for inclusion in a paper (WIP). To share the grammar with collaborators as source, just share the project files directly.

| Flag | Description |
|------|-------------|
| `-f txt\|latex` | Output format (default: `txt`) |
| `-o FILE` | Write to a file instead of stdout |

## The DSL

Out functions are written in a Lisp-style functional language. The root of every `Out` expression must evaluate to a sequence of segments.

### Key syntax

| Syntax | Type | Meaning |
|--------|------|---------|
| `INR` | `Seq` | Full sequence matched by the Initiator |
| `TRM` | `Seq` | Full sequence matched by the Terminator |
| `INR[N]` | `Seq` | N-th segment of INR, 1-based (length-1 sequence) |
| `INR[N:M]` | `Seq` | Segments N through M of INR (inclusive) |
| `TRM[N]` | `Seq` | N-th segment of TRM, 1-based (length-1 sequence) |
| `TRM[N:M]` | `Seq` | Segments N through M of TRM (inclusive) |
| `{+F -G}` | `FSpec` | Feature specification |
| `[{+F} {-G}]` | `NcSeq` | Natural class sequence |
| `(F G ...)` | `FNames` | Feature name list (used in `proj`) |
| `&A` | `Seq` | Literal segment `A` from the alphabet (length-1 sequence) |
| `(x y z)` | `Seq` | Implicit concatenation |

### Operators

| Operator | Signature | Description |
|----------|-----------|-------------|
| `(in? seq [{...} ...])` | `Seq × NcSeq → Bool` | Tests whether a sequence is a member of a natural class sequence |
| `(if cond then else)` | `Bool × Seq × Seq → Seq` | Conditional |
| `(unify seq {+F})` | `Seq[1] × FSpec → Seq[1]` | Adds valued features to the segment if not blocked by an opposing value |
| `(subtract seq {+F})` | `Seq[1] × FSpec → Seq[1]` | Removes the specified valued features from the segment |
| `(proj seq (F G))` | `Seq[1] × FNames → Seq[1]` | Projection: keeps only named features |

`unify`, `subtract`, and `proj` require their first argument to be a length-1 sequence.

For the full specification, see [DSL_SPEC.md](DSL_SPEC.md).

## Starter Projects

### English past tense (`english_past_tense`)

Models the allomorphy of the English past tense suffix /D/ (Hayes 2009, §6.3). The underlying form uses a capital `D` to represent the underspecified suffix. Two rules apply in order:

**R1:Schwa epenthesis.** When two coronal stops are adjacent (i.e., a stem ending in /t/ or /d/ followed by /D/), a schwa is inserted between them:

```toml
Inr = [["-Sonorant", "+Coronal", "-Continuant"], ["-Sonorant", "+Coronal", "-Continuant"]]
Out = "(INR[1] &ə INR[2])"
```

**R2:Voicing harmony.** The suffix /D/ agrees in voicing with the nearest preceding segment (the trigger). Its Voice value is projected from the trigger and unified into the target:

```toml
Inr = [["-Sonorant", "+Coronal", "-Continuant"]]
Trm = [[]]
Out = "(unify INR[1] (proj TRM[1] (Voice)))"
```

`Trm = [[]]` means the trigger is any single segment:the rule picks the nearest one to the left (`Dir = "L"`).

### English plural (`english_plural`)

Models the allomorphy of the English plural suffix /S/ (Kenstowicz & Kisseberth 1979, Ch. 1). The underlying form uses a capital `S` to represent the underspecified suffix. Three rules apply in order:

**R1a:Schwa epenthesis after stridents.** When a strident (s, z) is followed by another strident, a schwa is inserted between them:

```toml
Inr = [["-Labial", "+Strident"], ["-Syllabic", "+Strident"]]
Out = "(INR[1] &ə INR[2])"
```

**R1b:Schwa epenthesis after distributed coronals.** Same insertion after distributed coronals (ʃ, ʒ):

```toml
Inr = [["+Coronal", "+Distributed"], ["-Syllabic", "+Strident"]]
Out = "(INR[1] &ə INR[2])"
```

**R2: Voicing harmony.** The suffix /S/ agrees in voicing with the nearest preceding segment:

```toml
Inr = [["-Syllabic"]]
Trm = [[]]
Out = "(unify INR[1] (proj TRM[1] (Voice)))"
```

### Georgian lateral harmony (`georgian_laterals`)

Models the front/back alternation of the Georgian lateral /l̃/ before front vs. back vowels (Kenstowicz & Kisseberth 1979, Ch. 2). The lateral is specified as `+Dorsal` by default and becomes `-Dorsal` when followed by a segment that is `-Back`.

**R1: Lateral harmony.** If the trigger (any following segment) is front (`-Back`), the lateral's `+Dorsal` is replaced by `-Dorsal`. Otherwise it surfaces unchanged:

```toml
Inr = [["+Lateral", "+Dorsal"]]
Trm = [[]]
Dir = "R"
Out = """
  (if (in? TRM[1] [{-Back}])
    (unify (subtract INR[1] {+Dorsal}) {-Dorsal})
    INR)
"""
```

The `subtract` is necessary before `unify` because unification is blocked when the opposing value is already present: `+Dorsal` must be removed before `-Dorsal` can be added.

### Iloko plural (`iloko_plural`)

Models plural noun formation in Iloko via CVC reduplication (Hayes 2009). The plural is formed by copying the first word-initial consonant-vowel-consonant sequence of the stem. The rule uses a BOS boundary to anchor the match to the start of the word.

**R1: CVC reduplication.** Matches BOS followed by a CVC sequence and copies it leftward:

```toml
Inr = [["+BOS"], ["-Syllabic"], ["+Syllabic"], ["-Syllabic"]]
Out = "(INR[1:4] INR[2:4])"
```

`INR[1:4]` is the full BOS+CVC window; `INR[2:4]` is just the CVC. The result prepends the copy before the original, producing e.g. *kaldiŋ* → *kalkaldiŋ*.

### Turkish k-deletion (`turkish_k_deletion`)

Models intervocalic k-deletion in Turkish (Reiss & Gorman 2026). The underlying form uses a capital `K` for the alternating velar stop. Three rules apply in order:

**R1: Word-final epenthesis.** A stem ending in two consonants before EOS receives an epenthetic vowel /ɯ/ between them:

```toml
Inr = [["-Syllabic"], ["-Syllabic"], ["+EOS"]]
Out = "(INR[1] &ɯ INR[2:3])"
```

**R2: Intervocalic deletion.** /k/ is deleted when in between vowels:

```toml
Inr = [["+Syllabic"], ["-Syllabic", "+Dorsal"], ["+Syllabic"]]
Out = "(INR[1] INR[3])"
```

**R3: Feature-filling.** Underspecified voiceless stops become dorsal (i.e., /K/ surfaces as /k/ when not deleted):

```toml
Inr = [["-Syllabic", "-Voice", "-Continuant"]]
Out = "(unify INR[1] {+Dorsal})"
```

### Votic vowel harmony (`votic_vowel_harmony`)

Models vowel harmony in Votic (Leduc, Reiss & Volenec 2020). Suffix vowels agree in backness with the nearest preceding vowel trigger. Three rules apply in order, each targeting any vowel and searching leftward for a trigger:

**R1: Harmony from non-high vowels.** A vowel copies `Back` from the nearest preceding non-high vowel:

```toml
Inr = [["+Syllabic"]]
Trm = [["+Syllabic", "-High"]]
Out = "(unify INR[1] (proj TRM[1] (Back)))"
```

**R2: Harmony from high round vowels.** A vowel copies `Back` from the nearest preceding high round vowel:

```toml
Inr = [["+Syllabic"]]
Trm = [["+Syllabic", "+High", "+Round"]]
Out = "(unify INR[1] (proj TRM[1] (Back)))"
```

**R3: Default.** Any vowel not reached by R1 or R2 surfaces as `-Back`:

```toml
Inr = [["+Syllabic"]]
Trm = [[]]
Out = "(unify INR[1] {-Back})"
```

Because rules apply in order, R3 only fires when neither R1 nor R2 found a trigger.

> **Note:** The starter projects are examples intended to demonstrate how the software works. They are not meant to be complete analyses of the phonological patterns they are based on.

## Developer Notes

### Releasing a new version

1. Bump the version in `pyproject.toml` and `conda-recipe/meta.yaml`.

2. Build the conda package:

```bash
conda build conda-recipe
```

3. Upload to your anaconda channel:

```bash
anaconda login
anaconda upload ~/miniforge3/envs/snc2fst/conda-bld/noarch/snc2fst-<version>-*.conda
```

## License

Apache 2.0. See [LICENSE](LICENSE).
