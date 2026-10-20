# Specification-based testing — partition and boundary heuristics

Distilled from Chapter 2 ("Specification-based testing") of *Effective Software Testing*,
Maurício Aniche (Manning, 2022), focusing on §2.2 (the 7 steps in summary) and §2.4
(real-world pragmatics). Read this file **before** Phase 3, because the quality of the whole
suite depends on partitioning well — and the rest of the flow (boundaries, cases, coverage)
is nearly mechanical once the partitions are right.

> Contents
> 1. Core idea: equivalence and partitions
> 2. How to identify partitions (the 3 lenses + signals)
> 3. How to identify boundaries (on/off point, in/out point)
> 4. §2.4 — real-world pragmatics (rules that avoid a bloated or brittle suite)
> 5. Full worked example

---

## 1. Core idea: equivalence and partitions

Specification-based testing derives tests from the **requirement** (any description of what
the code must and must not do) — not from the implementation. It is the first technique to
apply; structural coverage (line/branch) comes **afterwards**, to find what the
specification missed.

Two inputs are **equivalent** when they make the program behave the same way, regardless of
the exact value. If `("abcd","a","d")→"bc"` behaves like `("xyzw","x","w")→"yz"`, both are in
the same class and you test **only one** — it represents the whole class. A partition is
that set of equivalent inputs.

The reasoning loop: find a class → look for **another** class that makes the program behave
in a way you have **not tested yet** → keep splitting the domain until every distinct
behavior is covered.

---

## 2. How to identify partitions (equivalence partitioning)

For **each function**, apply the three systematic lenses:

1. **Each input in isolation** — explore the type and value range. Can it be NULL? 0–100?
   negative? *"What input classes can I provide for this variable?"*
2. **Inputs in combination** — variables often depend on or constrain each other. *"Which
   combinations are valid between `open` and `close`?"* This is where the cases no single
   lens reveals live.
3. **Output classes** — *"Can it return an empty array? NULL? one item? several?"* Thinking
   about the output reveals inputs you forgot, especially in complex programs.

### Signals that a distinct partition exists

- The spec mentions the case explicitly ("NULL returns NULL; empty string returns empty" →
  NULL and empty are partitions).
- **NULL and empty are always good exceptional cases** — consider them even when not
  mentioned (but see §2.4.9 on *when* testing them makes sense).
- A string is "basically a list of characters", so **length** partitions: NULL / empty /
  length 1 / length > 1. The same reasoning applies to arrays, buffers and lists of any
  type — in firmware, `count == 0`, `count == 1`, `count == N_MAX`.
- **"Length > 1" is not one partition when the module stores, copies or allocates from the
  input.** Split it into typical and **long** (well past any stated size, ≥ 64 when none is
  stated). A mistake in the size arithmetic (`strlen(s) + 1`, `header + len`) stays invisible
  for short values and shows only on long ones. No branch depends on the length, so coverage
  will not point at it.
- **Implicit business rules** the docs omit but the domain reveals. In the digit-list `add`
  example, the *carry* was not in the docs; knowing arithmetic is what produced the tests
  that found the bug. In firmware this shows up as: saturation/clamp, counter wrap-around,
  hysteresis, dead zone, units (steps↔mm, degrees↔raw), sign.
- Internal states that change the behavior (see §2.4.12 — stateful classes).

### What to do with the result

Produce, per function, a **numbered catalog**: `<func>/P1, P2, …` for partitions and
`<func>/B1, B2, …` for boundaries. This catalog is the suite's traceability contract (see
Phase 3 and Phase 6 in SKILL.md). Each item gets a short description; each item becomes at
least one test; every test references at least one item.

---

## 3. How to identify boundaries

"Bugs love boundaries." An off-by-one (`>` where it should be `>=`) works for almost every
input and fails **near the transition** between partitions. Once you have defined the
partitions, neighboring partitions share nearby boundaries; the boundary test guarantees
correct behavior there.

### On point and off point (Jeng & Weyuker) — test two points at each boundary

Example: prints "hiphip" if `input < 10`, otherwise "hooray" (`input >= 10`). The boundary
lies between 9 and 10.

- **On point** — the point **on** the boundary: the number in the condition (`10`). Here it
  makes the program print "hooray".
- **Off point** — the point closest to the boundary that belongs to the partition
  **opposite** to the on point's: `9`, which still falls in "hiphip".

**Equality needs three tests.** If the condition were `input == 10`: one on point (`10`) and
**two** off points (`9` and `11`), because the boundary holds on both sides.

### In point and out point

- **In points** — values that make the condition **true** (11, 12, 25, 42 for
  `input >= 10`). There may be infinitely many.
- **Out points** — values that make the condition **false** (8, 7, −42).
- In an equality, the only in point is the condition's value; every other value is an out
  point.

On/off points already belong to specific partitions, so testing every boundary (on+off) is
**enough** and also serves as a concrete partition test. In/out points are somewhat
redundant, but adding a few makes the suite more realistic (§2.4.4).

**Aniche's trick:** look at all the partitions and think of inputs *between* them; whenever
you find one worth it, test it.

**Loops over chunked or chained data** (buffer chains, fragments, blocks, ring segments) have
a stop condition that is a boundary of its own. Besides "request longer than the data",
test the case where the requested length ends **before** the data does, exactly at a
chunk boundary, with more chunks after it whose bytes would also match. A wrong
length/counter update (e.g. growing instead of shrinking the remaining count) passes every
test where the data simply runs out, and only fails here.

Not every boundary becomes a new test: if the boundary case is already covered by another
test, **drop it** (do not duplicate).

---

## 4. §2.4 — real-world pragmatics

These rules exist so you produce the **leanest suite that still catches bugs**. Apply them
all; they are the antidote to a bloated, brittle or irrelevant suite.

- **Iterative, not sequential.** The 7 steps are not a rigid pipeline. While writing the
  tests you notice a missing partition and go back to improve the catalog.
- **How far to go? By the risk of failure.** What would a failure in *this* part cost? High
  cost → more corner cases, more techniques. Low cost → less exhaustive is enough. Stop when
  you have gone through the steps twice and see no more untested case.
- **Partition or boundary? It doesn't matter.** If a case arises as an "exclusive partition"
  instead of a "boundary between two", fine. What matters is that the case **exists** and
  the bug does not escape.
- **On/off are enough; in/out are a bonus.** Aim for the lean suite, but a few extra points
  are fine.
- **Vary the *same* input to ease understanding.** Use a single seed and change only the
  minimum to satisfy each partition (every `substringsBetween` test starts from "abc"). When
  a test fails, it is easy to compare it with the passing neighbors. (This contradicts the
  generic "vary everything" advice — which applies to broad exploration, done later through
  property-based testing.)
- **Combination explosion → be pragmatic.** (1) Reduce: isolate the exceptional (test
  NULL/empty **once**, do not combine it with everything) and use the domain to cut more.
  (2) If a method has too many combinations, **split it into two smaller methods** with
  well-defined contracts — each has less to test.
- **When in doubt, the simplest input.** A realistic but simple value, to ease debugging when
  it fails. Do not use a big integer if a small one works; do not use a 100-char string if 5
  are enough. The exception is the **long** length partition above: there, length is the
  point of the case.
- **Inputs you don't care about → reasonable values.** For the variable that does not take
  part in the behavior under test, pass any value — but prefer a **realistic** one.
- **NULL and exceptional cases only when they make sense. Context is king.** Test them
  because developers forget to handle them — but do not write a test that would never catch
  a bug. Understand the architecture: if the code is **near the edge/UI** (unsanitized
  input), exercise many corners; if it is **far from the edge** and the data already arrives
  sanitized by contract/precondition, you may skip them. *Only write tests that may one day
  catch a bug.* In firmware: a driver receiving directly from a protocol parser ⇒ test
  NULL/range; an internal function only called with data validated upstream ⇒ no need.
- **Tests with the same skeleton → parameterize.** A little duplication is not a problem; a
  lot is. 21 nearly identical tests (~105 lines) call for a parameterized test. Use the
  framework's parameterization (Unity: `TEST_CASE` params or a table loop; ztest: data-driven
  suites; etc.). Choosing between simple and parameterized is a matter of taste when the
  duplication is small.
- **Requirements at any granularity.** The technique works for a method or for a larger
  requirement. Still, **this skill is unit tests only** — the granularity is the
  function/module, never integration or system.
- **Stateful classes: the mechanics are the same.** When reasoning about the function,
  consider not only the parameters but the **state the class/module must be in**. E.g.
  `totalPrice()` → partitions zero items / one item / several items / varied quantities. You
  **set up the state** (add items) before calling the function under test. In firmware:
  initialize the handle/context, inject the state through the fakes, then call.
- **Experience and creativity (Step 7).** The systematic process reduces the reliance on
  experience, but does not remove it. After covering the catalog, ask: "does my instinct
  say this could fail somewhere?" and add interesting variations (in the example, strings
  with spaces). Four eyes are better than two: different models reveal new cases.

---

## 5. Full worked example — `substringsBetween(str, open, close)`

Finds the substrings between an `open` and a `close`. Serves as a template for how a catalog
grows.

**Partitions (Phase 3):**
- `str` alone: NULL / empty / length 1 / length > 1
- `open` alone: NULL / empty / length 1 / length > 1
- `close` alone: NULL / empty / length 1 / length > 1
- `(str, open, close)` in combination: str contains neither open nor close / contains open
  without close / contains close without open / contains both / contains both **multiple
  times**
- output (array): NULL / empty / one item / several; each string: empty / 1 char / several

**Boundary (Phase 4):** when str contains both and the length of the substring between them
goes from **0 to > 0** — the program stops returning empty and starts returning a substring.
Two candidate tests: (a) both with nothing between them; (b) both with characters between
them. (b) is already covered by another test ⇒ **dropped**; only (a) is kept.

**Combination reduction (Phase 5):** the full cartesian product would be 4×4×4×5 = 320 tests.
Isolating the exceptional (NULL/empty once each) and using the domain brings it down to
**21**. Step 7 added 2 (strings with spaces) → 23.

**Domain matters (digit-list `add`):** analyzing parameters finds many bugs, but it was
knowing the **carry** (an implicit rule) that produced the tests that found the real bug —
the only boundary that mattered was `99 + 1` (the carry propagates into a new most
significant digit). The lesson for firmware: implicit domain rules (saturation, wrap, units,
sign) are where the real bugs hide — invest Phase 3 reasoning there.
