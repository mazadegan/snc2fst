# snc2fst — Design Doc

## 0. Context

**Goal:** Build a compiler that takes a **Search & Change (S&C)** grammar/ruleset and produces a **finite-state transducer (FST)** implementation suitable for downstream tooling (e.g., applying phonological rules to strings, composing with other machines, exporting to OpenFST/Pynini, analysis using The Language Toolkit, etc.).

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

Grammar should be able to express:

* Alphabet (segments or symbols)
* Feature matrix for symbols
* Rule set: list of Rules (consist of Inr/Trm/Dir/Out/Cnd)

**Design decision (v0.1):** JSON is the canonical input format for rule definitions. CSV/TSV is supported only as a *source* format for feature tables, via a conversion command that produces the schema+rows JSON representation used by the compiler.

### 2.2 Output formats (MVP)

* **OpenFST text** (FST in AT&T-like format)

**Design decision (v0.1):** OpenFST text only. Other export targets (e.g., Pynini builder scripts) can be revisited after v0.1 once the core compilation semantics stabilize.

## 3. Core concepts

### 3.1 Basic data model

* **Symbol**: atomic token in strings (e.g., `a`, `p`, `tʃ`, `V`, etc.)
* **Feature bundle**: `{feature: +|-|0}` tri-valued (0 = unspecified)
* **Natural class**: predicate over symbols defined by feature constraints
* **Rule**: `(Inr,Trm,Dir,Out,Cnd)`

**Design decision:** *Symbols are not rewritten directly.* Rewrites are expressed as **feature updates** applied to the matched symbol(s). The surface output symbol is whichever segment in the alphabet matches the updated feature bundle (subject to well-formedness/uniqueness constraints).

### 3.2 Search & Change overview (compiler view)

At a high level each rule defines:

* **Inr:** Where searches begin (Is a natural class)
* **Trm:** Where searches end (Is a natural class)
* **Dir:** Where searches go (LEFT or RIGHT)
* **Out:** How segments should change (Is a function)
* **Cnd:** Segments that license change (Is a natural class)

---

## 4. Architecture

### 4.1 Pipeline

We do **not** need a large, general-purpose AST for v0.1, because the rule language is intentionally small and JSON already provides a tree structure.

Instead we parse JSON directly into **typed config objects** (dataclasses / maybe pydantic models?), then validate + normalize those objects. If/when the rule language grows (macros, nested expressions, syntactic sugar), we can introduce an AST later.

### 4.2 Modules

* `parser/` — JSON → config objects
* `schema/` — config types + validation
* `features/` — feature bundles, unification, subtraction, natural classes
* `ir/` — IR definitions (rule-lowered forms)
* `compile/` — IR → FST
* `export/` — OpenFST AT&T formatted text, etc.
* `cli/` — `snc2fst compile ...`
* `tests/` — unit + golden tests

---

## 5. Intermediate representation (IR)

Design the IR to make compilation straightforward.

### 5.1 Candidate IR primitives

* `ClassRef(name)` or `ClassPred(feature_constraints)`
* `Literal(symbol)`
* `Concat([...])`
* `Union([...])`
* `KleeneStar(x)` (maybe avoid for subsequential constraints)
* `Capture(id, pattern)` (only if needed)

### 5.2 Rule IR shape

A possible normalized shape:

* `LHS = (Inr,Trm,Dir,Cnd)` expressed as predicates over positions/symbols
* `Out = feature_update_fn` that maps an input feature bundle → output feature bundle
* `Application = parallel` (design decision: compute all licensed changes on the input, then apply them to produce output)

Alpha-notation lowering might introduce **feature variables** that unify across multiple positions.

---

## 6. FST compilation strategy

### 6.1 Strategy options

1. **Direct construction**: build a single transducer that (conceptually) computes the change set and outputs the rewritten string.

2. **Factorized**: build helper machines (e.g., a recognizer that marks licensed positions) and compose.

MVP recommendation: **direct construction** for the simplest behavior.

### 6.2 Determinism & subsequentiality assumptions

Design decisions:

* Feature system is **ternary**: `+`, `-`, `0` (underspecified)
* Backend/export target is **OpenFST text**
* Rule application is **not iterative**: we compute the full set of licensed changes on the input, then apply them to produce output (parallel application)

Implications to document/validate:

* Define the match-selection policy used to compute the change set (e.g., leftmost-longest vs leftmost-shortest).
* Define what happens under overlap/conflict (multiple changes propose different feature updates at one position).
* Strictness requirements remain enforced (unique symbol resolution after applying `Out`).

---

## 9. Milestones

### v0.1 (MVP)

* JSON grammar
* alphabet feature table import (CSV/TSV → JSON)
* symbols + feature matrix
* one rule type: bounded context rewrite via feature updates
* compile to OpenFST text
* `validate` (rules *or* alphabet) + `compile` + `config table import`