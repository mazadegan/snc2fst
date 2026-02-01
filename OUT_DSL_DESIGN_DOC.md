# snc2fst Tiny Lisp — Design Doc

## 0. Purpose

This document specifies a **tiny, safe, expression-only Lisp** used to define the `Out` component of Search & Change rules in `snc2fst`.

The language:

* is pure
* evaluates to a single feature bundle
* operates only on two bound inputs: `INR` and `TRM`
* supports unification, subtraction, projection, **and explicit feature literals** over ternary feature bundles
* is interpreted (never executed as code)

This Lisp is syntactic sugar over the internal set operations and is designed to mirror the mathematical definitions of `Out` used in S&C. Its main reason for existing is so the config file isn't horrifying to look at.

---

## 1. Design goals

* Match the mathematical semantics of S&C `Out` definitions
* Allow nested composition of feature operations
* Be concise and readable
* Be safe by construction (no arbitrary code execution)
* Be easy to parse and interpret
* Produce a single output bundle per rule application
* Allow **direct construction of feature bundles** without reference to `INR` or `TRM`

---

## 2. Non-goals: avoid scope creep

* No user-defined functions or lambdas
* No variables beyond `INR` and `TRM`
* No control flow (conditionals, loops)
* No mutation or assignment

---

## 3. Evaluation model

### 3.1 Inputs

At rule-application time, the evaluator is given:

* `INR`: a feature bundle (the search initiator)
* `TRM`: a feature bundle (the search terminator)

These are the *only* bound identifiers.

### 3.2 Output

The evaluation of an `Out` expression returns a single feature bundle.

A resulting bundle is considered well-formed (consistent) iff, for every feature F, it does not contain both ⟨+, F⟩ and ⟨-, F⟩.

Underspecification is allowed: a feature may be absent from the bundle (implicitly 0).

In other words, the result should be a set of valued features (i.e., a segment).

---

## 4. Value types

The language operates over the following value types:

### 4.1 Feature bundle

A feature bundle is a set of feature specifications of the form:

* ⟨`c`, `F`⟩ where `c ∈ {+, -}` and `F` is a feature name

For example:

```
{ (+, voice), (-, consonantal), (+, continuant) }
```

Underspecification (`0`) is represented implicitly:

* A feature `F` is underspecified in a bundle iff neither ⟨`+`, `F`⟩ nor ⟨`-`, `F`⟩ is present in the set.

The empty bundle `∅` represents complete underspecification (all features `0`).

### 4.2 Feature list

A feature list is a list of feature names (used as the second argument to `proj`).

---

## 5. Syntax

The language uses **S-expressions**.

### 5.1 Atoms

* `INR` — evaluates to the search initiator bundle
* `TRM` — evaluates to the search terminator bundle
* Feature names (used only inside feature lists and literals)
* Polarity symbols: `+`, `-`

### 5.2 Lists

A list represents a function application:

```
(<operator> <arg1> <arg2> ...)
```

---

## 6. Expressions

All expressions evaluate to feature bundles.

### 6.1 Bundle reference

```
INR
TRM
```

Evaluates to the specified bound bundle (i.e., the search initiator INR or terminator TRM).

---

### 6.2 Feature literals

```
(lit <polarity> <feature>)
```

Evaluates to a **singleton feature bundle** containing exactly one feature specification.

Examples:

```
(lit + voice)        ⇒ { (+, voice) }
(lit - consonantal) ⇒ { (-, consonantal) }
```

Semantics:

* `<polarity>` must be either `+` or `-`.
* `<feature>` must be a valid feature name in the alphabet.
* The resulting bundle contains exactly one valued feature.

Notes:

* Literals are the primary way to introduce *new* feature values not copied from `INR` or `TRM`.
* More complex bundles are constructed by composing literals with `unify`.

Example:

```
(unify
  (lit + voice)
  (lit - continuant))
```

---

### 6.3 Projection

```
(proj <bundle-expr> (<feature>...))
```

Evaluates to a feature bundle consisting of only the listed features, with values taken from the evaluated bundle expression.

Formally, if `A` is the evaluated bundle and `S` is the set of listed features:

```
proj(A, S) = { ⟨c, F⟩ ∈ A | F ∈ S }
```

Semantics:

* If the feature list is non-empty, the result bundle contains exactly those feature specifications from `A` whose feature is listed.
* If the feature list is empty, the result is the empty bundle `∅`.

Constraints:

* all listed features must exist in the alphabet

Notes:

* Projection onto the empty feature set yields the empty bundle.
* The empty bundle acts as an identity element for both `unify` and `subtract`.

---

### 6.4 Unification

```
(unify <bundle-expr> <bundle-expr>)
```

Evaluates both arguments to bundles and returns their left-biased unification.

Let `A` be the left bundle and `B` the right bundle. Unification is defined as:

```
A ⊔ B = A ∪ { ⟨c, F⟩ ∈ B | ⟨-c, F⟩ ∉ A }
```

Intuitively:

* Feature specifications already present in `A` always win.
* Feature specifications from `B` are added only if they do not contradict `A`.

Notes:

* `unify` is not symmetric: `unify(A, B) ≠ unify(B, A)`.
* Unification never removes feature specifications from `A`.
* Literals are commonly unified with projections or other literals to construct outputs.

---

### 6.5 Subtraction

```
(subtract <bundle-expr> <bundle-expr>)
```

Evaluates both arguments to bundles and returns the subtraction of the right bundle from the left bundle.

Let `A` be the left bundle and `B` the right bundle. Subtraction is defined as:

```
A \ B = { ⟨c, F⟩ ∈ A | ⟨c, F⟩ ∉ B }
```

Intuitively:

* Any feature specification present in `B` is removed from `A`.
* Features not mentioned in `B` are unaffected.

---

## 7. Nesting and composition

Expressions may be nested arbitrarily.

Example:

```
(unify
  (subtract TRM (proj TRM (voice)))
  (lit + voice))
```

---

## 8. Top-level contract

* An `Out` expression **must** evaluate to a single feature bundle.
* There are no statements and no mutation.
* The result of the expression is interpreted as the rewritten feature bundle for the rule application.

If evaluation fails (e.g., unknown feature), a helpful error should be thrown.

---

## 9. Errors and strictness

The language is **always strict**:

* unknown operators → error
* wrong arity → error
* invalid polarity in `lit` → error
* unknown feature names → error

Errors should be reported with context (operator name, argument position).

---

## 10. Implementation notes

* Parsing is performed using the S-expression parser `sexpdata`
* Evaluation is recursive and deterministic
* The interpreter does not execute code and cannot escape its defined semantics
* The evaluator is parameterized by the **alphabet feature universe** (the set of all valid feature names)
* During evaluation of `(proj …)` and `(lit …)`, all referenced feature names are validated against this universe; use of an undefined feature results in an error
* Resolution from a feature bundle to a surface segment (and enforcement of uniqueness/strictness) is performed **outside** the DSL, by the surrounding rule-application or compilation logic

---

## 11. Why?

This design:

* mirrors the lambda-style definitions used in formal S&C descriptions
* avoids embedding executable code in config files
* allows expressive, nested feature operations
* supports direct construction of output features via literals
* keeps the compiler pipeline simple, and keeps the config file readable
