# snc2fst — Design Doc

## 0. Context

**Goal:** Build a compiler that takes a **Search & Change (S&C)** grammar/ruleset and produces a **finite-state transducer (FST)** implementation suitable for downstream tooling (e.g., applying phonological rules to strings, composing with other machines, exporting to OpenFST/Pynini, analysis using *The Language Toolkit*, etc.).

**Working name:** `snc2fst`

---

## 1. Problem statement

We want a maintainable, testable compiler pipeline:

1. Parse an S&C grammar description.
2. Type-check / validate it (symbols, features, natural classes, alpha-notation constraints, etc.).
3. Lower it to an intermediate representation (IR) that is easy to reason about.
4. Compile the IR to an FST.
5. Provide exports + a small CLI.

---

## 2. Inputs and outputs

### 2.1 Input formats (MVP)

* **JSON** (S&C rule definitions)
* **CSV/TSV** (feature matrix source for the alphabet; converted into JSON via CLI)

Grammar must be able to express:

* Alphabet (segments or symbols)
* Feature matrix for symbols
* Rule set: list of rules (each consisting of `Inr`, `Trm`, `Dir`, `Out`, `Cnd`)

**Design decision (v0.1):** JSON is the canonical input format for rule definitions. CSV/TSV is supported only as a *source* format for feature tables, via a conversion command that produces the schema+rows JSON representation used by the compiler.

### 2.2 Output formats (MVP)

* AT&T Format

---

## 3. Core concepts

### 3.1 Basic data model

* **Symbol**: atomic token in strings (e.g., `a`, `p`, `tʃ`, `V`, etc.)
* **Feature bundle**: set of valued features `{⟨+,F⟩, ⟨-,F⟩}`, with implicit underspecification
* **Natural class**: conjunction of valued feature constraints
* **Rule**: `(Inr, Trm, Dir, Out, Cnd)`

**Design decision:** *Symbols are not rewritten directly.* Rewrites are expressed as **feature updates** applied to the matched symbol(s). Any mapping from a resulting feature bundle to a surface symbol is handled outside the rule language.

### 3.2 Search & Change overview (compiler view)

At a high level, each rule defines:

* **Inr**: where searches begin (a natural class)
* **Trm**: where searches end (a natural class)
* **Dir**: where searches go (`LEFT` or `RIGHT`)
* **Out**: how segments should change (a feature-update expression)
* **Cnd**: segments that license change (a natural class)

In v0.1, natural classes are expressed only as **conjunctions of valued features**. No disjunction or negation operators are provided.

---

## 4. Rule format (JSON)

Rules are represented as **pure data objects** in JSON. Each rule has the following structure:

```json
{
  "id": "spread_voice_right",
  "dir": "RIGHT",
  "inr": [["+", "Voice"]],
  "trm": [["+", "Consonantal"]],
  "cnd": [],
  "out": "(unify (subtract TRM (proj TRM (Voice))) (proj INR (Voice)))"
}
```

A rules file will look like this:

```json
{
  "rules": [
    {
        "id": "spread_voice_right",
        "dir": "RIGHT",
        "inr": [["+", "Voice"]],
        "trm": [["+", "Consonantal"]],
        "cnd": [],
        "out": "(unify (subtract TRM (proj TRM (Voice))) (proj INR (Voice)))"
    }
  ]
}
```

### 4.1 Natural classes (`inr`, `trm`, `cnd`)

* Represented as **lists of valued feature tuples**: `[polarity, feature]`
* Polarity is either `"+"` or `"-"`
* A feature not mentioned is implicitly underspecified
* An empty list `[]` imposes no constraints (matches all symbols)

Natural classes are interpreted as **conjunctions** of their listed feature constraints.

### 4.2 Direction (`dir`)

* Must be one of: `"LEFT"` or `"RIGHT"`

### 4.3 Out expression (`out`)

* A **string** containing a program written in the *snc2fst Tiny Lisp*
* Evaluates to a single **feature bundle**
* May reference only the bound identifiers `INR` and `TRM`
* Uses the operations `unify`, `subtract`, `proj`, and `bundle`

The DSL is intentionally pure and limited; it computes feature bundles but performs no mutation or control flow.

---

## 5. The Out DSL (Tiny Lisp)

The `out` field is evaluated using a **tiny, safe, expression-only Lisp** defined separately (see *snc2fst Tiny Lisp — Design Doc*).

Key properties:

* Pure (no side effects)
* Expression-only
* Evaluates to a single feature bundle
* Supports explicit feature literals via `(bundle (+ F))` / `(bundle (- F))`
* Validates feature names against the alphabet feature universe

The DSL exists solely to express feature-bundle transformations in a way that mirrors the formal S&C definitions while remaining readable in JSON.

---

## 6. Architecture

We do **not** need a large, general-purpose AST for v0.1, because the rule language is intentionally small and JSON already provides a tree structure.

Instead, JSON is parsed directly into **typed configuration objects** (e.g., dataclasses or pydantic models), which are then validated and normalized. If the rule language grows (macros, syntactic sugar, etc.), an explicit AST layer can be introduced later.

---

## 7. Intermediate representation (IR)

The IR is designed to make compilation straightforward.

### 7.1 Candidate IR primitives

* `ClassPred(feature_constraints)`
* `Concat([...])`
* `Union([...])`
* `KleeneStar(x)` (used sparingly)

## 7. FST compilation strategy

**Direct construction**: build a single transducer that computes the change set and outputs the rewritten string.

### 7.1 Determinism & subsequentiality assumptions

Design decisions:

* Feature system is **ternary**: `+`, `-`, `0`
* Backend/export target is **OpenFST text**
* Rule application is **parallel**, not iterative

---

## 8. Milestones

### v0.1 (MVP)

* Alphabet feature table import (CSV/TSV → JSON)
* JSON grammar
* Tiny Lisp evaluator for `out`
* One rule type: bounded context rewrite via feature updates
* Compile to OpenFST text
* CLI: `validate`, `compile`
