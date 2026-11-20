# Rust coding practice

This guide describes good practice for writing Rust in our projects: Spider and the Rust components
of CLP. It is the companion of `coding-style.md`, which covers how code should look, and
`pr-review.md`, which covers how a review is run. This guide covers what the code should do: how to
use types, traits, errors, ownership, async and crate boundaries so that whole classes of bugs can't
be written, and the rest fail loudly instead of silently.

The rules are drawn from three sources: the Spider codebase and its review history
([y-scope/spider](https://github.com/y-scope/spider)), the Rust PRs and review comments in
[y-scope/clp](https://github.com/y-scope/clp), and Microsoft's
[RustTraining](https://microsoft.github.io/RustTraining/) books. Each rule links the PR comments,
files and book sections it came from. File links are permalinks to Spider
`d229555f31b40c63e2196a6d505cbbcc692cb91e` and CLP `2c617be50c21aa66968033bbcaefc4c2d8665fa2`.

## How to use this guide

The guide serves three audiences.

- **Humans learning the codebase.** Read the core principles, then each section's introduction. For
  each rule, the **Why** paragraph and the Bad/Good examples explain the bug the rule prevents. Most
  of them come from a real incident or review comment, cited under **Sources**.
- **Coding agents.** Follow the **Rule** paragraph of every rule that applies to the code you are
  writing. Treat **Exceptions** as the only sanctioned departures, and when one applies, say so in a
  comment or the PR description.
- **Review agents.** Walk the [Review checklist](checklist.md) against the diff, in addition to the
  checks in `pr-review.md`. Each rule's **Review** bullets say what to look for and which fix to ask
  for. Cite the rule ID in every comment (for example, "TYPE-4: `0` is used as a sentinel here ...")
  so the author can look up the reasoning.

Every rule has the same parts: **Rule** (what to do), **Why** (the failure it prevents), Bad and
Good examples, **Review** (what a reviewer flags), optional **Exceptions**, and **Sources**. The
examples are trimmed from real code, so most are marked `ignore`: they don't compile on their own.

Rule IDs (`TYPE-1`, `ASYNC-3`, ...) are stable references for comments, commit messages and other
documents. Don't renumber existing rules when adding new ones, and retire the ID of a removed rule
instead of reusing it.

**Precedence.** `coding-style.md` wins any conflict on style: naming, docstrings, formatting and
lint policy. This guide and `pr-review.md` are meant to agree. Where they overlap, this guide adds
the reasoning and the concrete checks, and the "See also" notes point at the related sections.

# Core principles

- **Make invalid states unrepresentable.** Put a value's meaning and allowed range in its type:
  newtypes for IDs and units, `NonZero*` for positive quantities, enums for modes and outcomes,
  `Option` for absence. (TYPE, TLC)
- **Validate once, at the boundary.** Parse external data into validated types where it enters the
  process. Code behind the boundary takes those types and never checks again. (TYPE-1, BND-1)
- **Let the compiler enforce contracts.** Exhaustive matches, move-only tokens, narrow trait bounds
  and const asserts turn "remember to" into a build error. (TLC-2, TLC-4)
- **Fail loudly and attributably.** Never invent a plausible value for bad input. Return a typed
  error that keeps its cause, handle and log it once, and take the service down when shared state is
  corrupt. (SRV-2, SRV-4, ERR-4, ERR-5)
- **Keep state changes atomic and cancel-safe.** Check before the first mutation, make
  check-then-act one step, and assume that any future can be dropped at any `.await`. (DEF-1, DEF-2,
  ASYNC-1, ASYNC-2)
- **Bound everything an outsider can size.** Cap the durations, allocations, queues and payloads a
  peer or config controls, and put a deadline on every external wait. (SRV-3, ASYNC-6, ASYNC-7,
  BND-7)
- **Own what you consume, borrow what you read.** Signatures state ownership honestly, and every
  resource and spawned task has an owner responsible for its cleanup. (OWN-1, OBJ-3, ASYNC-3)
- **Keep the public surface minimal and its contracts explicit.** Give items the narrowest
  visibility, give each type one owner, and mark every change to a serialized or cross-repo contract
  as breaking. (MOD-1, MOD-2, MOD-6)

# Table of contents

1. [Type safety](type-safety.md) (TYPE-1 to TYPE-10)
   - TYPE-1: Parse at the boundary into a type that proves the check ran
   - TYPE-2: Make a validated type unforgeable on every construction path
   - TYPE-3: Give every ID and unit its own type; a type alias is not a newtype
   - TYPE-4: Represent absence with `Option`, never with a sentinel
   - TYPE-5: Model exclusive modes and dependent fields as one enum or one struct
   - TYPE-6: Parse closed sets of strings into enums, with no catch-all default
   - TYPE-7: Choose the numeric type whose range is the invariant
   - TYPE-8: Convert numbers with `From`/`TryFrom`, never a lossy `as`
   - TYPE-9: Return and store named enums, not positional `bool`s
   - TYPE-10: Wrap encoded bytes in a type named after their encoding
2. [Type-level constraints, traits and generics](type-level-constraints.md) (TLC-1 to TLC-9)
   - TLC-1: Give each kind of ID its own type through a phantom marker
   - TLC-2: Bound each component by the narrowest capability it uses
   - TLC-3: Keep a statically known type as an associated type
   - TLC-4: Make a permit or proof a move-only token that only its owning module can mint
   - TLC-5: Use associated types for types each implementor fixes, and `Infallible` for impls that
     can't fail
   - TLC-6: Make a stateless strategy a type-only trait
   - TLC-7: Take `self: Box<Self>` in consuming methods called through a trait object
   - TLC-8: Use blanket impls only for behavior that is the same for every type
   - TLC-9: Use typestate only for statically ordered protocols
3. [Defensive programming](defensive-programming.md) (DEF-1 to DEF-5)
   - DEF-1: Run every check that can fail before the first mutation
   - DEF-2: Make check-then-act one atomic step
   - DEF-3: Choose an overflow behaviour for every arithmetic on unbounded values
   - DEF-4: Decode external input with checked slicing, never indexing
   - DEF-5: Confine `unsafe` behind a safe API, and state its contract in the right place
4. [Server design](server-design.md) (SRV-1 to SRV-5)
   - SRV-1: Let progress state only move forward
   - SRV-2: Turn unknown, missing or unsupported input into an error, never a plausible value
   - SRV-3: Cap every resource that a peer or a config value can size
   - SRV-4: Return errors for what the environment can cause, and fail the whole service for broken
     invariants
   - SRV-5: Retry only transient failures, with backoff, and only idempotent operations
5. [Error handling](error-handling.md) (ERR-1 to ERR-10)
   - ERR-1: Group error variants by the recovery action they need
   - ERR-2: Recover only from the variant you expect; propagate everything else
   - ERR-3: Add a variant only when a caller reacts differently, and give it typed fields
   - ERR-4: Keep the cause attached
   - ERR-5: Handle an error once: return it, or log it where the decision is made
   - ERR-6: Translate errors to wire responses in one exhaustive place, without leaking internals
   - ERR-7: Return expected outcomes in `Ok`, and keep `Err` for failures
   - ERR-8: Use `#[from]` only when the source type has one meaning
   - ERR-9: Make best-effort explicit in the signature
   - ERR-10: Give fallible trait methods an associated `Error` type
6. [Designing types and their methods](designing-types.md) (OBJ-1 to OBJ-10)
   - OBJ-1: Keep invariant-carrying fields private and make the validating path the only way in
   - OBJ-2: Return a ready-to-use value from every factory function
   - OBJ-3: Tie mandatory cleanup to a guard's `Drop`, and give the normal path a consuming method
   - OBJ-4: Give a type exactly the dependencies it owns
   - OBJ-5: Share state through a cloneable handle over one private `Arc`
   - OBJ-6: Expose domain operations, not the container or the call protocol
   - OBJ-7: Take required builder arguments up front and finish with a consuming `build(self)`
   - OBJ-8: Name methods for their contract
   - OBJ-9: Convert through the std traits
   - OBJ-10: Derive std traits when they are needed and when they mean the right thing
7. [Ownership, borrowing and performance](ownership-and-borrowing.md) (OWN-1 to OWN-10)
   - OWN-1: Take ownership exactly where the value must outlive the call
   - OWN-2: Expose the borrowed view, not the container
   - OWN-3: Consume at-most-once state with `Option::take` and `std::mem::take`/`replace`
   - OWN-4: Make a future-producing closure return an owned `async move` future
   - OWN-5: Keep per-item hot paths borrowed and allocation-free in the common case
   - OWN-6: Don't force `Arc` on callers; make shared ownership opt-in
   - OWN-7: Treat a clone that silences the borrow checker as a design smell
   - OWN-8: Borrow with in-task concurrency; spawn only for parallelism or detachment
   - OWN-9: Model graphs as an owning arena with indices, not `Rc`/`Arc` links
   - OWN-10: Use iterator adapters for pipelines and plain loops for multi-output state
8. [Async and concurrency](async-and-concurrency.md) (ASYNC-1 to ASYNC-10)
   - ASYNC-1: Make every future you race, time out or serve safe to drop
   - ASYNC-2: Run multi-step mutations where the caller can't cancel them
   - ASYNC-3: Give every spawned task an owner and a failure destination
   - ASYNC-4: Shut down through one token tree, with one deadline and an honest exit code
   - ASYNC-5: Never hold a lock across an `.await` that waits on someone else
   - ASYNC-6: Bound every queue, and handle every channel outcome
   - ASYNC-7: Don't block the executor, and put a deadline on every external wait
   - ASYNC-8: Write `biased;` when `select!` priority is part of correctness
   - ASYNC-9: Give shared mutable state one owning actor
   - ASYNC-10: Design async APIs around laziness and `Send`
9. [Serialization, config and external boundaries](external-boundaries.md) (BND-1 to BND-10)
   - BND-1: Validate external data while deserializing it, not afterwards
   - BND-2: Reject unknown keys in every schema you own, and tag enums explicitly
   - BND-3: Guard read-then-write DB transitions in the statement itself
   - BND-4: Convert wire messages to domain types in one fallible layer
   - BND-5: Load config and env vars at startup, and tell absent apart from invalid
   - BND-6: Make every default an intended value, owned in one place
   - BND-7: Bound and tolerate untrusted byte streams
   - BND-8: Keep secrets typed, unserialized, out of logs, and compared in constant time
   - BND-9: Treat wire status codes as a contract, and keep client-facing errors coarse
   - BND-10: Read DB rows through typed projections and re-validate them as persisted data
10. [Modules, crates and API surface](modules-and-crates.md) (MOD-1 to MOD-10)
    - MOD-1: Give every item the narrowest visibility its intended callers need
    - MOD-2: Treat every contract change as breaking, and make the breakage loud rather than
      tolerated
    - MOD-3: Declare each dependency once, pin cross-repo ones to a commit, and bump every reference
      together
    - MOD-4: Place code by dependency direction, and share it once a second consumer needs it
    - MOD-5: Make `mod.rs` a table of contents: declarations, named re-exports and the core type
    - MOD-6: Give each shared type one owning crate and one import path
    - MOD-7: Give user-facing crates a small facade, and keep transport and generated types private
    - MOD-8: Keep test-only code out of the production surface and dependency graph
    - MOD-9: Declare the intended visibility when staged code lands, and silence dead code with
      `expect`
    - MOD-10: Keep Cargo features additive and declare optional dependencies with `dep:`
11. [Testing and observability for correctness](testing-and-observability.md) (TEST-1 to TEST-10)
    - TEST-1: Assert the exact outcome, not a proxy for it
    - TEST-2: Bound every wait in a test, and guard loops that must make progress
    - TEST-3: Test each decision exhaustively, in the module that defines it
    - TEST-4: Make concurrency tests contend, and make them reproducible
    - TEST-5: Keep tests independent of process-global and shared state
    - TEST-6: Take the current time, output streams and awaited futures as inputs of the decision
      logic
    - TEST-7: Keep test doubles within the real contract, and gate test-only code out of production
    - TEST-8: Assert invariants over every output of hand-written algorithms and decoders
    - TEST-9: Log structured fields with the full error, and attach spans to spawned work with
      `.instrument`
    - TEST-10: Pin type-level guarantees with compile-fail tests
12. [Review checklist](checklist.md)
