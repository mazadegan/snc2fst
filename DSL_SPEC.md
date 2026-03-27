# Search & Change (S&C) DSL Specification

## Overview

This DSL is a Lisp-style functional language designed to map directly to the mathematical primitives of Logical Phonology and Search & Change. It transforms a Target Substring (INR) into an Output String based on its relationship to a Trigger Substring (TRM).

## Core Data Types

- **SEGMENT**: A consistent set of valued features (e.g., from an alphabet lookup or a rule modification).
- **FEATURE SPECIFICATION**: A set of valued features (e.g., `[+Syllabic -High]`) used for matching (Natural Classes) or segment construction.
- **SEQUENCE**: A finite string of segments (e.g., a word or substring) or Natural Classes.

## Syntax Conventions

| Syntax | Role | Description |
|--------|------|-------------|
| `(...)` | Operations (Verbs) | Functions executed by the compiler. |
| `[...]` | Feature Data (Nouns) | Valued features, Natural Classes, or feature name lists. |
| Whitespace | Delimiter | Sole separator between features and arguments. No commas needed. |
| `'A` | Symbol shorthand | Expands to segment A's full feature bundle from the project alphabet. |

## Reserved Keywords

- **INR** — The substring matched by the Initiator sequence (length n).
- **TRM** — The substring matched by the Terminator sequence (length m).

## Primitives & Operations

The root of every DSL expression **must** evaluate to a sequence of segments. Indexing is **1-based** throughout.

### Extraction

```
(nth <i> <sequence>)             -> Segment
```
Returns the i-th Segment of a sequence.

### Validation

```
(in? <seg> [<features>])         -> Boolean
```
Returns true if the segment is a member of the natural class defined by the feature specification.

```
(models? <seq> <nc_seq>)         -> Boolean
```
Returns true if the sequence models the natural class sequence (pointwise membership check).

### Logic

```
(if <cond> <then> <else>)        -> Sequence
```
Standard ternary control flow. Subsumes the role of the former CND component.

### Modification

```
(unify <seg> [<features>])       -> Segment
```
Applies the Unification (⊔) operator.

```
(subtract <seg> [<features>])    -> Segment
```
Applies the Subtraction (\\) operator.

```
(project <seg> [<f1> <f2> ...])  -> Segment
```
Applies the Projection (π) operator. The bracket contains unvalued feature names.

### Construction

```
(concat <arg1> <arg2> ...)       -> Sequence
```
Combines Segments into the final Output String. A feature spec `[<features>]` used as an argument constructs a new Segment at that position.

## Examples

**Metathesis** — Swap two segments:
```
(concat (nth 2 INR) (nth 1 INR))
```

**Epenthesis** — Insert a new segment:
```
(concat (nth 1 INR) [+Syllabic -High] (nth 2 INR))
```

**Conditional Assimilation** — condition on full TRM (m=1):
```
(if (models? TRM [[+Syllabic]])
    (concat (unify (nth 1 INR) [+Voice]))
    INR)
```

**Conditional Assimilation** — condition on a specific position within TRM (m>1):
```
(if (in? (nth 2 TRM) [+Syllabic])
    (concat (unify (nth 1 INR) [+Voice]))
    INR)
```

## Notes

`[...]` does double duty: it is a **Feature Specification** when used as a matching argument (e.g., in `in?` or `models?`) and a **segment constructor** when used as a `concat` argument. The distinction is determined by position/context and resolved by the compiler.
