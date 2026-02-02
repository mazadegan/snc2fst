## 0. Goal

Implement a **rule-to-FST compiler** in Python that outputs an **explicit FST machine** (and can be printed in AT&T text format) for S&C-style rules.

Key requirement: build the **canonicalized/merged transducer** (T_V) **directly**, without first constructing a brute-force (T) and then merging.

This design targets rules where (|V|) is typically small (≈ 2–8), so (|\Sigma_V| = 3^{|V|}) is tractable and we can materialize all arcs.

---

## 1. Objects and notation

* (\mathcal F): global feature set (may be large)
* (V \subseteq \mathcal F): **grammar-visible features** (features referenced in `inr`, `trm`, `cnd`, and in projections/static bundles inside `out`)
* (P \subseteq V): **Out-visible TRM features** (the subset of features of `TRM` that `out` actually depends on)
* (\Omega(\mathcal F)): all consistent (possibly underspecified) bundles over (\mathcal F)
* (\Sigma_V): witness alphabet over (V), size (3^{|V|})
* (T_V): explicit transducer over (\Sigma_V)

Canonicalization map (conceptual):

* (\kappa(x) = \pi_V(x))

In implementation we operate directly on projected bundles (symbols in (\Sigma_V)).

---

## 2. Inputs and outputs

### Inputs

* JSON rule file (single rule or list):

  * `id`
  * `inr`, `trm`, `cnd`: lists of feature literals like `["+", "voice"]`
  * `out`: tiny DSL expression over `INR` and `TRM` using `proj`, `subtract`, `unify`, and literals
  * `dir` is **optional**; direction is handled by CLI (see §9)

### Outputs

* An explicit FST machine (binary `.fst`) with:

  * integer-labeled symbols
  * attached input/output SymbolTables
  * compiled via OpenFst CLI tools from AT&T text
* Optionally, AT&T text via `fstprint`

---

## 3. Feature bundle representation

### Ternary values

Represent each feature value in `{∅, +, −}` as an int:

* `0` = unspecified (∅)
* `1` = plus (+)
* `2` = minus (−)

### Bundle as tuple

For a fixed ordered list `V_order = [f0, f1, ..., fk-1]`, represent a bundle (x\in\Sigma_V) as:

* `x: tuple[int, ...]` of length `k`

Projection to `P` becomes coordinate selection.

### Consistency

We assume the ternary encoding is always consistent by construction (each feature has exactly one ternary value). If the input grammar ever supplies inconsistent specs, reject during parse/validation time.

---

## 4. Parsing and validation

### 4.1 Rule schema

Validate via Pydantic (recommended) or manual checks:

* `inr/trm/cnd` are lists of pairs `[sign, feature]`
* `sign ∈ {"+", "-"}`
* features are strings
* `out` parses to a valid AST in the tiny DSL

Compute `V` as the union of:

* all features mentioned in `inr`, `trm`, `cnd`
* all features mentioned in `out`, including:

  * `(proj ... (f1 f2 ...))`
  * `(lit + f)` / `(lit - f)` literals
  * any static bundles (if supported)

Choose a stable ordering `V_order` (e.g., sorted feature names, or a user-provided canonical order for reproducibility).

---

Goal: build the merged state space indexed by (\Sigma_P). We need the **subset of TRM features** that the DSL can observe.

### 5.1 Out-dependency analysis (AST walk)

Compute `P` by traversing the `out` AST and collecting **exactly those features of ********`TRM`******** that can influence the value of the output**.

The guiding principle is:

> A feature `f` belongs to `P` iff changing the value of `TRM[f]` (while holding all other inputs fixed) can change the value of `out(INR, TRM)` for some `INR`.

To approximate this efficiently and safely, we perform a **TRM-sensitivity analysis** on the AST:

* Any feature appearing in a subexpression rooted at `TRM` is included in `P`.
* Any feature appearing in `(proj TRM (f1 ... fn))` is included in `P`.
* Any feature appearing in a `lit` expression **is included in ****`P`**** only if that ****`lit`**** occurs in a subtree that also contains ****`TRM`** (e.g. under `unify`, `subtract`, or other operators combining with `TRM`).
* Features appearing exclusively in subtrees that depend only on `INR` do **not** contribute to `P`.

This analysis ensures that `P` contains all and only those TRM features whose values may be observed by the output function.

**Correctness.** If a feature is excluded from `P`, then by construction the output of `out` is invariant under changes to that feature’s value in `TRM`. Therefore, collapsing TRM segments that differ only on excluded features preserves the function computed by the transducer.

**Conservatism.** The analysis may still slightly over-approximate true dependencies (e.g. by including a literal feature that occurs in a large subtree containing `TRM` even if it is semantically irrelevant). Such over-approximation is harmless: it increases the number of states but never changes the realized transduction.

---

Given `k = |V|`, enumerate all tuples in `{0,1,2}^k`:

* `sigmaV = product([0,1,2], repeat=k)`

### 6.2 Integer label encoding

FSTs use integer labels; reserve `0` for epsilon.
Use base-3 encoding:

$$
\text{label}(t_0,\dots,t_{k-1}) = 1 + \sum_{i=0}^{k-1} t_i,3^i
$$

### 6.3 Symbol strings

Attach readable strings for `fstprint`, e.g.

* `voice+_consonantal∅_back-` etc.

Create one SymbolTable used for both input and output.

---

### 7.1 State set

Let `P_order` be `P` in the same order as `V_order` (subsequence).
Enumerate (\Sigma_P = {0,1,2}^{|P|}).

States:

* `qF` (False)
* one True state for each (p \in \Sigma_P)

Total states:

$$
|Q| = 1 + 3^{|P|}
$$

### 7.2 Compiling class membership predicates

Compile `inr/trm/cnd` into fast predicate functions over (\Sigma_V) tuples.

A class spec like `[ ["+", "voice"], ["-", "back"] ]` becomes a conjunction of coordinate checks:

* `x[idx("voice")] == 1` and `x[idx("back")] == 2`

Implement:

* `is_inr(xV)`
* `is_trm(xV)`
* `is_cnd(xV)`

Interpretation of `cnd: []`:

* recommended: treat as **no additional constraint** (i.e., `is_cnd` always true)
* if you ever need “empty set” semantics, use an explicit marker, not `[]`

### 7.3 Out evaluation on projected bundles

We need an evaluator that computes an output bundle in (\Sigma_V).

Inputs to the evaluator:

* `INR`: current symbol `xV ∈ Σ_V`
* `TRM`: remembered TRM projection `p ∈ Σ_P` (state memory)

Because the machine’s state remembers only (\pi_P(\text{TRM})), `out` must be evaluable from:

* `INR` fully over `V`
* `TRM` only over `P`

Implementation options:

1. **Specialize ************`out`************ to a function** `outV(inrV, trmP) -> yV`.
2. Evaluate the DSL in an environment:

   * `INR` as a dict for features in `V`
   * `TRM` as a dict for features in `P` and `∅` for features in `V\P`
   * then project final result to `V`

Option (2) is simpler and robust; it may slightly over-approximate if the DSL expects TRM features outside P, but that’s prevented by how we compute P.

### 7.4 Transition/output rules

We build a **total deterministic** transducer by adding one arc for every `(state, symbol)` pair.

Let:

* `projP(xV)` be projection of `xV` to `P` coordinates
* `apply_out(xV, trmP)` compute `outV(xV, trmP)`

Define the per-state emission function:

* `emit(q, xV)`:

  * if `is_inr(xV)` then `apply_out(xV, trmP)` (where `trmP` is state memory)
  * else `xV`

Define the next-state function (mirrors the S&C “trigger memory” idea):

From `qF`:

* if `is_trm(xV) and is_cnd(xV)`:

  * `next = q[projP(xV)]`, output `xV`
* else:

  * `next = qF`, output `xV`

From a True state with memory `trmP`:

* if `is_trm(xV)`:

  * if `is_cnd(xV)`:

    * `next = q[projP(xV)]`, output `emit(trmP, xV)`
  * else:

    * `next = qF`, output `emit(trmP, xV)`
* else (not terminator):

  * `next = same True state`, output `emit(trmP, xV)` **or** `xV` depending on the chosen S&C semantics

**Important:** pick and document the exact semantics for “inside True state reading a non-TRM symbol”.

* If your earlier construction leaves non-TRM symbols unchanged while remaining in True, then output `xV` there.
* If your model applies `Out` to every initiating segment while in True, then output `emit(trmP, xV)`.

(Choose one; implement consistently across proofs and compiler.)

### 7.5 Final states

Typically set all states final (length-preserving mapping). If you add boundary symbols later, you may prefer explicit finals.

---

## 8. FST construction details

### 8.1 AT&T output

To print with readable symbols:

* write symtab to file
* `fstprint --isymbols=... --osymbols=... Tv.fst > Tv.att`

### 8.2 Binary compilation

Emit AT&T text and use OpenFst CLI tools for compilation and inspection.

---

## 9. Direction handling (CLI-level)

Direction affects the S&C search orientation (left vs right), but compilation can be standardized.

Recommended approach:

* compile a single canonical direction (e.g., “LEFT search”) into (T_V)
* implement `--direction R` by reversing input and output strings:

$$
f_R(w) = \mathrm{rev}(T_V(\mathrm{rev}(w)))\quad\text{and}\quad f_L(w)=T_V(w)
$$

This lets you omit `dir` from rule JSON if direction is a global runtime choice.

If you later need mixed directions per rule, keep `dir` optional per rule and default to the CLI value.

---

## 10. Complexity and practical thresholds

Materializing the full explicit machine costs:

* states: (1 + 3^{|P|})
* arcs: ((1 + 3^{|P|})\cdot 3^{|V|})

This is fine for typical phonological rules where (|V|\le 8).

Optional safeguard:

* if arcs exceed a configurable threshold (e.g., 5–10 million), switch to a restricted alphabet (\Sigma_{work}) derived from a lexicon/corpus or grammar support.

---

## 11. Testing plan

### 11.1 Unit tests

* Feature parsing and validation
* `V` extraction from classes + DSL AST
* `P` dependency analysis correctness
* Symbol encoding/decoding round-trip
* Predicate compilation (`is_inr/is_trm/is_cnd`)
* DSL evaluator for `proj/subtract/unify/lit`

### 11.2 Behavioral tests

For each rule:

* generate random strings over (\Sigma_V)
* evaluate with:

  1. a direct Python reference interpreter of the S&C rule over projected bundles
  2. the compiled machine
* assert outputs match

### 11.3 Regression tests for AT&T output

* compile known small rule
* `fstprint` output matches a golden file (up to arc ordering)

---

## 12. Edge cases and conventions

* Interpret `cnd: []` as “no additional constraint” (always true)
* Handle `P = ∅`:

  * (\Sigma_P) has size 1
  * states = 2
* If `out` refers to TRM features not in `P` (should not happen if analysis is correct):

  * fail loudly with a helpful error
* Reserve label 0 for epsilon
* Keep feature ordering stable to ensure reproducible label assignments

---

## 13. Minimal milestone implementation

1. Implement bundle encoding and (\Sigma_V) enumeration
2. Implement class predicate compilation for `inr/trm/cnd`
3. Implement DSL parser + evaluator for `lit/proj/subtract/unify`
4. Implement `V` extraction and TRM-sensitivity–based `P` extraction
5. Build explicit (T_V) and emit AT&T text
6. Print AT&T with symbol tables
7. Add direction reversal wrapper in CLI

---

## 14. Example (spread voice)

Rule:

* `V = {voice, consonantal}`
* `P = {consonantal}`
* (|\Sigma_V| = 9)
* (|Q| = 4)
* arcs = 36

This is the expected scale for most rules in the target domain.
