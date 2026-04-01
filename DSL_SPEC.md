# Search & Change (S&C) DSL Specification

## Overview

This DSL is a Lisp-style functional language designed to map directly to the mathematical primitives of Logical Phonology and Search & Change. It transforms a Target Substring (INR) into an Output String based on its relationship to a Trigger Substring (TRM).

## Core Data Types

- **Sequence**: A finite string of zero or more segments. All expressions ultimately evaluate to a sequence. `INR`, `TRM`, `INR[N:M]`, and the result of `(in? ...)` used as a condition all operate on sequences.
- **Segment**: A consistent set of valued features. A length-1 sequence is treated as a segment by `unify`, `subtract`, and `proj`.
- **Feature Specification**: A set of valued features written as `{+F -G}`, used for matching (natural classes) or segment unification.
- **Natural Class Sequence**: A sequence of feature specifications written as `[{+F} {-G}]`, used in `in?`. Defines the set of all strings of a given length whose i-th segment satisfies the i-th spec.
- **Feature Names**: An unvalued list of feature names written as `(F G ...)`, used in `proj`.

## Syntax Conventions

| Syntax | Role | Description |
|--------|------|-------------|
| `(...)` | Expression / concat | If the first token is an operator keyword, it's a function call. Otherwise, arguments are implicitly concatenated into a sequence. |
| `{...}` | Feature specification | Valued features, space-separated: `{+Voice -Sonorant}`. Empty spec `{}` matches any segment. |
| `[{...} {...}]` | Natural class sequence | Used as the second argument to `in?`. |
| `(F G ...)` | Feature name list | Unvalued feature names, used as the second argument to `proj`. |
| `&A` | Literal segment | Expands to segment `A`'s full feature bundle from the project alphabet. |
| `INR[N]` | Single-position slice | Sugar for `INR[N:N]`. Evaluates to a length-1 sequence. |
| `INR[N:M]` | Subsequence slice | Segments N through M of the Initiator match (1-based, inclusive). |
| `TRM[N]` | Single-position slice | Sugar for `TRM[N:N]`. Evaluates to a length-1 sequence. |
| `TRM[N:M]` | Subsequence slice | Segments N through M of the Terminator match (1-based, inclusive). |
| Whitespace | Delimiter | Sole separator between tokens. No commas. |

## Reserved Keywords

- **INR** — The full sequence matched by the Initiator (length n).
- **TRM** — The full sequence matched by the Terminator (length m).

## Operators

The root of every Out expression must evaluate to a sequence of segments. Indexing is **1-based** throughout.

### Membership

```
(in? <seq> [{<f1>} {<f2>} ...])     -> Boolean
```
Returns true if `<seq>` is a member of the natural class sequence — i.e., the lengths match and each segment satisfies the corresponding feature specification. A length-1 NC sequence `[{...}]` tests a single segment; a longer NC sequence tests a substring.

### Logic

```
(if <cond> <then> <else>)           -> Sequence
```
Standard ternary control flow. Both branches must evaluate to a sequence.

### Modification

```
(unify <seq> <features>)            -> Segment
```
Returns the segment unified with the given feature specification. `<seq>` must evaluate to a length-1 sequence. The second argument may be a `{...}` literal or any length-1 sequence-returning expression (e.g., `(proj TRM[1] (Voice))`).

```
(subtract <seq> {<features>})       -> Segment
```
Returns the segment with the given features removed. `<seq>` must evaluate to a length-1 sequence.

```
(proj <seq> (<f1> <f2> ...))        -> Segment
```
Projects the segment onto the named features, returning only those feature values. `<seq>` must evaluate to a length-1 sequence. The second argument is a feature name list `(F G ...)`.

### Concatenation

```
(<arg1> <arg2> ...)                 -> Sequence
```
Bare parentheses with no leading operator keyword perform implicit concatenation. Arguments may be sequences, segments (`&A`, modification results), or feature specs (treated as underspecified epenthetic segments).

## Examples

**Identity** — return the matched segment unchanged:
```
INR[1]
```

**Reduplication** — copy a CVC sequence (Iloko plural):
```
(INR[1] INR[2] INR[3] INR[4] INR[2] INR[3] INR[4])
```

Which can equivalently be written using slices:
```
(INR[1:4] INR[2:4])
```

**Epenthesis** — insert a literal segment between two matched segments:
```
(INR[1] &ə INR[2])
```

**Voicing harmony** — unify the target's Voice feature with the trigger's:
```
(unify INR[1] (proj TRM[1] (Voice)))
```

**Conditional assimilation** — condition on a single trigger segment:
```
(if (in? TRM[1] [{-Back}])
    (unify (subtract INR[1] {+Dorsal}) {-Dorsal})
    INR)
```

**Conditional assimilation** — condition on the full trigger (m=1):
```
(if (in? TRM [{+Voice}])
    (unify INR[1] {+Voice})
    INR[1])
```

**Conditional assimilation** — condition on a multi-position trigger (m=2):
```
(if (in? TRM [{-Sonorant} {+Voice}])
    (unify INR[1] {+Voice})
    INR[1])
```

## Notes

- `{}` (empty feature spec) used in `in?` matches any segment (the universal natural class).
- `INR` and `TRM` as bare keywords refer to the full matched sequences. They are most useful as the `else` branch of an `if` to return the target unchanged, or as the argument to `in?` when testing the full trigger.
- `unify`, `subtract`, and `proj` require their first argument to evaluate to a length-1 sequence. Passing a longer sequence is a runtime error caught during `snc validate`.
- BOS and EOS word boundary pseudo-segments can appear in `Inr` (as `["+BOS"]`/`["+EOS"]`) to anchor rules to word edges. They are not segment types and cannot appear in Out expressions.
