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
- **Review agents.** Walk the [Review checklist](#review-checklist) at the end of this guide against
  the diff, in addition to the checks in `pr-review.md`. Each rule's **Review** bullets say what to
  look for and which fix to ask for. Cite the rule ID in every comment (for example, "TYPE-4: `0` is
  used as a sentinel here ...") so the author can look up the reasoning.

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

1. [Type safety](#type-safety) (TYPE-1 to TYPE-10)
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
2. [Type-level constraints, traits and generics](#type-level-constraints-traits-and-generics) (TLC-1
   to TLC-9)
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
3. [Defensive programming](#defensive-programming) (DEF-1 to DEF-5)
   - DEF-1: Run every check that can fail before the first mutation
   - DEF-2: Make check-then-act one atomic step
   - DEF-3: Choose an overflow behaviour for every arithmetic on unbounded values
   - DEF-4: Decode external input with checked slicing, never indexing
   - DEF-5: Confine `unsafe` behind a safe API, and state its contract in the right place
4. [Server design](#server-design) (SRV-1 to SRV-5)
   - SRV-1: Let progress state only move forward
   - SRV-2: Turn unknown, missing or unsupported input into an error, never a plausible value
   - SRV-3: Cap every resource that a peer or a config value can size
   - SRV-4: Return errors for what the environment can cause, and fail the whole service for broken
     invariants
   - SRV-5: Retry only transient failures, with backoff, and only idempotent operations
5. [Error handling](#error-handling) (ERR-1 to ERR-10)
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
6. [Designing types and their methods](#designing-types-and-their-methods) (OBJ-1 to OBJ-10)
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
7. [Ownership, borrowing and performance](#ownership-borrowing-and-performance) (OWN-1 to OWN-10)
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
8. [Async and concurrency](#async-and-concurrency) (ASYNC-1 to ASYNC-10)
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
9. [Serialization, config and external boundaries](#serialization-config-and-external-boundaries)
   (BND-1 to BND-10)
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
10. [Modules, crates and API surface](#modules-crates-and-api-surface) (MOD-1 to MOD-10)
    - MOD-1: Give every item the narrowest visibility its intended callers need
    - MOD-2: Treat every contract change as breaking, and make the breakage loud rather than
      tolerated
    - MOD-3: Declare each dependency once, pin cross-repo ones to a commit, and bump every reference
      together
    - MOD-4: Place code by dependency direction, and share it once a second consumer needs it
    - MOD-5: Make `mod.rs` a table of contents: declarations and named re-exports only
    - MOD-6: Give each shared type one owning crate and one import path
    - MOD-7: Give user-facing crates a small facade, and keep transport and generated types private
    - MOD-8: Keep test-only code out of the production surface and dependency graph
    - MOD-9: Declare the intended visibility when staged code lands, and silence dead code with
      `expect`
    - MOD-10: Keep Cargo features additive and declare optional dependencies with `dep:`
11. [Testing and observability for correctness](#testing-and-observability-for-correctness) (TEST-1
    to TEST-10)
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
12. [Review checklist](#review-checklist)

# Type safety

A value's type should say what the value means and which values are allowed, so the compiler rejects
a misuse before it can run. In practice this means four habits. Parse input once into a type that
can only hold checked values. Give IDs and units their own types instead of bare primitives. Use
`Option` instead of magic values. Use enums instead of strings, flag combinations and bare `bool`s.
Each rule below moves a check from "every caller has to remember it" to "a wrong value cannot be
written down". Newtypes, `NonZero*` and enums cost nothing at run time, so the only price is a few
lines of declaration.

## TYPE-1: Parse at the boundary into a type that proves the check ran

**Rule.** Convert raw input into a validated type exactly once, at the point where it enters the
program. Use `TryFrom<Raw>`, `FromStr`, or a `create`/`validate_and_create` factory function that
returns `Result<Self, _>`. Downstream functions, including the DB and wire write APIs, take the
validated type and never the raw parts. Do not write a `validate(&self) -> Result<()>` method that
leaves the raw value in circulation.

**Why.** A check that returns `()` proves nothing to the next function. Callers can skip it, and
every later layer either checks again or trusts blindly, so checks kept up by hand drift apart from
the fields they guard. If the only way to get a `ValidatedJobSubmission` is through its factory
function, then holding one proves the graph decoded, is non-empty and matches its input count.
Running that factory function before any spawn or DB write also means a malformed request fails as a
bad request, and there is nothing to roll back.

```rust,ignore
// Bad
impl CompressionUsageParams {
    pub fn validate(&self) -> Result<(), ClientError> { /* ... */ }
}

/// # Note
///
/// Assumes `task_graph` and `inputs` are consistent.
async fn register(&self, task_graph: &[u8], inputs: &[u8]) -> Result<JobId, DbError>;
```

```rust,ignore
// Good
pub struct ValidatedJobSubmission {
    task_graph: TaskGraph,
    inputs: TaskGraphInput,
}

impl ValidatedJobSubmission {
    pub fn create(graph: Vec<u8>, inputs: Vec<u8>) -> Result<Self, JobSubmissionError> {
        /* decode both, reject an empty graph, check that the input counts match */
    }

    pub fn into_parts(self) -> (TaskGraph, TaskGraphInput) {
        (self.task_graph, self.inputs)
    }
}

async fn register(&self, submission: &ValidatedJobSubmission) -> Result<JobId, DbError>;
```

**Review.**
- Flag `validate(&self) -> Result<()>` on a raw type, docstrings that say "assumes X and Y are
  consistent", and `let ... else { unreachable!("rejected by validation") }` that matches again on
  something an earlier check already looked at. Each of these means a type is missing. The fix is a
  parser that returns the checked value, already destructured.
- Flag downstream code that validates again, or that quietly clamps (`max(n, 1)`, `.min(20)`) a
  value the boundary already checked. That gives the value two sources of truth. Reject out-of-range
  input at the boundary, with an error that carries the offending value (see also coding-style.md §
  Assert preconditions instead of tolerating them).
- When the raw type is also the public OpenAPI schema, keep the public name on the raw type and name
  the checked type `Validated*`
  ([y-scope/clp#2197](https://github.com/y-scope/clp/pull/2197#discussion_r3069316981)).

See also: coding-style.md § Type-Level Validation, and BND-1 for running the parse inside serde.

**Sources.**

- [spider `spider-storage/src/job_submission.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/job_submission.rs#L62-L151): `ValidatedJobSubmission::create` decodes and checks before anything else runs
- [spider `spider-storage/src/state/service/state.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/state/service/state.rs#L227-L286): `register_job` parses first and maps failure to `BadRequest`
- [spider `spider-tdl-derive/src/task_macro.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-tdl-derive/src/task_macro.rs#L78-L182): counter-example: `validate_*` return `()`, then `unreachable!` re-matches
- [y-scope/spider#283](https://github.com/y-scope/spider/pull/283#discussion_r2927393656): reviewer proposes a submission type built only through graph + input validation
- [y-scope/spider#351](https://github.com/y-scope/spider/pull/351#pullrequestreview-4566073502): validation moves into `ValidatedJobSubmission`'s factory function
- [y-scope/clp#1989](https://github.com/y-scope/clp/pull/1989#discussion_r2807868044): reviewer proposes wrapping the validated config in a type passed down
- [y-scope/clp#2197](https://github.com/y-scope/clp/pull/2197#discussion_r3069316981): reviewer suggests `TryFrom` into `ValidatedCompressionUsageParams`, keeping the OpenAPI name
- [RustTraining type-driven-correctness-book § Parse, Don't Validate](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch07-validated-boundaries-parse-dont-validate.html#parse-dont-validate): validate once at the boundary, carry the proof in the type
- [RustTraining rust-patterns-book § Parse Don't Validate — `TryFrom` and Validated Types](https://microsoft.github.io/RustTraining/rust-patterns-book/ch15-crate-architecture-and-api-design.html#parse-dont-validate--tryfrom-and-validated-types): validate-then-use versus parsing into a `TryFrom` newtype

## TYPE-2: Make a validated type unforgeable on every construction path

**Rule.** Keep private every field that the invariant covers, and send every way of producing the
value through the single check. That covers `FromStr`, `TryFrom`, serde (through
`#[serde(try_from = "Raw")]`) and sqlx (through a `Decode` that parses). A validated type must not
have `pub` fields, a plain `#[derive(Deserialize)]`, an infallible `From<raw>`, an unchecked
`Default` or a `DerefMut`.

**Why.** A validating constructor guarantees nothing if one other path skips it. In Spider,
`TimeoutPolicy::validate` checks that `soft < hard`, but the fields are `pub`, so the protobuf
conversion builds `TimeoutPolicy { soft_timeout_ms, hard_timeout_ms }` straight from wire values and
never runs the check. `TaskContext::new` rejects a commit task that has no outputs, but the type
derives `Deserialize`, and the TDL side only ever gets the value from `rmp_serde::from_slice`, so
the check never runs where the value is used. A `DerefMut` to the inner value lets `*port = 0` undo
the invariant after construction.

```rust,ignore
// Bad
#[derive(Deserialize)]
pub struct TimeRange {
    pub begin: Option<i64>,
    pub end: Option<i64>,
}
```

```rust,ignore
// Good
#[derive(Deserialize)]
struct UncheckedTimeRange {
    begin: Option<i64>,
    end: Option<i64>,
}

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(try_from = "UncheckedTimeRange")]
pub struct TimeRange {
    begin: Option<i64>,
    end: Option<i64>,
}

impl TryFrom<UncheckedTimeRange> for TimeRange {
    type Error = ReversedTimeRangeError;

    fn try_from(raw: UncheckedTimeRange) -> Result<Self, Self::Error> {
        if let (Some(begin), Some(end)) = (raw.begin, raw.end)
            && begin > end
        {
            return Err(ReversedTimeRangeError { begin, end });
        }
        Ok(Self { begin: raw.begin, end: raw.end })
    }
}
```

**Review.**
- For any type with a fallible constructor, list every place the type is constructed (struct
  literals, `From` impls, derives, sqlx row decoding, proto conversions) and confirm that each one
  goes through the check. The usual hole is a `pub` field or a plain `derive(Deserialize)` sitting
  next to a fallible `new`.
- Flag `impl From<u16> for Port`, and parameters such as `fn f(id: impl Into<Validated>)` that let
  bare primitives back in. Use `TryFrom` or `FromStr`, and expose read-only accessors (`get`,
  `as_str`, `AsRef`) instead of `Deref` or `DerefMut`.
- When a consumer needs only part of the validated data, such as the compressed bytes a DB persists,
  give that part its own type that only the validator can build
  (`ValidatedCompressedJobSubmission`). The guarantee then travels with the data.

**Exceptions.** A wrapper with no invariant, such as an ID newtype, may have an infallible
`From<u64>`. For compile-time literals of a validated type, use one named panicking constructor
documented under `# Panics`, such as `NonEmptyString::from_static_str("default")` from
clp-rust-utils' `ExpectedNonEmpty`, rather than writing an `expect` at each call site.

See also: coding-style.md § Type-Level Validation, OBJ-1 (designing the type so mutations can't
break it) and BND-1 (the serde side).

**Sources.**

- [spider `spider-core/src/task/task_graph.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/task/task_graph.rs#L62-L126): `TimeoutPolicy`: a private `validate` next to `pub` fields
- [spider `spider-proto-rust/src/io.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-proto-rust/src/io.rs#L10-L33): the proto conversion builds `TimeoutPolicy` from wire values, unchecked
- [spider `spider-tdl/src/task_context.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-tdl/src/task_context.rs#L23-L77): `TaskContext::new` validates, yet the type also derives `Deserialize`
- [spider `spider-tdl/src/task.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-tdl/src/task.rs#L141-L157): the TDL gets `TaskContext` from `rmp_serde::from_slice`, skipping `new`
- [spider `spider-core/src/types/io/task_graph_input.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/types/io/task_graph_input.rs#L128-L183): private fields; only the builder and the decoder construct it
- [y-scope/spider#492](https://github.com/y-scope/spider/pull/492): `TaskGraphInput` rejects bad shared-payload references on every construction path
- [y-scope/spider#562](https://github.com/y-scope/spider/pull/562): `PreparedChild::create` validates a child's submission before it is stored
- [y-scope/spider#565](https://github.com/y-scope/spider/pull/565): the persisted bytes get their own type that only the validator builds
- [y-scope/clp#1769](https://github.com/y-scope/clp/pull/1769#discussion_r2611608845): reviewer proposes one `from_static` constructor instead of scattered `unwrap`s
- [y-scope/clp#2595](https://github.com/y-scope/clp/pull/2595): `DatasetName` validates through `FromStr`, `TryFrom`, serde and sqlx `Decode`
- [y-scope/clp#2652](https://github.com/y-scope/clp/pull/2652): `TimeRange` rejects a reversed range at deserialization
- [clp `clp-rust-libs/clp-rust-utils/src/types.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/clp-rust-utils/src/types.rs#L192-L223): `ExpectedNonEmpty::from_static_str`, the named panicking constructor
- [RustTraining type-driven-correctness-book § Case Study: IPMI FRU Data](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch07-validated-boundaries-parse-dont-validate.html#case-study-ipmi-fru-data): `ValidFru` has private fields and is built only via `TryFrom`
- [RustTraining rust-patterns-book § `impl Deref` for Newtypes — Power and Pitfalls](https://microsoft.github.io/RustTraining/rust-patterns-book/ch03-the-newtype-and-type-state-patterns.html#impl-deref-for-newtypes--power-and-pitfalls): what `Deref` on a newtype exposes

## TYPE-3: Give every ID and unit its own type; a type alias is not a newtype

**Rule.** When two values share a primitive representation but mean different things (a job ID and a
task ID, a session and a task instance, milliseconds and bytes), give each one a distinct newtype.
Spider does this with a shared `Id<TypeMarker>` and one uninhabited marker per kind; TLC-1 covers
how to build it. Do not use `pub type FooId = u64;` for a domain identifier. When another system
owns an identifier (a Spider task index, an archive UUID), use that system's type.

**Why.** `fn report(task_instance_id: u64, session_id: u64)` compiles with its arguments swapped,
and the bug only shows up much later as rejected or misattributed work. An alias just renames `u64`,
so it protects no better than the bare `u64`. Spider's `SessionId` and `TaskInstanceId` are both
`u64` aliases that appear in the same positional unpack tuples, where a destructuring pattern that
swaps them still compiles. In clp, `ArchiveId` started out as `type ArchiveId = NonEmptyString`,
which let any non-UUID string into the query interfaces. The `Uuid`-backed newtype that replaced it
rejects such strings at the boundary, and it is also `Copy`.

```rust,ignore
// Bad
pub type SessionId = u64;
pub type TaskInstanceId = u64;

fn report(task_instance_id: TaskInstanceId, session_id: SessionId) { /* ... */ }

report(session_id, task_instance_id); // compiles
```

```rust,ignore
// Good
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct Id<TypeMarker> {
    raw: u64,
    _marker: PhantomData<TypeMarker>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum SessionIdMarker {}
pub type SessionId = Id<SessionIdMarker>;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum TaskInstanceIdMarker {}
pub type TaskInstanceId = Id<TaskInstanceIdMarker>;

report(session_id, task_instance_id); // error[E0308]: arguments to this function are incorrect
```

**Review.**
- Flag any signature, struct field, tuple or error variant that holds two or more values of the same
  primitive or alias type with different meanings, and any new
  `pub type XxxId = <integer or string>`. The fix is the shared `Id<TypeMarker>` in Spider, or a
  shared newtype in `clp-rust-utils`. Implement serde, sqlx and `Display` once by delegating to the
  raw value, so the wire and DB formats stay the same.
- Flag call sites that unwrap with `.0` or `.get()` just to do arithmetic across units, and blanket
  operator impls on quantities. Implement only the operations that make sense, for example
  `EpochMillis - EpochMillis = Duration` with no `Add` between two timestamps.
- Flag a raw `u64` or `usize` for a peer system's identifier when that system exports a type for it.
  For example, [y-scope/clp#2681](https://github.com/y-scope/clp/pull/2681) replaced
  `task_index: u64` with `spider_core::task::TaskIndex`.

**Exceptions.** Config fields keep the house form of a `u64` with a unit suffix in the name, which
is what carries the meaning there (coding-style.md § Prefer `u64` seconds over `Duration` for time
config). `pub type` aliases for *external* types remain the house style (coding-style.md § Type
Aliases for External Types). This rule covers domain identifiers and quantities.

**Sources.**

- [spider `spider-core/src/types/id.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/types/id.rs#L29-L33): `Id<TypeMarker>`; `SessionId` and `TaskInstanceId` ([L174-L176](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/types/id.rs#L174-L176)) are still `u64` aliases
- [spider `spider-proto-rust/src/unpack/storage.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-proto-rust/src/unpack/storage.rs#L84-L113): an unpack tuple holding `SessionId` and `TaskInstanceId` side by side
- [spider `spider-execution-manager/src/client/storage.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/client/storage.rs#L101-L109): `report_task_success` takes both `u64` aliases positionally
- [clp `clp-rust-libs/clp-rust-utils/src/types.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/clp-rust-utils/src/types.rs#L16-L73): `ArchiveId`, a `Uuid` newtype whose serde and sqlx impls delegate to it
- [y-scope/clp#2420](https://github.com/y-scope/clp/pull/2420#discussion_r3654279704): reviewer asks for `IngestionJobId` and `S3ObjectMetadataId` instead of `u64`
- [y-scope/clp#2503](https://github.com/y-scope/clp/pull/2503#discussion_r3884620341): reviewer asks for a dedicated query job ID type in clp-rust-utils
- [y-scope/clp#2504](https://github.com/y-scope/clp/pull/2504#discussion_r3917430304): reviewer asks to replace raw-string archive IDs with a UUID type
- [y-scope/clp#2531](https://github.com/y-scope/clp/pull/2531): the `NonEmptyString` archive ID alias becomes a `Uuid`-backed newtype
- [y-scope/clp#2676](https://github.com/y-scope/clp/pull/2676#discussion_r4487980675): reviewer asks for Spider's task index type instead of a raw `u64`
- [y-scope/clp#2681](https://github.com/y-scope/clp/pull/2681): the handshake's `task_index` becomes `spider_core::task::TaskIndex`
- [y-scope/spider#337](https://github.com/y-scope/spider/pull/337): IDs stay typed `Id<TypeMarker>` while their raw value becomes `u64`
- [RustTraining type-driven-correctness-book § Newtypes for Physical Quantities](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch06-dimensional-analysis-making-the-compiler.html#newtypes-for-physical-quantities): unit newtypes turn mixed-unit arithmetic into compile errors
- [RustTraining rust-patterns-book § Newtype: Zero-Cost Type Safety](https://microsoft.github.io/RustTraining/rust-patterns-book/ch03-the-newtype-and-type-state-patterns.html#newtype-zero-cost-type-safety): distinct newtypes over one primitive, at no run-time cost

## TYPE-4: Represent absence with `Option`, never with a sentinel

**Rule.** Write "not set", "unlimited" or "not present" as `Option<T>`. When the present value has
its own constraint, use `Option<NonZero*>` or `Option<Validated>`. Do not use `0`, `-1`, `""`,
`u32::MAX`, an empty container, a defaulted ID or an `Option<bool>` third state for this. When an
external format uses a sentinel, convert it to `None` at the first parse step. Keep "absent"
separate from "malformed", and substitute a display placeholder only at the presentation edge.

**Why.** A sentinel looks exactly like a real value, so every consumer has to remember the magic
check, and the one that forgets works on made-up data. In
[y-scope/clp#2567](https://github.com/y-scope/clp/pull/2567), `max_num_results` used 0 to mean
"unlimited" while another layer had already replaced 0 with a default, so callers who left the field
out were silently capped. With `Option<NonZeroU32>`, `None` means unlimited and 0 is rejected.
Calling `.unwrap_or(0)` or `.ok()` on a parse result is just as bad: a corrupt field turns into "not
present", and the original error is lost.

```rust,ignore
// Bad
pub struct ResultsCacheOutput {
    pub max_num_results: u32, // 0 means unlimited
}

let sensor_num = bytes.get(7).copied().unwrap_or(0); // 0 is also a valid sensor
```

```rust,ignore
// Good
#[derive(Debug, Deserialize)]
pub struct ResultsCacheOutput {
    pub max_num_results: Option<NonZeroU32>, // `None` means unlimited
}

let sensor_num = bytes
    .get(7)
    .copied()
    .ok_or(Error::TruncatedRecord { len: bytes.len() })?;
```

**Review.**
- Flag docstrings such as "0 means ...", "-1 if unset" or "empty means none". Also flag
  `unwrap_or(0)`, `unwrap_or_default()` or `.ok()` on a parse or read in domain code, and
  comparisons such as `if n > 0` that decode a sentinel. Ask for `Option`, or for `?` when the
  failure is a real error.
- Flag `Default` impls on ID types, and `..Default::default()` in structs that hold IDs: a defaulted
  ID of 0 may exist in the DB. Use `Option<Id>` for "not yet assigned".
- When a producer sends a sentinel (for example an empty `timestamp_key` from the CLI or WebUI),
  turn it into `None` at that producer's edge. The backend type is then `Option<NonEmptyString>` and
  rejects `""`. SQL columns follow the same rule: make them nullable instead of storing `''`.

**Exceptions.** If `None` and "empty" would mean exactly the same thing, keep a single
representation, usually an empty `Vec` rather than `Option<Vec<_>>`
([y-scope/spider#293](https://github.com/y-scope/spider/pull/293#discussion_r3024981899)). In
storage, a self-reference can be a deliberate choice over NULL for index or write-cost reasons
([y-scope/spider#531](https://github.com/y-scope/spider/pull/531#discussion_r4309555633)), but write
the reason down.

See also: SRV-2 (unknown input is an error) and ERR-2 (don't hide errors with `.ok()`).

**Sources.**

- [y-scope/clp#1728](https://github.com/y-scope/clp/pull/1728#discussion_r2587287081): the S3 endpoint becomes optional instead of a hard-coded AWS URL
- [y-scope/clp#1776](https://github.com/y-scope/clp/pull/1776#discussion_r2625610254): reviewer settles on `Option<NonEmptyString>` for the endpoint
- [y-scope/clp#2180](https://github.com/y-scope/clp/pull/2180#discussion_r3085560909): reviewer: 0 is a limit of 0, and another layer already replaced it
- [y-scope/clp#2251](https://github.com/y-scope/clp/pull/2251#discussion_r3207531702): reviewer flags `Option<bool>` as a needless third state
- [y-scope/clp#2503](https://github.com/y-scope/clp/pull/2503#discussion_r3890492612): reviewer asks for `Option<NonZeroU32>` so that "unlimited" is expressible
- [y-scope/clp#2513](https://github.com/y-scope/clp/pull/2513#discussion_r3963857670): reviewer: pass `None`, never an empty string, for "no message"
- [y-scope/clp#2513](https://github.com/y-scope/clp/pull/2513#discussion_r4139055514): reviewer asks for a nullable column instead of an empty string
- [y-scope/clp#2567](https://github.com/y-scope/clp/pull/2567): an omitted result limit now means unlimited, not a silent default
- [y-scope/clp#2597](https://github.com/y-scope/clp/pull/2597#issuecomment-6375278635): an empty `timestamp_key` should become `None` at the CLI and WebUI
- [spider `spider-scheduler/src/core_impl/inbound_queue_reader.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/core_impl/inbound_queue_reader.rs#L155-L221): counter-example: an unpolled lane reports session ID `0`
- [spider `spider-core/src/types/id.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/types/id.rs#L35-L39): counter-example: `Default` for `Id` yields ID 0
- [RustTraining type-driven-correctness-book § Sentinel → `Option` at the Boundary](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch11-fourteen-tricks-from-the-trenches.html#trick-1--sentinel--option-at-the-boundary): convert a format's sentinel to `None` at the first parse
- [RustTraining python-book § Exercises](https://microsoft.github.io/RustTraining/python-book/ch16-best-practices.html#exercises): takeaway: return `Option` instead of a sentinel such as `""`

## TYPE-5: Model exclusive modes and dependent fields as one enum or one struct

**Rule.** When a value can be in exactly one of several shapes, use one enum whose variants each
carry exactly the data that shape needs. Examples are a config's output mode, a task that is an
index, a commit or a cleanup, and a job row that is pending or running. Do not use flat `Option`
fields, `bool`s that change together, reserved index values, or one struct whose nullable field
tells you which state it is in. When two values are only valid together (an ID and its password, a
session and its result stream), bundle them in one type and pass `Option<Bundle>` instead of two
independent `Option`s.

**Why.** N independent options or flags allow 2^N combinations, and most of them are illegal: a
network address *and* a cache limit, a running job with no Spider job ID, a resource-group ID with
no password. Every consumer then needs its own runtime check, and the one that misses it either
panics or sends the work to the wrong place. An enum makes those states impossible to write, and its
exhaustive `match` shows every site that needs updating when a mode is added. In
[y-scope/clp#2705](https://github.com/y-scope/clp/pull/2705#discussion_r4558363049), returning
`(Session, ResultStream)` let a caller pair one session's stream with a different session. An
`OpenSession` that only the registry can construct made that pairing impossible.

```rust,ignore
// Bad
pub struct SearchJobConfig {
    pub network_address: Option<(String, u16)>,
    pub write_to_file: bool,
    pub max_num_results: u32,
}

const COMMIT_TASK_INDEX: usize = usize::MAX;
```

```rust,ignore
// Good
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields, tag = "type", rename_all = "snake_case")]
pub enum QueryOutput {
    ResultsCache(ResultsCacheOutput),
    Network(NetworkOutput),
    File {},
}

pub enum TaskId {
    Index(TaskIndex),
    Commit,
    Cleanup,
}
```

**Review.**
- Flag structs with several `Option` fields whose docs say "only one of" or "ignored when X is set",
  groups of `is_*` booleans that describe one lifecycle, and `const` reserved values in an ID or
  index space.
- Flag a single `FromRow` struct with an `Option` column that encodes the row's state. Use one row
  type per query shape, or an enum over them
  ([y-scope/clp#2435](https://github.com/y-scope/clp/pull/2435#discussion_r3736816199)).
- Flag functions that take or return a tuple of values that must come from the same creation, and
  lossy projections of a config enum such as `Option<(&str, &str)>`. Pass the enum or the bundle
  instead, and put the variant-specific logic on it as a method.

**Exceptions.** Keep separate `Option` fields when every combination is valid and its meaning is
documented, for example an aggregation that runs regardless of `max_num_results`.

See also: coding-style.md § API design (named fields over positional tuples) and § Enum vs Trait
Objects.

**Sources.**

- [y-scope/clp#1962](https://github.com/y-scope/clp/pull/1962#discussion_r2912583038): take an `AwsAuthentication` instead of an `Option<(&str, &str)>` projection
- [y-scope/clp#2435](https://github.com/y-scope/clp/pull/2435#discussion_r3736816199): reviewer: keep pending and running row types apart, or use an enum
- [y-scope/clp#2561](https://github.com/y-scope/clp/pull/2561#discussion_r4264475291): reviewer: the result limit and the bucket size belong in one enum
- [y-scope/clp#2613](https://github.com/y-scope/clp/pull/2613#discussion_r4383914186): reviewer: the output must be one of three, so use an enum
- [y-scope/clp#2652](https://github.com/y-scope/clp/pull/2652): the `QueryOutput` enum replaces flat output fields and their combination checks
- [y-scope/clp#2705](https://github.com/y-scope/clp/pull/2705#discussion_r4558363049): reviewer proposes `OpenSession`, built only by the registry
- [y-scope/spider#464](https://github.com/y-scope/spider/pull/464#discussion_r3897529935): reviewer asks to bundle the ID and password in one credentials type
- [spider `spider-core/src/types/id.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/types/id.rs#L131-L142): `TaskId::{Index, Commit, Cleanup}`
- [spider `spider-storage/src/db/mariadb/tree_transition.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/db/mariadb/tree_transition.rs#L381-L386): `UpdateRows`: either every row carries outputs or none does
- [spider `spider-core/src/types/resource_group.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/types/resource_group.rs#L12-L20): `ExternalResourceGroupCredentials` bundles the external ID and its password
- [RustTraining python-book § Rust Enums — Data-Carrying Variants](https://microsoft.github.io/RustTraining/python-book/ch06-enums-and-pattern-matching.html#rust-enums--data-carrying-variants): each variant carries its own data, matched exhaustively

## TYPE-6: Parse closed sets of strings into enums, with no catch-all default

**Rule.** Turn every string or integer that names one of a closed set of values (a status, kind,
format or health level) into an enum at the boundary. Use a serde enum with `rename` or
`rename_all`, `FromStr`, strum's `EnumString`, or `#[sqlx(try_from = "i32")]`. Reject an unknown
value with an error that names it, and reuse the existing domain enum instead of writing a new
string-to-integer table.

**Why.** If code matches on strings, a typo becomes a value that never matches, and adding a variant
gives no compile error at the sites that need updating. A `_ =>` arm that maps unknown input to a
default variant is worse. A config typo such as `"extendedd"` silently gets the default mode, and an
unexpected value from a peer is classified as whatever the catch-all happens to return. A
hand-written `resolve_job_status(&str) -> Option<i32>` duplicates the enum, drifts away from it, and
lets bare integers into business logic;
[y-scope/clp#2197](https://github.com/y-scope/clp/pull/2197#discussion_r3068022834) removed exactly
that.

```rust,ignore
// Bad
fn parse_health(s: &str) -> HealthStatus {
    match s {
        "OK" => HealthStatus::Ok,
        "Warning" => HealthStatus::Warning,
        _ => HealthStatus::Critical,
    }
}
```

```rust,ignore
// Good
impl FromStr for HealthStatus {
    type Err = UnknownHealthError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "OK" => Ok(Self::Ok),
            "Warning" => Ok(Self::Warning),
            "Critical" => Ok(Self::Critical),
            other => Err(UnknownHealthError(other.to_owned())),
        }
    }
}

let health: HealthStatus = raw.parse()?;
```

**Review.**
- Flag a `String` field or parameter whose valid values could be listed, and `match` or `==` on
  string literals outside a parser. The fix is an enum parsed at the boundary.
- Flag `_ =>` arms in a parser, and in any `match` over a domain enum that decides behavior.
  When every variant is listed, the compiler points at the match when a variant is added.
- Flag a `HashMap<KeyEnum, V>` read through `map[&key]` when the key set is fixed. Use a struct with
  one field per key and `#[serde(deny_unknown_fields)]`, so a missing or misspelled key fails at
  parse time instead of panicking at the lookup
  ([y-scope/clp#1828](https://github.com/y-scope/clp/pull/1828#discussion_r2636456469)).

See also: coding-style.md § Avoid hardcoded state values and SRV-2 (unknown input is an error).

**Sources.**

- [y-scope/clp#1828](https://github.com/y-scope/clp/pull/1828#discussion_r2636456469): reviewer agrees that `names[&ClpDbNameType::Clp]` panics on a missing key
- [y-scope/clp#2197](https://github.com/y-scope/clp/pull/2197#discussion_r3068022834): reviewer: replace `resolve_job_status` and reuse `CompressionJobStatus`
- [RustTraining type-driven-correctness-book § The Cost of Runtime Checking](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch01-the-philosophy-why-types-beat-tests.html#the-cost-of-runtime-checking): a string `match` misses typos and new variants
- [RustTraining type-driven-correctness-book § `FromStr` as a Validation Boundary](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch11-fourteen-tricks-from-the-trenches.html#trick-5--fromstr-as-a-validation-boundary): an `"extendedd"` typo silently gets the default mode
- [RustTraining type-driven-correctness-book § Typed Telemetry Reads (Typed Commands + Dimensional Analysis, ch02 + ch06)](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch17-redfish-applied-walkthrough.html#section-4--typed-telemetry-reads-typed-commands--dimensional-analysis-ch02--ch06): its `parse_health` is the `_ =>` catch-all this rule rejects

## TYPE-7: Choose the numeric type whose range is the invariant

**Rule.** Declare capacities, pool sizes, intervals, divisors, rates and limits that must be
positive as `NonZeroUsize`, `NonZeroU64` or `NonZeroU16` in the struct that holds them, so
deserialization rejects 0. Call `.get()` where the value is used. Keep a plain integer only where 0
has a documented meaning. Choose the width and signedness from the real range and from every
consumer (wire, DB, C++ core, BSON), and add a validated newtype when those consumers disagree.

**Why.** A zero capacity panics in `mpsc::channel` or leaves every `Semaphore::acquire` waiting
forever. A zero divisor panics in `div_ceil`, a zero heartbeat period panics in
`tokio::time::interval` ([y-scope/spider#362](https://github.com/y-scope/spider/pull/362)), and a
zero tick interval busy-spins the scheduler loop. All of these fail far away from the config file
that caused them. In [y-scope/spider#367](https://github.com/y-scope/spider/pull/367), switching to
`NonZero*` deleted the hand-written `validate()` methods, their `InvalidConfig` variants and the
`Result` on the constructors. A type that merely looks tight can also backfire. In
[y-scope/clp#2561](https://github.com/y-scope/clp/pull/2561#pullrequestreview-5555514247), a
`NonZeroU32` millisecond bucket size overflows on a WebUI timeline longer than about 3 years, while
clp-s and MongoDB both expect `i64`. That is why the field is now `PositiveI64` (deserialized
`try_from = "NonZeroU64"`).

```rust,ignore
// Bad
#[derive(Deserialize)]
pub struct RegistryConfig {
    /// Must be positive; behavior for 0 is undefined.
    pub tracking_interval_ms: u64,
}

fn set_max_retries(max_retries: i64) -> Result<(), ConfigError> {
    if max_retries < 0 { /* ... */ }
}
```

```rust,ignore
// Good
#[derive(Deserialize)]
pub struct RegistryConfig {
    pub tracking_interval_ms: NonZeroU64,
    /// 0 means "poll without blocking".
    pub poll_timeout_ms: u64,
}

const DEFAULT_POOL_SIZE: NonZeroUsize = NonZeroUsize::new(8).expect("8 is non-zero");

fn set_max_retries(max_retries: u32) { /* ... */ }
```

**Review.**
- Flag a plain integer that is passed to `tokio::time::interval`, `mpsc::channel`, `Semaphore::new`,
  a division or a `%`, and any docstring saying "must be positive" or "behavior for 0 is undefined".
  The fix is a `NonZero*` field type.
- Flag range checks that can never fire, such as `port > 65535` on a `u16` or `n < 0` on a value
  that should be unsigned. Either the parameter has the wrong type, or the real check belongs where
  the wider type enters.
- Before accepting a numeric field's width, ask where else the value goes (a DB column, BSON, the
  C++ parser).

See also: coding-style.md § Use `u64` for sizes that may exceed 32-bit, SRV-3 (upper caps) and BND-6
(defaults that must not be zero).

**Sources.**

- [spider `spider-scheduler/src/config.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/config.rs#L15-L34): `connection_pool_size: NonZeroUsize`
- [spider `spider-scheduler/src/execution_manager_registry.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/execution_manager_registry.rs#L30-L38): the dead-EM cutoff and the tracking interval are `NonZeroU64`
- [spider `spider-scheduler/src/runtime.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/runtime.rs#L85-L164): `create_runtime` can fail only on registration, not on config
- [y-scope/spider#334](https://github.com/y-scope/spider/pull/334): adds the round-robin core, whose capacities and tick interval are config
- [y-scope/spider#362](https://github.com/y-scope/spider/pull/362): adds the EM binary, whose heartbeat intervals reach `tokio::time::interval`
- [y-scope/spider#367](https://github.com/y-scope/spider/pull/367): `NonZero*` fields replace `validate()`, `InvalidConfig` and fallible constructors
- [y-scope/spider#396](https://github.com/y-scope/spider/pull/396): adds the client's pool-size and retry settings
- [y-scope/clp#2150](https://github.com/y-scope/clp/pull/2150#pullrequestreview-4039460381): a zero `channel_capacity` panics at channel creation and kills the job
- [y-scope/clp#2561](https://github.com/y-scope/clp/pull/2561#pullrequestreview-5555514247): a `u32` bucket size overflows, so `PositiveI64` matches BSON's `i64`
- [y-scope/clp#2668](https://github.com/y-scope/clp/pull/2668#discussion_r4496882129): reviewer types the throughput divisors as `NonZeroU64`
- [clp `clp-rust-libs/clp-rust-utils/src/types.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/clp-rust-utils/src/types.rs#L140-L190): `PositiveI64`, deserialized `try_from = "NonZeroU64"`
- [RustTraining rust-patterns-book § The Solution: Parse Into Validated Newtypes with `TryFrom`](https://microsoft.github.io/RustTraining/rust-patterns-book/ch15-crate-architecture-and-api-design.html#the-solution-parse-into-validated-newtypes-with-tryfrom): `Port(u16)` checks only for 0, since `u16` caps the top

## TYPE-8: Convert numbers with `From`/`TryFrom`, never a lossy `as`

**Rule.** Use `T::from(x)` for conversions that are lossless by construction, and `T::try_from(x)`
for any conversion that narrows, changes sign or depends on the platform's pointer width. Map the
failure to an error that carries the offending value when the value comes from outside the component
(wire, DB, an auto-increment ID). Use `expect("...")` only when this code itself guarantees that the
value fits. Float-to-integer conversions have no `TryFrom`, so round the value and check
`is_finite()` and the range explicitly before the cast.

**Why.** `as` never fails. `300_u16 as u8` is 44, `-1_i64 as u64` is `u64::MAX`, `u64 as u32`
silently drops the high bits, and `f64::NAN as u32` is 0. The wrong value passes every type check
and ends up in a size, an offset or an ID. A cast that is safe today also turns lossy without
warning when someone widens the source type, whereas a `From` call stops compiling. Whether a failed
conversion returns an error or panics follows the house rule: an overflowing DB-generated ID is not
this component's bug, so it returns an error
([y-scope/clp#2017](https://github.com/y-scope/clp/pull/2017#discussion_r2849514515)).

```rust,ignore
// Bad
let job_id = result.last_insert_id() as u32;
let port = self.port as u16;
let mut handles = Vec::with_capacity(config.num_tasks as usize);
```

```rust,ignore
// Good
let raw_id = result.last_insert_id();
let job_id = CompressionJobId::try_from(raw_id)
    .map_err(|_| anyhow::anyhow!("the retrieved ID overflows: {raw_id}"))?;
let port = u16::try_from(self.port)
    .map_err(|_| invalid_argument(format!("port does not fit in `u16`: {}", self.port)))?;
let mut handles = Vec::with_capacity(usize::from(config.num_tasks));
let index = u64::try_from(task_index).expect("`usize` always fits in `u64`");
```

**Review.**
- Treat every narrowing, sign-changing or float-to-int `as` in a diff as a bug until shown
  otherwise, especially next to careful presence checks (`ok_or_else(..)? as u32`). The fix is
  `try_from` with a named error variant.
- Flag `as` where a `From` impl exists (`u8` to `usize`, `u16` to `i32`). A `From` call keeps
  compiling only as long as the conversion stays lossless.
- Keep DB-facing fields at the schema's width (for example `i64`) and convert at the edge, instead
  of casting inside the logic.

**Exceptions.** `as` is acceptable for a `#[repr]` enum to its discriminant, for a deliberate bit
reinterpretation with a comment, for a float-to-int cast right after an explicit range check, for an
integer-to-float conversion in metrics or ratios, where rounding is acceptable, and for a lossless
widening inside a `const` item, where `From` isn't callable (DEF-3).

See also: pr-review.md § Panic vs error returns, DEF-3 (overflow in arithmetic), BND-4 (proto
fields) and BND-7 (wire lengths).

**Sources.**

- [spider `spider-proto-rust/src/unpack/storage.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-proto-rust/src/unpack/storage.rs#L195-L206): `u16::try_from` on the wire port, with the value in the error
- [spider `spider-proto-rust/src/id.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-proto-rust/src/id.rs#L8-L34): `usize::try_from` errors on wire input; `u64::try_from` expects locally
- [spider `spider-core/src/types/io/mod.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/types/io/mod.rs#L134-L148): `as u8` on a `#[repr(u8)]` enum, the allowed exception
- [y-scope/spider#492](https://github.com/y-scope/spider/pull/492): `TaskGraphInputBuilder` converts shared input IDs with `u32::try_from`
- [y-scope/clp#1989](https://github.com/y-scope/clp/pull/1989#discussion_r2806928070): reviewer suggests `usize::from` instead of `as usize`
- [y-scope/clp#2017](https://github.com/y-scope/clp/pull/2017#discussion_r2849514515): an overflowing DB ID isn't this component's bug, so return an error
- [y-scope/clp#2180](https://github.com/y-scope/clp/pull/2180#discussion_r3085560909): reviewer: `u32` to `usize` isn't safe on every platform; use `try_into`
- [y-scope/clp#2224](https://github.com/y-scope/clp/pull/2224#discussion_r3149859975): the S3 object size goes from `i64` to `u64` through `try_into`
- [RustTraining c-cpp-book § Casting Hierarchy: Four C++ Casts → Rust Equivalents](https://microsoft.github.io/RustTraining/c-cpp-book/ch18-cpp-rust-semantic-deep-dives.html#casting-hierarchy-four-c-casts--rust-equivalents): `300_u16 as u8` wraps to 44; narrow with `TryFrom`
- [RustTraining csharp-book § Numeric Conversions](https://microsoft.github.io/RustTraining/csharp-book/ch03-built-in-types-and-variables.html#numeric-conversions): `as` truncates and wraps, while `try_from` returns a `Result`

## TYPE-9: Return and store named enums, not positional `bool`s

**Rule.** When a function's result tells the caller which state something ended in
(`TerminalStatus::{Finished, Failed}`, `Claim::{Claimed, Duplicate}`), or when its outcomes need
different handling (`Cancellability`), return a dedicated enum, even one with only two variants.
When a two-way kind is stored without a name, inside a tuple, a queue element or a message, use an
enum or a struct with a named field instead of a bare `bool`. A method that may only accept some of
a type's states takes a narrower enum only when that subset has three or more variants or its
variants carry data. A plain two-way choice stays a `bool` parameter.

**Why.** `Ok(true)` makes every reader remember which polarity means which state, and an inverted
condition passes review because `if cursor.claim(i)` reads correctly either way. A
`should_request_cancellation() -> bool` merges "already cancelling" (which is fine) with "already
succeeded" (which should be a 409), so every caller has to work the distinction out again.
Collapsing typed results into `has_errors: bool` throws away the information the next layer needs in
order to branch. `terminate(outcome: QueryJobOutcome)`, with variants `Succeeded`,
`Failed { error_message }` and `Cancelled`, makes "the job must be terminal" impossible to violate
and requires a message only on the variant that has one.

```rust,ignore
// Bad
/// Returns `true` if the job finished, `false` if it failed.
pub async fn shutdown(self) -> anyhow::Result<bool>;

let finalize_queue: VecDeque<(JobId, bool)> = VecDeque::new(); // `true` = commit?
```

```rust,ignore
// Good
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TerminalStatus {
    Finished,
    Failed,
}

pub async fn shutdown(self) -> anyhow::Result<TerminalStatus>;

enum FinalizeKind {
    Commit,
    Cleanup,
}

let finalize_queue: VecDeque<(JobId, FinalizeKind)> = VecDeque::new();
```

**Review.**
- Flag `-> bool` or `-> Result<bool, _>` when the docstring explains `true` and `false` as two
  states rather than as the answer to a yes/no question, and flag `bool`s inside stored tuples or
  messages.
- Flag classifier functions that map their own errors inside the classifier. The classifier should
  return the domain enum, built with an exhaustive `match` and no `_` arm, and the caller maps it to
  its own error or HTTP code.
- Flag `fn f(status: FullStatus)` followed by `assert!(status.is_terminal())`, where the terminal
  states number three or more or carry data. The fix is a narrower outcome enum.

**Exceptions.** A named binary input parameter stays a `bool`, because its parameter name carries
the meaning (coding-style.md § Prefer Booleans Over Small Enum Subsets). True predicates such as
`is_empty` and `is_valid_transition` also stay `bool`.

**Sources.**

- [y-scope/clp#2053](https://github.com/y-scope/clp/pull/2053#discussion_r2870451058): reviewer: don't return `bool` for different states, even binary ones
- [y-scope/clp#2513](https://github.com/y-scope/clp/pull/2513#pullrequestreview-5286744460): `TerminalQueryJobStatus` makes "must be terminal" unrepresentable
- [y-scope/clp#2589](https://github.com/y-scope/clp/pull/2589#discussion_r4355503709): reviewer suggests a three-state enum instead of a `bool`
- [y-scope/clp#2617](https://github.com/y-scope/clp/pull/2617): `request_cancellation` returns the job's `Cancellability` to the caller
- [y-scope/clp#2662](https://github.com/y-scope/clp/pull/2662#discussion_r4459562723): an enum reads clearer than a `bool` for `Claim`
- [spider `spider-scheduler/src/core_impl/resource_group_round_robin/scheduling_state.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/core_impl/resource_group_round_robin/scheduling_state.rs#L42-L47): `FinalizeKind::{Commit, Cleanup}`, stored in the finalize queue
- [clp `log-ingestor/src/ingestion_job_manager.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/log-ingestor/src/ingestion_job_manager.rs#L47-L53): `TerminalStatus::{Finished, Failed}`
- [clp `query-coordinator/src/job_handle.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/query-coordinator/src/job_handle.rs#L393-L478): `terminate(outcome: QueryJobOutcome)`
- [clp `query-coordinator/src/query_job_submitter/mod.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/query-coordinator/src/query_job_submitter/mod.rs#L37-L48): `QueryJobOutcome`, with a message only on `Failed`
- [RustTraining type-driven-correctness-book § From Parsed Events to Redfish Health: The Consumer Pipeline](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch07-validated-boundaries-parse-dont-validate.html#from-parsed-events-to-redfish-health-the-consumer-pipeline): replaces a lossy `has_critical_events: bool` with a typed summary

## TYPE-10: Wrap encoded bytes in a type named after their encoding

**Rule.** When a `Vec<u8>` holds one specific encoding, such as a msgpack-encoded `ExecutorError`, a
wire-framed task-input stream or zstd-compressed JSON, wrap it in a newtype named after that
encoding. Keep the field private. Let only the matching encoder create the value and only the
matching decoder read it. Carry the newtype through every layer, and take the raw bytes out only at
the I/O call that writes them.

**Why.** A bare `Vec<u8>` states its encoding only in a comment, and the compiler accepts any bytes
in its place. Spider's execution manager hit both failure modes. `Outcome::InTaskFailure` carries
"the msgpack-encoded `ExecutorError`" as a `Vec<u8>`, and the code that reports it renders those
bytes with `String::from_utf8_lossy`, so the failure message stored for every in-task failure is
mangled msgpack instead of the error text. Task inputs were also a plain `Vec<u8>`, so `Vec::new()`
type-checked as "no inputs" even though the executor expects a wire-framed stream. Every commit task
failed until [y-scope/spider#405](https://github.com/y-scope/spider/pull/405) replaced it with a
valid zero-frame buffer. With an encoding newtype, neither bug compiles: the only way to read the
error is `decode()`, and the only way to build inputs is the serializer.

```rust,ignore
// Bad
pub enum Outcome {
    /// `error` is the msgpack-encoded `ExecutorError`.
    InTaskFailure { error: Vec<u8> },
}

let message = String::from_utf8_lossy(&error).into_owned();
let commit_task_inputs: Vec<u8> = Vec::new();
```

```rust,ignore
// Good
pub struct MsgpackExecutorError {
    bytes: Vec<u8>,
}

impl MsgpackExecutorError {
    pub fn encode(error: &ExecutorError) -> Result<Self, rmp_serde::encode::Error> {
        Ok(Self { bytes: rmp_serde::to_vec(error)? })
    }

    pub fn decode(&self) -> Result<ExecutorError, rmp_serde::decode::Error> {
        rmp_serde::from_slice(&self.bytes)
    }
}

pub enum Outcome {
    InTaskFailure { error: MsgpackExecutorError },
}

let message = error.decode()?.to_string();
let commit_task_inputs: WireFramedTaskInputs = TaskInputsSerializer::new().release();
```

**Review.**
- Flag `Vec<u8>` fields, parameters and aliases, such as `Result<Vec<u8>, Vec<u8>>`, whose encoding
  is stated only in a comment or docstring. Ask for one newtype per encoding.
- Flag `String::from_utf8` or `from_utf8_lossy` on bytes that aren't UTF-8 text, and hand-built
  encoded buffers (`Vec::new()`, `vec![..]`, byte literals) where an encoder exists.
- Flag tests that check an encoded buffer with `is_empty()`. An empty buffer may not be a valid
  encoding, so assert on the decoded value instead.

**Exceptions.** Bytes whose encoding the holding code doesn't rely on, such as a payload it stores
or forwards unchanged for someone else to decode, can stay `Vec<u8>`.

See also: coding-style.md § Binary Serialization. BND-8 covers secrets, the other kind of byte
buffer that needs its own type.

**Sources.**

- [spider `spider-execution-manager/src/process_pool.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/process_pool.rs#L66-L83): `InTaskFailure { error: Vec<u8> }`, msgpack only by comment
- [spider `spider-execution-manager/src/runtime.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/runtime.rs#L541-L592): `from_outcome` renders that error with `String::from_utf8_lossy`
- [spider `spider-tdl/src/task.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-tdl/src/task.rs#L15-L21): `ExecutionResult = Result<Vec<u8>, Vec<u8>>`, documented only in prose
- [y-scope/spider#292](https://github.com/y-scope/spider/pull/292#discussion_r3024204286): reviewer: don't serialize byte arrays into UTF-8 strings
- [y-scope/spider#405](https://github.com/y-scope/spider/pull/405): a commit task's empty inputs are framed as a valid wire frame

# Type-level constraints, traits and generics

Rust's type system can turn "remember to check this" into "this doesn't compile". The rules below
use it where our bugs actually happen: IDs that get swapped, components that can reach more of the
backend than they should, types that get erased and then recovered with a panic, and permits that
get spent twice. Each rule also says when the machinery costs more than it saves. Reviewers should
match enforcement to how bad the bug would be in production, and should not ask for tokens or
typestate where an `assert!` or a value validated at the boundary is enough.

## TLC-1: Give each kind of ID its own type through a phantom marker

**Rule.** Represent identifiers that share a raw representation as `Id<TypeMarker>`: the raw value
plus `PhantomData`, with one uninhabited marker enum per entity, and implement encoding (serde,
sqlx, `Display`) once on the generic type. Put no bounds on the marker parameter in the struct
definition. Derive on every marker the full trait set that the wrapper derives, or implement the
wrapper's traits by hand without bounds.

**Why.** `fn register_task_instance(job_id: u64, execution_manager_id: u64)` still compiles when the
two arguments are swapped, and the bug only shows up as a wrong row in the DB. A
`pub type SessionId = u64;` alias gives no protection either. A marker per entity turns the swap
into a type error at no runtime cost. There is one trap: `#[derive(Clone, Copy, Hash)]` on
`Id<TypeMarker>` generates `impl<TypeMarker: Clone> Clone for Id<TypeMarker>`, even though
`TypeMarker` appears only inside `PhantomData`. In
[y-scope/spider#271](https://github.com/y-scope/spider/pull/271) the markers derived only
`Debug, PartialEq, Eq`, so `JobId` was silently neither `Copy` nor `Hash` despite the derive on
`Id`. [y-scope/spider#309](https://github.com/y-scope/spider/pull/309) had to add the missing
derives. Bounds on the definition itself (`Id<TypeMarker: Debug + PartialEq + Eq>`) gain nothing,
and every `impl` block has to repeat them.

```rust,ignore
// Bad
fn register_task_instance(job_id: u64, execution_manager_id: u64) -> Result<(), DbError>;

register_task_instance(execution_manager_id, job_id)?;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct Id<TypeMarker: Debug + PartialEq + Eq> {
    raw: u64,
    _marker: PhantomData<TypeMarker>,
}

#[derive(Debug, PartialEq, Eq)]
pub enum JobIdMarker {} // `JobId` is not `Copy` or `Hash`.
```

```rust,ignore
// Good
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct Id<TypeMarker> {
    raw: u64,
    _marker: PhantomData<TypeMarker>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum JobIdMarker {}
pub type JobId = Id<JobIdMarker>;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ExecutionManagerIdMarker {}
pub type ExecutionManagerId = Id<ExecutionManagerIdMarker>;

pub trait TaskInstanceStore {
    fn register_task_instance(
        &self,
        job_id: JobId,
        execution_manager_id: ExecutionManagerId,
    ) -> Result<(), DbError>;
}
```

**Review.**
- Flag signatures that take two or more raw `u64`/UUID IDs, or a new `pub type XxxId = u64;`. Ask
  for a marker and an `Id<..>` alias.
- Flag a new marker that doesn't derive every trait the wrapper derives. The doc example in spider's
  `id.rs` still shows the short `Debug, PartialEq, Eq` list, so don't copy it. Flag bounds on a new
  wrapper's definition, and ask for them to move to the `impl` blocks that need them.

**Exceptions.** A raw value may appear inside the one function that decodes it from a row or the
wire, as long as it is converted right away. IDs with real structure (for example
`TaskId::{Index, Commit, Cleanup}`) get their own enums. See also: TYPE-3, which says when an ID or
unit needs its own type, and coding-style.md § Type-Level Validation, which covers validated values;
this rule covers how identity is built.

**Sources.**

- [spider `spider-core/src/types/id.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/types/id.rs#L14-L172): generic `Id<TypeMarker>`, encodings on the generic, one marker per entity
- [y-scope/spider#271](https://github.com/y-scope/spider/pull/271): markers derive only `Debug, PartialEq, Eq` under a `Copy, Hash` wrapper
- [y-scope/spider#309](https://github.com/y-scope/spider/pull/309): change adds the missing `Hash` derive to every marker
- [RustTraining rust-patterns-book § Unit-of-Measure Pattern](https://microsoft.github.io/RustTraining/rust-patterns-book/ch04-phantomdata-types-that-carry-no-data.html#unit-of-measure-pattern): zero-sized markers in `PhantomData` keep same-representation values apart

## TLC-2: Bound each component by the narrowest capability it uses

**Rule.** Split a wide backend interface into role traits, and combine them in a supertrait only for
the composition root. Bound each generic component on just the traits it calls (`StateType:
IngestionJobState + SqsListenerState`). Don't add conveniences that turn one capability into
another, such as a `Reader::writer()`.

**Why.** Narrow bounds document what a component can do: a GC loop can't accidentally delete
resource groups, and the SQS listener can't call the S3 scanner's state methods. In
[y-scope/clp#2001](https://github.com/y-scope/clp/pull/2001#discussion_r2820703495) the reviewer
rejected `IngestionJobState: SqsListenerState + S3ScannerState`, because it forces every state
implementation to provide methods for job types it never runs. Mocks also shrink to the one trait
under test. In
[y-scope/spider#339](https://github.com/y-scope/spider/pull/339#discussion_r3383142317) a reviewer
removed a write-through-the-reader shortcut: the reader/writer split exists so that the types show
who can mutate shared outputs, and an escape hatch makes every reader a writer. Coding agents tend
to add such shortcuts just to make a change compile.

```rust,ignore
// Bad
pub trait IngestionJobState: SqsListenerState + S3ScannerState {}

pub struct SqsListener<StateType: IngestionJobState> {
    state: StateType,
}

async fn gc_loop(storage: Arc<MariaDbStorage>) { /* every DB method in reach */ }
```

```rust,ignore
// Good
pub trait IngestionJobState { /* job-type-agnostic: start, end */ }

pub trait DbStorage:
    ExternalJobOrchestration + InternalJobOrchestration + ResourceGroupManagement
{
}

pub struct SqsListener<StateType: IngestionJobState + SqsListenerState> {
    state: StateType,
}

async fn gc_loop<StorageType: InternalJobOrchestration>(
    storage: &StorageType,
) -> Result<(), DbError> {
    InternalJobOrchestration::delete_expired_terminated_jobs(storage, EXPIRE_AFTER_SEC).await
}
```

**Review.**
- Flag a component bounded on the aggregate trait, or written against the concrete backend
  (`MariaDbStorage`), when it uses only one role. Ask for the narrow bound. Where two role traits in
  scope share a short method name (`delete`, `fail`), call it as `Trait::method(&x)`.
- Flag methods that convert a restricted capability wrapper into a broader one. Ask for a dedicated
  API instead, for example initializing the value at construction.

**Exceptions.** The composition root that wires the service together may take the aggregate trait or
the concrete type. A server-side manager that only ever runs against one concrete state may use that
type directly ([y-scope/clp#2001](https://github.com/y-scope/clp/pull/2001#discussion_r2823380637)).
See also: pr-review.md § Trait surface minimization. That rule covers which methods a trait has, and
this one covers which traits a consumer can see.

**Sources.**

- [y-scope/clp#2001](https://github.com/y-scope/clp/pull/2001#discussion_r2820703495): reviewer questions `IngestionJobState: SqsListenerState + S3ScannerState`
- [y-scope/clp#2001](https://github.com/y-scope/clp/pull/2001#discussion_r2823380637): author narrows the bound per job; server-side manager keeps a concrete state
- [y-scope/spider#286](https://github.com/y-scope/spider/pull/286#discussion_r2943798775): bound each use on only the traits it needs; call as `Trait::method`
- [y-scope/spider#339](https://github.com/y-scope/spider/pull/339#discussion_r3383142317): reviewer rejects mutating through a reader and asks for a dedicated API
- [y-scope/spider#339](https://github.com/y-scope/spider/pull/339#discussion_r3383447442): author says the shortcut came from iterating with a coding agent
- [spider `spider-storage/src/db/protocol.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/db/protocol.rs#L131-L147): `DbStorage` aggregate supertrait over the role traits
- [clp `log-ingestor/src/ingestion_job/sqs_listener.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/log-ingestor/src/ingestion_job/sqs_listener.rs#L283-L293): `SqsListener` bounded on `IngestionJobState + SqsListenerState`
- [clp `log-ingestor/src/ingestion_job/state.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/log-ingestor/src/ingestion_job/state.rs#L5-L89): job-agnostic `IngestionJobState` plus per-job-type role traits

## TLC-3: Keep a statically known type as an associated type; don't erase it and recover it with `unreachable!`

**Rule.** If each implementor of a trait always produces one concrete type, make that type an
associated type (`type Manifest;`, `type Response;`) so callers keep it. Convert it into a shared
enum only at the boundary that actually needs the enum. In production code, treat `unreachable!` and
`let Enum::Variant(x) = y else { panic!(..) }` as signs that the type was erased too early.

**Why.** In [y-scope/clp#2620](https://github.com/y-scope/clp/pull/2620#discussion_r4402879713),
`Source::build_task_inputs` returned `Vec<CompressionInputSource>` even though each source
statically knew which manifest it built: `S3Config` only ever built `S3InputSource`. That forced the
S3 path to match its way back out with an `unreachable!`, and left enum accessors whose only callers
were tests. An untyped API such as `get(path) -> serde_json::Value` fails the same way, because
every caller has to guess the schema. With an associated type, a mismatch is a compile error and the
decoding lives in one implementation.

```rust,ignore
// Bad
trait Source {
    fn build_manifests(self, partitions: Vec<Vec<String>>) -> Vec<CompressionInputSource>;
}

let CompressionInputSource::S3(manifest) = input else {
    unreachable!("S3 sources produce only S3 manifests")
};
```

```rust,ignore
// Good
trait Source {
    type Manifest;

    fn build_manifests(self, partitions: Vec<Vec<String>>) -> Vec<Self::Manifest>;
}

impl Source for S3Source {
    type Manifest = S3InputSource;
    // ...
}

let input = CompressionInputSource::from(manifest);
```

**Review.**
- Flag a panic on an enum variant that the surrounding code statically knows. Ask for an associated
  type, plus a `From` impl into the enum at the boundary.
- Flag APIs that return `serde_json::Value`, `Vec<u8>` or a type-erased enum when each caller
  decodes the result itself. Ask for `trait Endpoint { type Response: DeserializeOwned;
  }` and a generic `execute<EndpointType: Endpoint>(..) -> Result<EndpointType::Response, _>`.

**Exceptions.** When the set of requests is chosen at runtime (for example from config), wrap the
typed requests in an enum so that each arm keeps its static type.

**Sources.**

- [y-scope/clp#2620](https://github.com/y-scope/clp/pull/2620#discussion_r4402879713): reviewer asks for an associated `Manifest` type to remove the `unreachable!`
- [clp `compression-coordinator/src/partition.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/compression-coordinator/src/partition.rs#L14-L49): `Source` trait with an associated `Manifest` type
- [RustTraining type-driven-correctness-book § The command trait (type-indexed dispatch)](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch02-typed-command-interfaces-request-determi.html#step-2--the-command-trait-type-indexed-dispatch): associated `Response` binds each command to its return type
- [RustTraining rust-patterns-book § Typed Commands — GADT-Style Return Type Safety](https://microsoft.github.io/RustTraining/rust-patterns-book/ch02-traits-in-depth.html#typed-commands--gadt-style-return-type-safety): replaces an untyped `Vec<u8>` API with per-command response types

## TLC-4: Make a permit or proof a move-only token that only its owning module can mint

**Rule.** When a value grants the right to do something at most once, or proves a precondition
(authenticated, slot reserved, subsystem ready), make it a struct with private fields and a
module-private constructor. Don't derive `Clone`, `Copy`, `Default` or `Deserialize` on it. Put the
spending operation on the token itself, as a method that takes `self`; it may be sync or async.
Don't express such a fact as a `bool` parameter, or as a method on a handle that many holders share.

**Why.** An earlier revision of [y-scope/spider#449](https://github.com/y-scope/spider/pull/449) put
the spend on the dispatch-queue reader, so any holder of any clone of the reader could decrement a
hint count it had no claim to. Once that happens, the counter stays wrong. With a move-only `Hint`,
spending twice (E0382) and forging a hint (E0451) are both compile errors, so reviewers don't have
to audit every call site. A `fn reset(is_admin: bool)` has the same problem in another form, because
the caller can just pass `true`. Each derive and each `pub` field is another way to forge the token.
An `async fn spend(self)` keeps the at-most-once guarantee too: the token moves into the future, so
dropping the future drops the token, and it can't be spent again. What cancellation can still break
is atomicity: if the spend updates the accounting and then awaits, a drop at that `.await` leaves
the count decremented without the work happening. Spider's `Hint` spend is synchronous because
both of its steps are; an async spend must be cancel-safe (ASYNC-1, ASYNC-2).

```rust,ignore
// Bad
impl DispatchQueueReader {
    pub fn spend_hint_and_try_recv(&self) -> Option<TaskAssignment> {
        self.inner.decrement_living_hint();
        self.inner.receiver.try_recv().ok()
    }
}
```

```rust,ignore
// Good
#[derive(Debug)]
pub struct Hint {
    reader: DispatchQueueReader,
}

impl Hint {
    pub fn consume_and_try_recv(self) -> Option<TaskAssignment> {
        self.reader.inner.decrement_living_hint();
        self.reader.inner.receiver.try_recv().ok()
    }

    const fn new(reader: DispatchQueueReader) -> Self {
        Self { reader }
    }
}
```

**Review.**
- Flag `Clone`/`Copy`/`Default`/`Deserialize` derives or `pub` fields on permit/proof types. Also
  flag a "call at most once" docstring on a `&self` method that mutates shared accounting.
- Flag `bool` parameters that assert a security or readiness fact, and ask for a `&Token` parameter
  instead. If the token must not be replayed against a different resource, make it borrow that
  resource (`Token<'session_lifetime>`), or make the guarded operation a method on the resource.
- For an async spend, flag accounting applied before an `.await` that can be cancelled. Ask to move
  it after the last such `.await`, or to run the spend where the caller can't cancel it (ASYNC-2).

**Exceptions.** A `bool` for a plain binary choice is still right (coding-style.md § Prefer Booleans
Over Small Enum Subsets). Dropping an unspent token is fine and needs no `Drop` impl, unless
abandoning it is itself a bug, in which case add a `Drop` guard (OBJ-3). See also: coding-style.md §
Take ownership when the value mustn't be used afterwards. This rule adds the private constructor,
the forbidden derives, and moving the spend off the shared handle. OBJ-10 covers derives in general,
and TEST-10 covers pinning the guarantee with a compile-fail test.

**Sources.**

- [y-scope/spider#449](https://github.com/y-scope/spider/pull/449): description explains the module-private, non-`Clone` `Hint` and the earlier reader-side spend
- [spider `spider-scheduler/src/core_impl/resource_group_round_robin/dispatch_queue.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/core_impl/resource_group_round_robin/dispatch_queue.rs#L419-L484): `Hint` with a private constructor and a synchronous consuming spend
- [RustTraining type-driven-correctness-book § Zero-Sized Types as Proof Tokens](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch04-capability-tokens-zero-cost-proof-of-aut.html#zero-sized-types-as-proof-tokens): private-field tokens that only the owning module can mint
- [RustTraining type-driven-correctness-book § Anti-Patterns to Avoid](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch13-reference-card.html#anti-patterns-to-avoid): `is_admin: bool` and `Clone` on single-use values

## TLC-5: Use associated types for types each implementor fixes, and `Infallible` for impls that can't fail

**Rule.** Use an associated type when each implementor fixes exactly one related type (`Error`,
`Batch`, `Item`, `Response`). Use a trait generic parameter only when one type legitimately
implements the trait several times (`From<SourceType>`). Give a trait that has several backends with
different failures `type Error: std::error::Error + Send + Sync + 'static`, and set `type Error =
Infallible` in an implementation that can't fail.

**Why.** A generic parameter says "this type may implement the trait many times". An encoder
produces one kind of batch and fails in one way, but `ResultEncoder<BatchType, ErrorType>` doesn't
say so. Every generic caller carries the extra parameters (`open<EncoderType, BatchType,
ErrorType>`), and nothing stops a second impl for the same encoder. Once one exists, every call that
relied on inference stops compiling with E0283 ("type annotations needed"). With associated types,
the batch and error belong to the encoder, so generic code names only `EncoderType` and reads
`EncoderType::Error`. A single shared error enum forces every backend's variants onto all backends.
A made-up `String` error on an infallible impl suggests failure paths that don't exist, and it
doesn't even satisfy a `std::error::Error` bound. `Infallible` does, and keeps `?` working in
generic code. The same trick compiles optional machinery out cleanly. Spider's disarmed test hooks return an
empty `enum InjectedFault {}` whose `From` impl is `match fault {}`, so the call sites are identical
in both builds and need no `#[cfg]`.

```rust,ignore
// Bad
pub trait ResultEncoder<BatchType, ErrorType>: Sized {
    fn new(archive_id: ArchiveId) -> Result<Self, ErrorType>;
    fn take_batch(&mut self) -> BatchType;
}

impl ResultEncoder<Vec<QueryResult>, String> for QueryResultEncoder {
    fn new(archive_id: ArchiveId) -> Result<Self, String> {
        Ok(Self { archive_id, batch: Vec::new() })
    }

    fn take_batch(&mut self) -> Vec<QueryResult> {
        std::mem::take(&mut self.batch)
    }
}

fn open<EncoderType, BatchType, ErrorType>(archive_id: ArchiveId) -> Result<EncoderType, ErrorType>
where
    EncoderType: ResultEncoder<BatchType, ErrorType>,
{
    EncoderType::new(archive_id)
}
```

```rust,ignore
// Good
pub trait ResultEncoder: Sized {
    type Batch: Send + 'static;
    type Error: std::error::Error + Send + Sync + 'static;

    fn new(archive_id: ArchiveId) -> Result<Self, Self::Error>;
    fn take_batch(&mut self) -> Self::Batch;
}

impl ResultEncoder for QueryResultEncoder {
    type Batch = Vec<QueryResult>;
    type Error = Infallible;

    fn new(archive_id: ArchiveId) -> Result<Self, Infallible> {
        Ok(Self { archive_id, batch: Vec::new() })
    }

    fn take_batch(&mut self) -> Vec<QueryResult> {
        std::mem::take(&mut self.batch)
    }
}

fn open<EncoderType: ResultEncoder>(
    archive_id: ArchiveId,
) -> Result<EncoderType, EncoderType::Error> {
    EncoderType::new(archive_id)
}
```

**Review.**
- Flag trait generic parameters where each type has only one impl. Flag shared error enums that
  collect variants from unrelated backends.
- Flag placeholder error types on infallible impls, and `#[cfg(feature = ..)]` repeated at every
  call site of an optional hook. Ask for `Infallible`, or for an empty error enum in a disarmed
  module.

**Exceptions.** A trait with one production backend plus test doubles (such as spider's storage
traits returning `DbError`) may keep a concrete error type.

See also: ERR-10 (when a trait method needs an associated `Error` at all).

**Sources.**

- [clp `clp-rust-libs/query-result-listener/src/encoding.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/query-result-listener/src/encoding.rs#L21-L67): `ResultEncoder` with associated `Batch` and a bounded associated `Error`
- [clp `clp-rust-libs/query-result-listener/src/test_utils.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/query-result-listener/src/test_utils.rs#L47-L85): test encoding and encoder set `type Error = Infallible`
- [spider `spider-storage/src/test_hooks/disarmed.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/test_hooks/disarmed.rs#L9-L20): empty `InjectedFault` enum whose `From` impl is `match fault {}`
- [RustTraining rust-patterns-book § Associated Types vs Generic Parameters](https://microsoft.github.io/RustTraining/rust-patterns-book/ch02-traits-in-depth.html#associated-types-vs-generic-parameters): one impl per type versus several impls per type
- [RustTraining rust-patterns-book § Exercise 6: Generic Trait with Associated Types](https://microsoft.github.io/RustTraining/rust-patterns-book/ch17-exercises.html#exercise-6-generic-trait-with-associated-types--40-min): associated `Error` set to `Infallible` for an in-memory store

## TLC-6: Make a stateless strategy a type-only trait

**Rule.** If a strategy carries no state, don't make callers construct and store a value of it.
Express it only through associated types, and put construction on the per-instance type as an
associated function (`EncodingType::Encoder::new(archive_id)`). If the strategy type is never
instantiated, make it an empty enum.

**Why.** A field holding a zero-sized strategy suggests that the strategy has state and that two
instances might differ. A factory method taking `&self` invites implementations to hide state there.
In [y-scope/clp#2676](https://github.com/y-scope/clp/pull/2676#discussion_r4488138722) the reviewer
put it this way: "it's not a variable, it should be just a type constraint".
[y-scope/clp#2682](https://github.com/y-scope/clp/pull/2682) then moved creation into
`ResultEncoder::new` and turned `SseEncoding` and the test encodings into empty enums.

```rust,ignore
// Bad
trait ResultEncoding {
    type Encoder: ResultEncoder;

    fn encoder(&self, archive_id: ArchiveId) -> Self::Encoder;
}

struct State<EncodingType: ResultEncoding> {
    encoding: EncodingType,
}
```

```rust,ignore
// Good
trait ResultEncoding {
    type Batch;
    type Encoder: ResultEncoder<Batch = Self::Batch>;
}

pub enum SseEncoding {}

let encoder = EncodingType::Encoder::new(archive_id)?;
```

**Review.**
- Flag struct fields whose type is a stateless strategy, and `&self` factory methods that ignore
  `self`. Ask for associated types plus an associated constructor on the product type.

**Sources.**

- [y-scope/clp#2676](https://github.com/y-scope/clp/pull/2676#discussion_r4488138722): reviewer: the encoding is not a variable, just a type constraint
- [y-scope/clp#2682](https://github.com/y-scope/clp/pull/2682): moves encoder creation into `ResultEncoder::new`; encodings become empty enums
- [clp `clp-rust-libs/query-result-listener/src/encoding.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/query-result-listener/src/encoding.rs#L5-L19): type-only `ResultEncoding` with `Batch`, `Error` and `Encoder`
- [clp `api-server/src/sse.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/api-server/src/sse.rs#L8-L53): `SseEncoding` as an empty enum, with its `SseEncoder`

## TLC-7: Take `self: Box<Self>` in consuming methods called through a trait object

**Rule.** If a method consumes `self` and is meant to be called on a trait object
(`Box<dyn Trait>`), declare it `self: Box<Self>`, not `self`.

**Why.** A by-value `self` can't be moved out of a `dyn Trait`, whose size is unknown, so the call
fails with E0161. The trait and the `Box<dyn Trait>` type still compile, so the mistake shows up
only at the first call, often in another crate.
[y-scope/spider#368](https://github.com/y-scope/spider/pull/368) changed `SchedulerCore::run` to
`self: Box<Self>` for this reason.

```rust,ignore
// Bad
#[async_trait]
pub trait SchedulerCore: Send {
    async fn run(self, cancellation_token: CancellationToken) -> Result<(), SchedulerError>;
}

core.run(cancellation_token).await?; // `core: Box<dyn SchedulerCore>`: E0161
```

```rust,ignore
// Good
#[async_trait]
pub trait SchedulerCore: Send {
    async fn run(self: Box<Self>, cancellation_token: CancellationToken)
        -> Result<(), SchedulerError>;
}

core.run(cancellation_token).await?;
```

**Review.**
- Flag a by-value `self` method on a trait that is used, or meant to be used, as `dyn`. Ask for
  `self: Box<Self>`, or for `where Self: Sized` if the method is only for concrete types.

**Exceptions.** Whether to use a trait object at all follows coding-style.md § Enum vs Trait
Objects: when the set of types is known at compile time, use an enum.

**Sources.**

- [y-scope/spider#368](https://github.com/y-scope/spider/pull/368): changes `SchedulerCore::run` to `self: Box<Self>` for `Box<dyn SchedulerCore>`
- [spider `spider-scheduler/src/core.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/core.rs#L39-L86): `SchedulerCore::run` takes `self: Box<Self>`
- [RustTraining rust-patterns-book § Dyn Compatibility (formerly "Object Safety")](https://microsoft.github.io/RustTraining/rust-patterns-book/ch02-traits-in-depth.html#dyn-compatibility-formerly-object-safety): the conditions a trait must meet to be used as `dyn`

## TLC-8: Use blanket impls only for behavior that is the same for every type: extension traits and smart-pointer forwarding

**Rule.** Write `impl<SomeType: Bound> Trait for SomeType` only when every type that meets the bound
should get the same behavior forever. Two cases qualify. The first is an extension trait whose
default method replaces copies of the same inherent method across crates. The second is a forwarding
impl such as `impl<ClientType: Client + ?Sized> Client for Arc<ClientType>`, shown in OWN-6.
Otherwise, write inherent methods or per-type impls.

**Why.** Copies of `from_yaml_file`, each with its own per-crate `ConfigError`, drifted apart.
[y-scope/spider#362](https://github.com/y-scope/spider/pull/362) replaced them with one `YamlConfig`
trait and a blanket impl over `DeserializeOwned`. A forwarding `Arc` impl lets generic code keep
requiring `Trait + Clone`, and lets a test hand an `Arc<Mock>` to an actor while keeping a handle to
inspect it. The `?Sized` bound is what makes `Arc<dyn Trait>` work. Blanket impls are hard to undo,
though: coherence forbids a more specific impl for any type the blanket impl already covers (E0119),
and adding a blanket impl to a published trait is a breaking change.

```rust,compile_fail
// Bad
pub trait Redact {
    fn redacted(&self) -> String;
}

impl<RedactedType: std::fmt::Debug> Redact for RedactedType {
    fn redacted(&self) -> String {
        format!("{self:?}")
    }
}

#[derive(Debug)]
pub struct Secret(String);

impl Redact for Secret {
    fn redacted(&self) -> String {
        "<redacted>".to_owned()
    }
}
```

```rust,ignore
// Good
pub trait YamlConfig: DeserializeOwned {
    fn from_yaml_file(path: &Path) -> Result<Self, ConfigError> {
        let file = File::open(path)?;
        Ok(yaml_serde::from_reader(file)?)
    }
}

impl<ConfigType: DeserializeOwned> YamlConfig for ConfigType {}
```

**Review.**
- Flag the same inherent method copied across types or crates when the types have only a bound in
  common. Ask for one extension trait in the shared utils crate (`clp-rust-utils` or
  `spider-utils`).
- Flag blanket impls over broad bounds (`Debug`, `Display`, `Serialize`) for behavior that some
  types will need to override.
- Flag tests that make a mock `Clone` with shared interior state only to satisfy a `Trait + Clone`
  bound. Suggest a forwarding `Arc` impl (OWN-6).

**Exceptions.** For behavior that only your own types have, add inherent methods. Extension traits
need an import, which makes their methods harder to find.

**Sources.**

- [y-scope/spider#362](https://github.com/y-scope/spider/pull/362): adds `YamlConfig` with a blanket impl, and a forwarding `Arc` impl
- [spider `spider-utils/src/config.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-utils/src/config.rs#L23-L47): `YamlConfig` extension trait with a blanket impl over `DeserializeOwned`
- [spider `spider-execution-manager/src/client/liveness.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/client/liveness.rs#L99-L115): forwarding `LivenessClient` impl for `Arc<LivenessClientType>` with `?Sized`
- [RustTraining rust-patterns-book § Blanket Implementations](https://microsoft.github.io/RustTraining/rust-patterns-book/ch02-traits-in-depth.html#blanket-implementations): blanket impls are irreversible because of coherence
- [RustTraining type-driven-correctness-book § Mixin Traits (Diagnostic Behaviors)](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch08-capability-mixins-compile-time-hardware-.html#mixin-traits-diagnostic-behaviors): blanket impls give behavior to every type with the capabilities

## TLC-9: Use typestate only for statically ordered protocols, and keep state data inside the state

**Rule.** When an object goes through three or more phases whose order is known at compile time and
which allow different operations, make it `Thing<StateType>`. Put each phase's operations in its own
`impl Thing<State>` block, and write transitions as methods that take `self`. Store data that exists
in only one state as fields of that state type, not as an `Option` on the wrapper. For two phases,
use two distinct types joined by a consuming conversion. Use an enum when the state comes from
runtime data, such as a DB row or a wire message.

**Why.** A runtime check like `if self.state != Active { return Err(..) }` has to be repeated in
every method, and any copy can be forgotten. With typestate, calling a method in the wrong state
fails with "no method named .. found" (E0599). An `Option` field shared by all states brings the
runtime check back: the book's own `IpmiSession<State>` keeps `session_id: Option<u32>` and calls
`.unwrap()` under a "guaranteed Some" comment in every `Active` method. When a transition can fail
in a recoverable way, hand the old state back (`Result<Next, (Error, Self)>`). Otherwise one failed
`.await` throws the connection away. Typestate has costs too: spider deliberately kept a single
`TaskContext` for all task kinds
([y-scope/spider#390](https://github.com/y-scope/spider/pull/390#issuecomment-4953671655)), and
documented rather than typed an internal-only invariant
([y-scope/spider#408](https://github.com/y-scope/spider/pull/408#issuecomment-5013945738)).

```rust,ignore
// Bad
pub struct Session<StateType> {
    base_url: String,
    auth_token: Option<String>,
    _state: PhantomData<StateType>,
}

impl Session<Authenticated> {
    fn auth_token(&self) -> &str {
        self.auth_token.as_deref().expect("authenticated session has a token")
    }
}
```

```rust,ignore
// Good
pub struct Connected;
pub struct Authenticated {
    auth_token: String,
}

pub struct Session<StateType> {
    base_url: String,
    state: StateType,
}

impl Session<Connected> {
    pub async fn login(
        self,
        credentials: &Credentials,
    ) -> Result<Session<Authenticated>, (LoginError, Self)> {
        match request_token(&self.base_url, credentials).await {
            Ok(auth_token) => Ok(Session {
                base_url: self.base_url,
                state: Authenticated { auth_token },
            }),
            Err(error) => Err((error, self)),
        }
    }
}
```

**Review.**
- Flag a state guard repeated across three or more methods when the order is fixed at compile time.
  Flag typestate wrappers that use `Option` fields plus `expect`, and transitions that take
  `&mut self`.
- Don't ask for typestate for two-phase flows, for state loaded at runtime, or for invariants the
  public API can't reach. A private field plus a documented invariant is enough there.
- Typestate can't stop a value from being dropped partway through the protocol. If abandoning a
  state is a bug, pair the type with a `Drop` guard or `#[must_use]` (OBJ-3).

**Exceptions.** For prototypes, and for private helpers inside one function, an `assert!` is enough.
See also: coding-style.md § Take ownership when the value mustn't be used afterwards,
coding-style.md § Type-Level Validation for the two-phase raw → validated case, OBJ-7 for typestate
builders, and TEST-10 for pinning the guarantee with a compile-fail test.

**Sources.**

- [RustTraining type-driven-correctness-book § Type-State Pattern](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch05-protocol-state-machines-type-state-for-r.html#type-state-pattern): `IpmiSession<State>`, including the shared `Option` field and `.unwrap()` calls
- [RustTraining type-driven-correctness-book § Async Type-State Machines](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch11-fourteen-tricks-from-the-trenches.html#trick-8--async-type-state-machines): consuming transitions that hand back the previous state on error
- [RustTraining type-driven-correctness-book § When NOT to Use These Patterns](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch01-the-philosophy-why-types-beat-tests.html#when-not-to-use-these-patterns): `assert!` suffices for prototypes and small internal helpers
- [y-scope/spider#390](https://github.com/y-scope/spider/pull/390#issuecomment-4953671655): keep one `TaskContext` type for all task kinds, for user ergonomics
- [y-scope/spider#408](https://github.com/y-scope/spider/pull/408#issuecomment-5013945738): internal-only invariant documented rather than encoded in the type system

# Defensive programming

Defensive code assumes three things: input is hostile, peers retry, crash and restart, and the next
person to touch the code will add a variant, raise a constant or reorder a step. The goal is not to
check everything everywhere. Let the compiler catch what it can, check once at the boundary what it
can't, and make any remaining violation loud and attributable rather than quiet and corrupting. This
matters most in long-running services like ours, where a silently wrong value or a stray panic in a
coordinator costs far more than an error returned to one caller.

## DEF-1: Run every check that can fail before the first mutation

**Rule.** In a function that changes state (memory, DB, a queue, a file) and can fail, do all
validation, lookups, size checks and config checks first, computing new values into locals, and only
then commit them. After the first mutation, only a bug or an infrastructure failure may still
produce an error. A lookup that the earlier validation guarantees should use `expect` with a message
naming that validation.

**Why.** A `?` between two mutations leaves the object half-updated while telling the caller that
the request was simply rejected, and the caller then retries against corrupt state. In Spider, a
wrong output count was only detected after the task had been marked succeeded, so one bad client
report shut down the whole storage service instead of failing a single task instance. In clp, a
`channel_capacity` of 0 made `mpsc::channel` panic after the ingestion-job row was already inserted,
and the recovery path hit the same panic on every restart. Putting the checks first makes failures
atomic, and it keeps "error after a mutation" a reliable sign of a bug.

```rust,ignore
// Bad
fn reload(&mut self) -> Result<(), Error> {
    self.endpoints = load_endpoints()?;
    self.credentials = load_credentials()?; // on error: new endpoints, old credentials
    Ok(())
}
```

```rust,ignore
// Good
fn reload(&mut self) -> Result<(), Error> {
    let endpoints = load_endpoints()?;
    let credentials = load_credentials()?;
    self.endpoints = endpoints;
    self.credentials = credentials;
    Ok(())
}

let dep_indices = self.validate_and_retrieve_input_dep_indices(&input_sources)?;
for dep_idx in dep_indices {
    self.deps
        .get_mut(dep_idx)
        .expect("indices should be validated in the previous step")
        .add_dst(task_idx);
}
```

**Review.**
- In each state-changing function, find the first mutation and look for a `?` on a request-dependent
  check after it. The usual fix is to move the check above the mutation, or to split a read-only
  `ensure_*(&self) -> Result<..>` from an infallible `&mut self` apply step. Typing the code after
  the mutation as `Result<_, InternalError>` lets the compiler enforce the split.
- Config values that reach panicking constructors (`mpsc::channel(0)`, `Semaphore::new` above
  `MAX_PERMITS`) must be validated, or typed as `NonZero*` (TYPE-7), before the first durable write
  and before anything is spawned.
- Where a partial mutation can't be avoided (a DB write, then the cache), ask for a drop guard that
  is armed right after the first mutation, triggers fatal shutdown and recovery if it is dropped
  while still armed, and is disarmed by a consuming method at the hand-off point. OBJ-3 shows one
  (`PartialMutationGuard`).

See also: coding-style.md § Type-Level Validation (where the validated-config types come from) and §
Take ownership when the value mustn't be used afterwards (for the guard's `disarm(self)`), and OBJ-7
(a builder's `add` validates before it changes state).

**Sources.**

- [y-scope/spider#554](https://github.com/y-scope/spider/pull/554): `PartialMutationGuard`; output count is now checked before marking success
- [y-scope/spider#560](https://github.com/y-scope/spider/pull/560): the outputs-size check runs before the report touches the task
- [y-scope/spider#290](https://github.com/y-scope/spider/pull/290): adds the task control block whose success path a later PR reorders
- [y-scope/clp#2150](https://github.com/y-scope/clp/pull/2150#pullrequestreview-4039460381): `channel_capacity` 0 panicked after the job row was inserted, on every restart
- [spider `spider-core/src/task/task_graph.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/task/task_graph.rs#L693-L737): `TaskGraph::compute_and_update_dependencies_from_inputs` validates, then `expect`s while mutating
- [spider `spider-storage/src/cache/task.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/cache/task.rs#L455-L518): `SharedTaskControlBlock::succeed_task_instance` checks the output count before the first mutation
- [spider `spider-storage/src/partial_mutation.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/partial_mutation.rs#L16-L95): `PartialMutationGuard`: fatal on drop, disarmed by `disarm(self)`
- [spider `spider-storage/src/task_instance_pool.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/task_instance_pool.rs#L503-L544): `create_task_instance_pool` validates its config before creating the channel and spawning
- [RustTraining c-cpp-book § Exception Safety → Panic Safety](https://microsoft.github.io/RustTraining/c-cpp-book/ch18-cpp-rust-semantic-deep-dives.html#exception-safety--panic-safety): `?` before the single commit gives the strong guarantee

## DEF-2: Make check-then-act one atomic step

**Rule.** When shared state is checked and then changed based on the result, do both in one atomic
operation: `entry()` on a concurrent map such as `DashMap`, a single `compare_exchange`,
`fetch_update` or `fetch_max` on an atomic, or one lock guard held across the check and the write.
BND-3 covers the same race in the database.

**Why.** Between a check and a separate write, another task can change the state, and the write then
acts on a check that no longer holds. On a `DashMap`, each call such as `contains_key` or `insert`
takes and releases its shard lock on its own. Two `open` calls can both see a token as free, and the
second silently replaces the first session. `entry()` holds the shard lock across both steps, which
is how clp's session registry registers tokens
([y-scope/clp#2689](https://github.com/y-scope/clp/pull/2689)). Clippy doesn't catch this:
`clippy::map_entry` only flags the std `HashMap`/`BTreeMap` `if !contains_key { insert }` form, as a
performance lint. It says nothing about `DashMap`, a map behind a lock taken twice, or atomics.

```rust,ignore
// Bad
let token = SessionToken::generate();
if self.sessions.contains_key(&token) {
    return Err(SessionError::TokenCollision(token));
}
// Another `open` can insert the same token here.
self.sessions.insert(token, session_state);
```

```rust,ignore
// Good
let token = SessionToken::generate();
let Entry::Vacant(entry) = self.sessions.entry(token) else {
    return Err(SessionError::TokenCollision(token));
};
entry.insert(session_state);
```

**Review.**
- Flag `contains_key` or `get` followed by `insert` or `remove` on a concurrent map, a `load`
  followed by `store` on an atomic, and a read under one lock guard followed by a write under
  another. Ask for `entry()`, one CAS, or one guard held across both. For async locks, see ASYNC-5
  (re-check under the write guard).

**Exceptions.** State owned by a single writer (an actor, a committer) is already atomic where that
writer checks and acts (ASYNC-9). A caller-side check is fine as long as it is advisory and the
single writer re-checks the precondition before committing, as Spider's committer does with
`StateRequirement`.

**Sources.**

- [y-scope/clp#2689](https://github.com/y-scope/clp/pull/2689): `open_session` registers a fresh token, failing with `TokenCollision` if taken
- [clp `clp-rust-libs/query-result-listener/src/session/registry.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/query-result-listener/src/session/registry.rs#L60-L72): `SessionRegistry::open` registers a fresh token through `entry()`
- [y-scope/clp#2662](https://github.com/y-scope/clp/pull/2662): `TaskCursor::claim` advances the cursor with one compare-and-swap
- [spider `spider-storage/src/cache/job.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/cache/job.rs#L860-L895): `submit_event_and_wait_for_reply`: the committer re-checks `StateRequirement`

## DEF-3: Choose an overflow behaviour for every arithmetic on unbounded values

**Rule.** For arithmetic on values that come from outside or grow without a proven bound (sizes,
offsets, counts, retry counters, `Instant`/`SystemTime` plus or minus a `Duration`), use `checked_*`
and return an error when overflow means bad input or corruption. Use `saturating_*` when clamping is
the intended meaning, with a comment on why if that isn't obvious, and `wrapping_*` only for
genuinely modular arithmetic. Convert between numeric types as TYPE-8 describes, never with a lossy
`as`.

**Why.** Overflow on `+`, `-`, `*` and `<<` panics in debug builds and wraps silently in release
builds. Cargo's release profile defaults to `overflow-checks = false`, and neither the clp nor the
Spider workspace overrides it; turning it on would only trade the silent wrap for a panic. Atomic
`fetch_add`/`fetch_sub` always wrap, in debug builds too. The tests pass, and production then gets a
tiny timeout from `value * 3600`, a counter of `u64::MAX` remaining tasks so the job never finishes,
or an offset that wraps into a valid-looking index. `as` never fails either: `u128 as u64`
truncates, `f64 as u32` turns NaN into 0, and `i64 as u64` flips the sign. `Instant + Duration`
panics when the sum is out of range, and that range is platform-specific (on Linux
`Duration::from_millis(u64::MAX)` still fits, `Duration::from_secs(u64::MAX)` does not), so adding a
client-chosen `wait_time` to `Instant::now()`, as Spider's resource-group dispatch queue does, is
safe only by accident of the unit.

```rust,ignore
// Bad
let remaining = job.num_incomplete_tasks.fetch_sub(1, Ordering::AcqRel) - 1;
let deadline = Instant::now() + wait_time;
let delay = INITIAL_BACKOFF * (1 << retry);
query.bind(limit as i64);
```

```rust,ignore
// Good
let remaining = job
    .num_incomplete_tasks
    .fetch_update(Ordering::AcqRel, Ordering::Acquire, |count| count.checked_sub(1))
    .map(|previous| previous - 1)
    .map_err(|_| InternalError::TaskGraphCorrupted("incomplete-task counter underflow".to_owned()))?;
let deadline = Instant::now()
    .checked_add(wait_time)
    .ok_or(DispatchError::InvalidWaitTime(wait_time))?;
let delay = u32::try_from(retry)
    .ok()
    .and_then(|shift| 1u32.checked_shl(shift))
    .and_then(|multiplier| INITIAL_BACKOFF.checked_mul(multiplier))
    .map_or(max_backoff, |delay| delay.min(max_backoff));
query.bind(i64::try_from(limit).expect("limit is bounded by `Semaphore::MAX_PERMITS`, which fits in i64"));
```

**Review.**
- Flag `-` and `fetch_sub` on a counter whose zero has meaning, and `+`, `*` or `<<` on
  input-derived values or loop counters, and ask which behaviour is meant. An unexpected zero on a
  counter is a corruption error, not something to wrap past; on an atomic, `fetch_update` with
  `checked_sub` leaves the counter intact when it reports the error.
- Flag `Instant + Duration` and `SystemTime + Duration` with a caller-controlled duration, and ask
  for `checked_add`. Lossy `as` casts are covered by TYPE-8.
- A test gated on `#[cfg(debug_assertions)]` or `#[should_panic(expected = "overflow")]` shows the
  release build wraps. Ask for checked arithmetic instead.

**Exceptions.** Arithmetic on values that are provably small where they are computed (constants, an
index over a slice already in hand), modular hashing or sequence numbers, which should use
`wrapping_*` explicitly, and a lossless widening `as` inside a `const` item, where `From` isn't
callable (SRV-3's `MAX_TASK_INSTANCE_MESSAGE_SIZE as u64`).

See also: coding-style.md § Use `u64` for sizes that may exceed 32-bit; pr-review.md § Panic vs
error returns (which classes overflow from external IDs as an error).

**Sources.**

- [y-scope/spider#396](https://github.com/y-scope/spider/pull/396): the retry backoff's doubling is overflow-safe
- [y-scope/spider#472](https://github.com/y-scope/spider/pull/472#discussion_r3980589460): cap the wait time and detect `Instant` overflow with `checked_add`
- [y-scope/spider#395](https://github.com/y-scope/spider/pull/395): reschedules assignments through the resource-group dispatch queue
- [y-scope/spider#290](https://github.com/y-scope/spider/pull/290#discussion_r2984962083): a child's unfinished-parent counter reaching 0 early is a corruption
- [spider `spider-utils/src/grpc/retry.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-utils/src/grpc/retry.rs#L154-L168): `backoff` uses `checked_shl`/`checked_mul` and falls back to the cap
- [spider `spider-storage/src/cache/job.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/cache/job.rs#L528-L591): `SharedJobControlBlock::succeed_task_instance` computes `fetch_sub(1, ..) - 1`
- [spider `spider-scheduler/src/core_impl/resource_group_round_robin/dispatch_queue.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/core_impl/resource_group_round_robin/dispatch_queue.rs#L259-L283): `DispatchQueueRegistry::dequeue_pinned` adds a client-chosen `wait_time` to `Instant::now()`
- [spider `spider-task-executor/src/bin/spider_task_executor.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-task-executor/src/bin/spider_task_executor.rs#L128): `u64::try_from(..).unwrap_or(u64::MAX)` saturates the elapsed time
- [y-scope/clp#2435](https://github.com/y-scope/clp/pull/2435#discussion_r3754801204): `i64::try_from(limit).expect(..)`, bounded by `Semaphore::MAX_PERMITS`
- [y-scope/clp#2402](https://github.com/y-scope/clp/pull/2402#discussion_r3625644781): `saturating_mul` so the poll backoff can't overflow
- [y-scope/clp#2403](https://github.com/y-scope/clp/pull/2403#pullrequestreview-4739365794): decrement the buffered size per file so the no-underflow argument stays local
- [RustTraining engineering-book § Release Profile Anatomy](https://microsoft.github.io/RustTraining/engineering-book/ch07-release-profiles-and-binary-size.html#release-profile-anatomy): the release profile defaults to `overflow-checks = false`
- [RustTraining rust-patterns-book § Unit Tests, Integration Tests, Doc Tests](https://microsoft.github.io/RustTraining/rust-patterns-book/ch14-testing-and-benchmarking-patterns.html#unit-tests-integration-tests-doc-tests): an overflow test that only passes under `cfg(debug_assertions)`
- [RustTraining type-driven-correctness-book § Case Study: IPMI FRU Data](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch07-validated-boundaries-parse-dont-validate.html#case-study-ipmi-fru-data): a modular checksum written with explicit `wrapping_add`

## DEF-4: Decode external input with checked slicing, never indexing

**Rule.** When parsing bytes from the network, disk or another process, read fixed-size prefixes
with `split_first_chunk::<N>()` and variable lengths with `split_at_checked` or `get(..)`, convert
lengths with `usize::try_from`, and turn every `None` into a decode error. Never index (`buf[i]`,
`&buf[a..b]`) with an offset derived from the input. Cap any preallocation sized by a declared count
to what the remaining bytes could actually hold. Look up indices taken from submitted or
deserialized structures with `.get(i).ok_or(..)` as well.

**Why.** A truncated or malicious message that hits an indexing panic crashes the service, a denial
of service in a single packet. A hand-written `pos + len > data.len()` check followed by indexing
can overflow, so the check passes and the slice panics anyway. A 4-byte header claiming 2^32 entries
allocates gigabytes before the first read fails. Spider's `wire.rs` contains both the good form
(`split_first_chunk`, bounded `with_capacity`) and the bad form (a manual `self.pos + field_len`
check, then a slice) in sibling parsers of the same format. `u32::from_le_bytes` needs a
`[u8; 4]`. A slice such as `&data[0..4]` is a `&[u8]`, so turning it into an array takes a
`try_into()` that can never fail but still returns a `Result`. That forces an `expect` or a made-up
error like `InvalidFormat("unreachable")`. `split_first_chunk::<4>()` returns the `&[u8; 4]`
directly, together with the length check, so the only error left (a buffer that's too short) is a
real one.

```rust,ignore
// Bad
let count_bytes: [u8; 4] = data[0..4]
    .try_into()
    .map_err(|_| WireError::InvalidFormat("unreachable"))?;
let count = u32::from_le_bytes(count_bytes);
let mut payloads = Vec::with_capacity(count as usize);
if self.pos + len > self.data.len() {
    return Err(WireError::InvalidFormat("truncated payload"));
}
let payload = &self.data[self.pos..self.pos + len];
```

```rust,ignore
// Good
const LEN_PREFIX_LEN: usize = 4;

let (count_bytes, mut remaining) = data
    .split_first_chunk::<LEN_PREFIX_LEN>()
    .ok_or(WireError::InvalidFormat("buffer too small for the count header"))?;
let count = usize::try_from(u32::from_le_bytes(*count_bytes))
    .map_err(|_| WireError::InvalidFormat("count exceeds the address space"))?;
let mut payloads = Vec::with_capacity(count.min(remaining.len() / LEN_PREFIX_LEN));
for _ in 0..count {
    let (len_bytes, rest) = remaining
        .split_first_chunk::<LEN_PREFIX_LEN>()
        .ok_or(WireError::InvalidFormat("truncated length prefix"))?;
    let len = usize::try_from(u32::from_le_bytes(*len_bytes))
        .map_err(|_| WireError::InvalidFormat("length exceeds the address space"))?;
    let (payload, rest) = rest
        .split_at_checked(len)
        .ok_or(WireError::InvalidFormat("truncated payload"))?;
    payloads.push(payload);
    remaining = rest;
}
```

**Review.**
- Flag `[]` indexing, range slicing, or `as usize` on any length, offset or index that came from
  input. Ask for the chunk or checked APIs, or a slice pattern (`let [a, b, c] = fields.as_slice()
  else { .. }`) when the record has a fixed shape.
- Flag `Vec::with_capacity(n)`, `reserve(n)` and `vec![_; n]` where `n` came from input.
- In streaming decoders, check that a declared length is compared against the protocol maximum
  before waiting for the payload (BND-7), that input is consumed only once a whole frame has
  decoded, and that "incomplete, wait for more" and "invalid, reject" are different errors.

**Exceptions.** Indexing a `[u8; N]` with constants after the conversion, and indices produced by
the same function from the same collection (`enumerate`, `position`).

See also: BND-7 (bounding byte streams from peers) and TEST-8 (feeding decoders byte by byte).

**Sources.**

- [spider `spider-utils/src/wire.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-utils/src/wire.rs#L311-L338): `WireFrameBuilder::unframe_payload_slices`: `split_first_chunk`, capped `with_capacity`
- [y-scope/spider#308](https://github.com/y-scope/spider/pull/308#discussion_r3088855874): rewritten with `first_chunk` to drop an unreachable `try_into` error
- [spider `spider-core/src/types/io/task_graph_input.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/types/io/task_graph_input.rs#L103-L125): `TaskGraphInputEntry::from_wire_payload`: `split_first` and a checked shared-input ID
- [y-scope/clp#2649](https://github.com/y-scope/clp/pull/2649#discussion_r4438333071): test that a result frame decodes only once it is complete
- [RustTraining rust-patterns-book § zerocopy and bytemuck — Safe Transmutation](https://microsoft.github.io/RustTraining/rust-patterns-book/ch11-serialization-zero-copy-and-binary-data.html#zerocopy-and-bytemuck--safe-transmutation): size-checked byte conversions that fail instead of panicking
- [RustTraining c-cpp-book § Avoiding unchecked indexing](https://microsoft.github.io/RustTraining/c-cpp-book/ch17-2-avoiding-unchecked-indexing.html#avoiding-unchecked-indexing): use `.get()` unless the index is provably valid

## DEF-5: Confine `unsafe` behind a safe API, and state its contract in the right place

**Rule.** Keep each `unsafe` block to the single operation that needs it, and put a `// SAFETY:`
comment on it naming the invariant and why it holds at this call site. A function whose soundness
depends on its caller is an `unsafe fn` with a `# Safety` section. A safe function must be sound for
every input that safe code can produce, so it establishes its own preconditions (bounds via
`checked_add`, null, alignment, initialized length). Every `extern "C"` function exported from Rust
wraps its body in `std::panic::catch_unwind`, and owned FFI buffers implement `Drop`.

**Why.** A safe signature promises that no misuse can cause undefined behaviour, and a doc comment
can't keep that promise. Spider's `CArray::as_slice` and `TaskExecutionResult::into_result` are safe
functions whose `# Safety` sections tell the caller to keep the pointer valid, so either the docs
are wrong or the API is unsound. `into_result` also wraps `self` in `ManuallyDrop` "to prevent the
destructor" of a type that has no `Drop`, so any result dropped without being converted leaks its
buffer. A panic that unwinds out of an `extern "C"` function aborts the process (Rust 1.81+).
`register_tdl_package!` exports `__spider_tdl_package_execute` without `catch_unwind`, so a
panicking user task aborts the task executor, and the execution manager sees a crash instead of the
task's error. The guarding check itself must be sound too: `offset + 4 > len` wraps for a huge
`offset` and passes.

```rust,ignore
// Bad
/// # Safety
///
/// The caller must guarantee `pointer` is valid for `length` elements.
pub fn as_slice(&self) -> &[u8] {
    unsafe { std::slice::from_raw_parts(self.pointer, self.length) }
}

#[unsafe(no_mangle)]
pub extern "C" fn lib_process(input: *const c_char) -> c_int {
    process(input).map_or(1, |()| 0)
}
```

```rust,ignore
// Good
pub fn as_slice(&self) -> &'borrow_lifetime [u8] {
    // SAFETY: the fields are private and only `from_slice` sets them, from a live
    // `&'borrow_lifetime [u8]`.
    unsafe { std::slice::from_raw_parts(self.pointer, self.length) }
}

#[unsafe(no_mangle)]
pub extern "C" fn lib_process(input: *const c_char) -> c_int {
    match std::panic::catch_unwind(|| process(input)) {
        Ok(Ok(())) => 0,
        Ok(Err(_)) => 1,
        Err(_) => 2,
    }
}
```

**Review.**
- Every `unsafe` block needs a `// SAFETY:` comment naming a concrete invariant (suggest enabling
  `clippy::undocumented_unsafe_blocks`). A `# Safety` section on a safe `fn` is a defect: either
  make the function `unsafe fn` or make it sound.
- Check the precondition checks in front of `unsafe` for overflow and alignment, every `extern "C"`
  export (including those a macro generates) for `catch_unwind`, and every owned FFI allocation for
  a `Drop` impl rather than `ManuallyDrop` or `mem::forget`.
- Ask for Miri (`cargo +nightly miri test`) on pure-Rust `unsafe` and for sanitizers on FFI. Prefer
  `from_le_bytes`, `zerocopy`/`bytemuck` or proven crates to `transmute` and hand-rolled lock-free
  code. Application logic should contain no `unsafe` at all.

See also: coding-style.md § Take ownership when the value mustn't be used afterwards (why
`ManuallyDrop` and `mem::forget` are not ways to skip `Drop`).

**Sources.**

- [spider `spider-tdl/src/ffi.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-tdl/src/ffi.rs#L68-L84): `CArray::as_slice`, a safe fn with a `# Safety` section
- [spider `spider-tdl/src/register.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-tdl/src/register.rs#L138-L175): the macro-generated `__spider_tdl_package_execute` has no `catch_unwind`
- [spider `spider-task-executor/src/manager.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-task-executor/src/manager.rs#L168-L190): `TdlPackage::execute_task`: a `// SAFETY:` comment on the FFI call
- [RustTraining rust-patterns-book § Writing Sound Abstractions](https://microsoft.github.io/RustTraining/rust-patterns-book/ch12-unsafe-rust-controlled-danger.html#writing-sound-abstractions): encapsulate `unsafe` so that every public method is safe
- [RustTraining rust-patterns-book § Lock-Free Patterns](https://microsoft.github.io/RustTraining/rust-patterns-book/ch06-concurrency-vs-parallelism-vs-threads.html#lock-free-patterns): prefer proven crates to hand-rolled lock-free code
- [RustTraining rust-patterns-book § Panics, catch_unwind, and When to Abort](https://microsoft.github.io/RustTraining/rust-patterns-book/ch10-error-handling-patterns.html#panics-catch_unwind-and-when-to-abort): `catch_unwind` belongs at FFI and thread-pool boundaries
- [RustTraining type-driven-correctness-book § Safe Wrappers Around `unsafe`](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch11-fourteen-tricks-from-the-trenches.html#trick-7--safe-wrappers-around-unsafe): wrap every `unsafe` block in a safe, auditable abstraction
- [RustTraining engineering-book § When to Use Which Tool](https://microsoft.github.io/RustTraining/engineering-book/ch05-miri-valgrind-and-sanitizers-verifying-u.html#when-to-use-which-tool): Miri for pure-Rust `unsafe`, sanitizers and Valgrind for FFI

# Server design

Most of our Rust runs as long-lived services, such as coordinators, schedulers and storage, that
talk to peers which retry, crash and restart. The rules here cover how such a service treats its
peers and its own failures: progress that must not be replayed, input it can't honour, resources an
outsider can size, failures it should survive versus ones that should stop it, and when to retry.

## SRV-1: Let progress state only move forward

**Rule.** Cursors, epochs and session IDs record how far something has gotten, so they only move
forward. Give them a `try_advance`, not a `set`, and don't overwrite one with the result of a fetch
that can come back empty. Check work stamped with an epoch against the current epoch at every point
where it is consumed, not only once.

**Why.** Progress state that moves backwards replays work already done. The S3 scanner overwrote its
`start_after` cursor with `None` after a scan that found nothing, so the next scan started over and
re-ingested the same object 286 times ([y-scope/clp#2333](https://github.com/y-scope/clp/pull/2333)).
A plain `set` on an epoch breaks the same way when writers race: a late writer stores an older value
over a newer one, and work from the superseded session looks current again. Spider stamps every
assignment with a session ID that only advances, and drops stale assignments at dequeue, hint
redemption, reschedule drain and completion.

```rust,ignore
// Bad
impl SessionTracker {
    pub fn set(&self, session_id: SessionId) {
        self.inner.store(session_id, Ordering::Release);
    }
}
```

```rust,ignore
// Good
impl SessionTracker {
    pub fn try_advance(&self, session_id: SessionId) -> bool {
        self.inner.fetch_max(session_id, Ordering::AcqRel) < session_id
    }
}
```

**Review.**
- Flag a raw `set` or `store` on an epoch, session ID or cursor, and `self.cursor = <fetch that
  returns an Option>`. Ask for `try_advance` (`fetch_max`, or a CAS loop) and for keeping the old
  value when the fetch returns nothing.
- Flag work that can outlive a reset but carries no epoch, or whose epoch is checked only when the
  work is created.

**Sources.**

- [y-scope/clp#2333](https://github.com/y-scope/clp/pull/2333): stops overwriting the `start_after` cursor after an empty scan
- [clp `log-ingestor/src/ingestion_job/s3_scanner.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/log-ingestor/src/ingestion_job/s3_scanner.rs#L107-L111): `start_after` is updated only when the scan ingested new objects
- [y-scope/spider#328](https://github.com/y-scope/spider/pull/328): `SessionTracker` only moves the session ID forward, via a CAS loop
- [spider `spider-core/src/session.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/session.rs#L51-L67): `SessionTracker::try_advance`, a forward-only CAS loop
- [spider `spider-scheduler/src/service.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/service.rs#L176-L206): `SchedulerServiceState::complete_task_assignment` drops completions from a stale scheduler

## SRV-2: Turn unknown, missing or unsupported input into an error, never a plausible value

**Rule.** When an external discriminant is not one you recognise, when a required field is absent,
or when a request asks for something the component can't honour, return an error variant carrying
the offending value (`UnknownStatus(u8)`, `UnsupportedJobConfig(..)`). Don't fall back to a
valid-looking variant, invent a default while parsing, quietly run a degraded version of the
request, or rewrite malformed input until it passes. Data that may legitimately be absent stays
`Option<T>` (TYPE-4), and the default for it is chosen by the caller that knows the context, in one
named place.

**Why.** An invented value is worse than a crash, because it flows downstream as if it were real. A
corrupted status byte decoded as `Pending` makes a broken row look like a fresh job. In clp,
aggregation jobs were left `PENDING` for a scheduler that no longer existed, so callers polled
forever, and `write_to_file` jobs ran but wrote their results where no caller looked. Both now fail
with `UnsupportedJobConfig` ([y-scope/clp#2565](https://github.com/y-scope/clp/pull/2565)). Wrapping
a KQL query in parentheses to avoid one failure would have turned the syntax error `a) AND (b` into
the valid `(a) AND (b)`. Defaulting the AWS region inside a shared helper sent AWS users to the
wrong region. Now the caller, which knows the context, validates the input and picks the default.

```rust,ignore
// Bad
let status = match code {
    0 => Status::Pending,
    1 => Status::Running,
    _ => Status::Pending,
};
let region = region.map_or("us-east-1", NonEmptyString::as_str);
args.push(OsString::from(format!("({})", query.as_str())));
```

```rust,ignore
// Good
let status = match code {
    0 => Status::Pending,
    1 => Status::Running,
    other => return Err(DecodeError::UnknownStatus(other)),
};
if config.endpoint.is_none() && config.region.is_none() {
    return Err(JobManagerError::MissingRegionCode);
}
args.push(OsString::from(query.as_str()));
```

**Review.**
- In parsing and conversion code for external data, flag `unwrap_or(<literal>)`,
  `unwrap_or_default()` and `_ => <valid variant>`. Ask whether absence is an error or should stay
  an `Option` for the consumer to handle.
- Flag request options that are accepted but then ignored or downgraded, and code that quotes, wraps
  or trims a user payload so that it parses. Ask for an explicit `Unsupported*` or invalid-input
  error and a recorded terminal status. Once a case is rejected upstream, later stages may mark it
  `unreachable!("<why>")`.
- A string from a request or config that becomes a filesystem path component must be checked to be
  exactly one `Component::Normal`. Paths under a mount point need a lexically validated newtype
  (absolute, no `..`) and a canonicalized containment check, because `Path::join` with an absolute
  path replaces the base and `..` escapes it.

**Exceptions.** Dropping unknown input as a deliberate forward-compatibility policy, provided it is
an explicit, logged branch rather than a silent default.

See also: TYPE-6 (closed sets as enums) and ERR-2 (recover only from the expected variant).

**Sources.**

- [y-scope/clp#2565](https://github.com/y-scope/clp/pull/2565): aggregation and write-to-file jobs now fail as `UnsupportedJobConfig`
- [y-scope/clp#2578](https://github.com/y-scope/clp/pull/2578#discussion_r4500099642): reviewer asks to mark the upstream-rejected file output `unreachable`
- [y-scope/clp#2512](https://github.com/y-scope/clp/pull/2512#discussion_r3985243866): wrapping the query in parentheses would make `a) AND (b` valid
- [y-scope/clp#1776](https://github.com/y-scope/clp/pull/1776#pullrequestreview-3600460172): the caller validates endpoint and region and picks the default region
- [y-scope/clp#2623](https://github.com/y-scope/clp/pull/2623): validates logs-input paths before resolving them under the mount point
- [spider `spider-task-executor/src/bin/spider_task_executor.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-task-executor/src/bin/spider_task_executor.rs#L69-L84): `run_task` joins a request's package name into a filesystem path
- [RustTraining type-driven-correctness-book § Parse, Don't Validate](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch07-validated-boundaries-parse-dont-validate.html#parse-dont-validate): parse once into a type that can't hold invalid data
- [RustTraining type-driven-correctness-book § Typed Telemetry Reads](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch17-redfish-applied-walkthrough.html#section-4--typed-telemetry-reads-typed-commands--dimensional-analysis-ch02--ch06): a missing required field is a parse error, not a default

## SRV-3: Cap every resource that a peer or a config value can size

**Rule.** Every duration, count, size or rate that a request or a config controls, and that turns
into server memory, time or lock hold time, gets an explicit server-side cap at the boundary: the
unpack, `TryFrom` or `validate` layer. Name the bounds as `MIN_`/`MAX_` constants, check relations
between fields (`hard_timeout > soft_timeout`), keep the limits in one module, and state the
relations between limits with `const _: () = assert!(..)`. Enforce each limit on every path that
produces or consumes the value.

**Why.** Type checking can't stop a denial of service. Spider's dispatch queue holds a session
`RwLock` read guard for the whole client-chosen `wait_time`, and the scheduler core needs the write
side to bump the session, so one execution manager sending a huge `wait_time_ms` can stall the core.
A zstd payload of a few KB decompressed with no output limit can expand to gigabytes. tonic's
default 4 MiB decode limit rejected large success reports, which the execution manager then dropped,
until the limits were made explicit and checked against each other
([y-scope/spider#560](https://github.com/y-scope/spider/pull/560)). In clp, a max-results limit
applied only to the Mongo path left file-backed results unbounded
([y-scope/clp#2180](https://github.com/y-scope/clp/pull/2180#discussion_r3059505785)), and a
per-file timeout formula pushed tasks of more than 288 files past Spider's 24 h maximum, so job
submission failed ([y-scope/clp#2668](https://github.com/y-scope/clp/pull/2668)).

```rust,ignore
// Bad
let wait_time = Duration::from_millis(request.wait_time_ms);
let json = zstd::stream::decode_all(request.payload.as_slice())?;
let hard_timeout_ms = num_files * 5 * 60 * 1000;
```

```rust,ignore
// Good
pub const MAX_WAIT_TIME: Duration = Duration::from_secs(30);
pub const MAX_DECOMPRESSED_SIZE: usize = 64 * 1024 * 1024;
pub const MAX_REPORT_OUTPUTS_SIZE: u64 = 4 * 1024 * 1024;
pub const MAX_TASK_INSTANCE_MESSAGE_SIZE: usize = 32 * 1024 * 1024;
const _: () = assert!(2 * MAX_REPORT_OUTPUTS_SIZE <= MAX_TASK_INSTANCE_MESSAGE_SIZE as u64);

let wait_time = Duration::from_millis(request.wait_time_ms).min(MAX_WAIT_TIME);
let json = zstd::bulk::decompress(&request.payload, MAX_DECOMPRESSED_SIZE)
    .map_err(Error::ZstdDecompression)?;
let estimate_ms = |throughput: NonZeroU64| {
    estimated_uncompressed_size.saturating_mul(1000).div_ceil(throughput.get())
};
let soft_timeout_ms = estimate_ms(soft_throughput).clamp(MIN_SOFT_TIMEOUT_MS, MAX_TIMEOUT_MS - 1);
let hard_timeout_ms = estimate_ms(hard_throughput)
    .clamp(MIN_HARD_TIMEOUT_MS.max(soft_timeout_ms + 1), MAX_TIMEOUT_MS);
```

**Review.**
- On inbound paths, grep for `Duration::from_*(request.`, `with_capacity(request.`, `decode_all`,
  unbounded channels, and `while let Ok(_) = rx.try_recv()` on a queue that other tasks keep
  filling. Each one needs a cap. For a drain, take a snapshot of `len()` and receive at most that
  many items per tick.
- When a PR adds a limit, check that every backend or output path enforces it, or that they all pass
  through one choke point that does (preferably a combinator such as `StreamExt::take`). When a PR
  raises a limit, check the limits that depend on it, such as an inner payload against the transport
  decode limit, and pin the relation with a const assert.
- Derived budgets such as timeouts should scale with what actually drives the cost (bytes, not
  files), use saturating arithmetic, and be clamped into the downstream's accepted range. `clamp`
  panics when its lower bound exceeds its upper bound, so a lower bound computed from another value
  (here `soft_timeout_ms + 1`) must itself be clamped first. Ask for a test showing that the largest
  input you can produce still fits.

**Exceptions.** A limit may be deferred on purpose if the PR or the code says so and names the bound
that holds in practice. For example, connections per session are bounded by the number of Spider
workers.

See also: TYPE-7 (the lower bound: `NonZero*`), DEF-4 and BND-7 (lengths read from bytes), ASYNC-6
(bounded queues).

**Sources.**

- [spider `spider-scheduler/src/dispatch_queue.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/dispatch_queue.rs#L118-L148): `DispatchQueueReader::dequeue` holds the session read guard for the whole `wait_time`
- [spider `spider-proto-rust/src/unpack/scheduler.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-proto-rust/src/unpack/scheduler.rs#L33-L44): `NextTaskRequest::unpack` converts `wait_time_ms` without a cap
- [spider `spider-core/src/compression.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/compression.rs#L29-L31): `decode_zstd_bytes` calls `decode_all` with no output limit
- [spider `spider-storage/src/limits.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/limits.rs#L27-L40): the limits module; report and message sizes pinned by a const assert
- [y-scope/spider#560](https://github.com/y-scope/spider/pull/560#discussion_r4507591661): assert that the message limit leaves a margin over the outputs limit
- [y-scope/spider#472](https://github.com/y-scope/spider/pull/472#discussion_r3980589460): cap the wait time at the service level and detect overflow with `checked_add`
- [y-scope/spider#395](https://github.com/y-scope/spider/pull/395): the reschedule step drains a bounded snapshot of the queue per tick
- [y-scope/spider#288](https://github.com/y-scope/spider/pull/288#discussion_r2968571739): reviewer asks for a 24-hour maximum timeout
- [y-scope/clp#2180](https://github.com/y-scope/clp/pull/2180#discussion_r3059505785): the results limit also has to be applied to `fetch_results_from_file`
- [y-scope/clp#2180](https://github.com/y-scope/clp/pull/2180#discussion_r3059574303): enforce the limit with `StreamExt::take` instead of counting by hand
- [y-scope/clp#2661](https://github.com/y-scope/clp/pull/2661#issuecomment-6619241828): the per-file timeout puts tasks of over 288 files past 24 h
- [y-scope/clp#2668](https://github.com/y-scope/clp/pull/2668#discussion_r4486559669): reviewer sets minimum soft and hard timeouts for the derived budget
- [y-scope/clp#2689](https://github.com/y-scope/clp/pull/2689#discussion_r4507624749): the connection limit is deferred: Spider's worker count bounds it

## SRV-4: Return errors for what the environment can cause, and fail the whole service for broken invariants

**Rule.** Decide between `Result` and a panic by asking who can break the condition. If input, I/O,
a peer, randomness or concurrency can break it, return a typed error, however rare it is. If code
you own proves it, use `expect` or `unreachable!` with the invariant as the message. Inside a
spawned, long-running task, report a detected corruption of shared state or a protocol-impossible
response by returning an `Internal`-style error or cancelling the root `CancellationToken`, so the
whole service stops together. Don't panic the task, and don't log and carry on. Pin assumptions
about constants with `const _: () = assert!(..)`.

**Why.** A panic in a tokio task ends only that task. The `JoinHandle` captures it, and the rest of
the service keeps serving on inconsistent shared state, without cleanup or final logs. Spider ties
every detected corruption (a missing registry entry, a corrupted round-robin cursor, a cache/DB
divergence) to the root token, so the gRPC server, the core and the trackers shut down together and
visibly. The opposite mistakes are just as real. An `assert!` against a freshly generated random
token colliding would crash production on a legitimate event. Retrying an auth error on a heartbeat
that sends no credentials hides a protocol mismatch. A comment saying "this loop terminates only
because `DOWNGRADE_LIVES == 1`" goes stale without anyone noticing, whereas a const assert fails the
build.

```rust,ignore
// Bad
tokio::spawn(async move {
    loop {
        let entry = table.get(&id).expect("registered execution managers should be tracked");
        // ...
    }
});

Err(LivenessResponseError::ResourceGroupAuth) => {
    tracing::warn!("Heartbeat authentication failed. Retrying next tick.");
}
```

```rust,ignore
// Good
let Some(entry) = table.get(&id) else {
    tracing::error!(id = % id, "Execution manager no longer exists. The liveness tracker is corrupted.");
    root_token.cancel();
    return;
};

Err(LivenessResponseError::ResourceGroupAuth) => {
    tracing::error!(
        "Storage returned an unexpected resource group authentication error for a heartbeat. \
         Cancelling the runtime."
    );
    self.cancellation_token.cancel();
}

const _: () = assert!(DOWNGRADE_LIVES == 1, "a larger downgrade budget needs a per-tick visited set");
```

**Review.**
- For each new `expect`, `assert!` or `unreachable!`, ask whether anything outside the code (input,
  a peer, the clock, randomness, a race) can trigger it. If so, it must be an error variant. If not,
  the message should state the invariant ("`split_into_batches` never yields an empty batch") rather
  than restate the failure, and a case that is proven impossible should not also keep a dead error
  variant.
- In spawned service loops, flag `expect` and `panic!` on facts that depend on shared state another
  component maintains (a registry entry, a cursor, the cache matching the DB). Either report through
  the root token or an `Internal` error, or remove the fallible step altogether by storing the value
  in the form the loop consumes, for example a `u64` milliseconds field passed straight to the RPC.
  An `expect` on a fact proven earlier in the same function, such as DEF-1's validated index, stays.
- Flag comments that state an assumption about a constant or a limit relation, and ask for a const
  assert inside the function that relies on it. Also flag checks that only accept the current
  backend's behaviour (session ID 0 "never" coming from MariaDB) when the documented contract allows
  it.

**Exceptions.** Synchronous startup and CLI code, where unwinding already takes the process down,
and test helpers (coding-style.md § Panic in test helpers when the failure means the test is wrong).

See also: pr-review.md § Panic vs error returns; coding-style.md § Assert preconditions instead of
tolerating them and § Using `unwrap`; ERR-1 (the fatal error tier) and ASYNC-4 (routing fatal errors
to the shutdown handle).

**Sources.**

- [spider `spider-scheduler/src/execution_manager_registry.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/execution_manager_registry.rs#L223-L281): `ExecutionManagerRegistry::track_liveness` cancels the root token on a missing entry
- [spider `spider-scheduler/src/runtime.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/runtime.rs#L109-L164): `create_runtime` shares one token; a core error cancels it
- [spider `spider-scheduler/src/grpc.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/grpc.rs#L56-L111): `GrpcSchedulerService::service_error_handler` cancels the service on `Internal`
- [spider `spider-execution-manager/src/liveness.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/liveness.rs#L130-L178): `LivenessActor::send_heartbeat` cancels the runtime on protocol-impossible replies
- [spider `spider-scheduler/src/core_impl/resource_group_round_robin/scheduling_state.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/core_impl/resource_group_round_robin/scheduling_state.rs#L243-L284): `RgSchedulingState::pop_regular_task` pins `DOWNGRADE_LIVES == 1` with a const assert
- [y-scope/spider#464](https://github.com/y-scope/spider/pull/464#discussion_r3905764333): an auth error is unreachable from a heartbeat: log it and shut down
- [y-scope/spider#462](https://github.com/y-scope/spider/pull/462): adds the scheduling state and its `DOWNGRADE_LIVES` const assert
- [y-scope/spider#342](https://github.com/y-scope/spider/pull/342#discussion_r3482613668): a fatal error there skips `main_loop`'s cleanup and logging
- [y-scope/spider#342](https://github.com/y-scope/spider/pull/342#discussion_r3482671121): keep the poll timeout a `u64` passed straight to the RPC
- [y-scope/spider#359](https://github.com/y-scope/spider/pull/359#discussion_r3488421185): session ID 0 is valid by policy, merely impossible with MariaDB
- [y-scope/spider#549](https://github.com/y-scope/spider/pull/549): a cache/DB divergence or a committer error shuts the service down
- [y-scope/spider#557](https://github.com/y-scope/spider/pull/557): a job changed twice in one round is a fatal internal error
- [y-scope/clp#2689](https://github.com/y-scope/clp/pull/2689#discussion_r4507699895): reviewer asks for an error instead of an assertion
- [y-scope/clp#2661](https://github.com/y-scope/clp/pull/2661#discussion_r4471968351): this can't happen after `canonicalize`, so use `expect`
- [y-scope/clp#2420](https://github.com/y-scope/clp/pull/2420#discussion_r3654284372): use `unreachable` since the factory already checked this
- [y-scope/clp#2513](https://github.com/y-scope/clp/pull/2513#discussion_r4057713082): a changed or missing job row is a `QueryJobMetadataCorrupted` error
- [RustTraining type-driven-correctness-book § Protocol Frame Layouts](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch15-const-fn-compile-time-correctness-proofs.html#protocol-frame-layouts): `const _: () = assert!(..)` pins a relation between constants

## SRV-5: Retry only transient failures, with backoff, and only idempotent operations

**Rule.** Retry through one helper that takes an `is_retriable` classifier, a finite attempt budget,
and capped exponential backoff with jitter computed without overflow (see DEF-3). Retry only
idempotent operations: reads, or writes keyed by a deterministic ID or an idempotency key. Let
permanent errors bring the item to a terminal state. On the server side, an operation that may be
replayed (start, cancel, terminate, fail) treats "already in the requested state, or past it" as
success, recognised by a typed variant rather than by matching message text. Every loop that retries
on error sleeps, including an ad-hoc `continue`.

**Why.** Retrying every error turns permanent failures into hangs. clp's cancellation monitor
retried a cancel that kept returning `JobNotFound`, so it got stuck on that job and blocked every
later cancellation. Retrying a non-idempotent call after a lost response duplicates the work:
Spider's `register_job` runs under `call_with_retry`, which also retries `Code::Unknown` transport
failures that can happen after the server has committed. The classifier has to inspect the source
chain, because tonic reports a dropped connection as `Code::Unknown` with a `transport::Error`
source. The server side has to cooperate too. If a repeated `start_job` or cancel fails because the
job already started or was already cancelled, a crash-recovery path turns into a permanent failure.
Tasks that the scheduler may retry need deterministic output names (`{job_id}-{task_index}-{n}`), so
that a retry overwrites its own output instead of leaving orphans.

```rust,ignore
// Bad
loop {
    match scheduler.next_task().await {
        Ok(task) => run(task).await,
        Err(_) => continue,
    }
}

let archive_id = Uuid::new_v4();
```

```rust,ignore
// Good
let mut retry: u32 = 0;
loop {
    match scheduler.next_task().await {
        Ok(task) => {
            retry = 0;
            run(task).await;
        }
        Err(e) if e.is_transient() => {
            tracing::warn!(error = % e, "Scheduler returned a transient error. Retrying.");
            tokio::time::sleep(backoff(retry, MAX_BACKOFF)).await;
            retry = retry.saturating_add(1);
        }
        Err(e) => return Err(e.into()),
    }
}

match self.start_job(job_id).await {
    Ok(_) | Err(ClientError::InvalidJobState(_)) => {}
    Err(e) => return Err(e.into()),
}

let archive_id = format!("{job_id}-{task_index}-{archive_index}");
```

**Review.**
- For each retry loop or `call_with_retry`, check for a classifier (itself an exhaustive match), a
  budget, a cap and jitter, and check that only the network round-trip sits inside the
  retried closure, with serialization and decoding outside it.
- Check that the retried operation is idempotent. Create, register or enqueue calls under retry need
  an idempotency key or a deterministic ID. Otherwise make a single attempt.
- In poll and recovery loops, a permanent error (`NotFound`, invalid state, corrupted metadata) must
  finish the item instead of being retried on the next tick. Flag `let _ = op().await` used to make
  a replay "idempotent". Match the one "already done" variant instead, and check that the variant
  can only mean "already done or past it" (`InvalidJobState` from `start_job` qualifies only because
  a job leaves `Ready` by being started or cancelled, and the next poll observes which).

**Exceptions.** A long-running service loop, such as an execution manager polling its scheduler, may
retry indefinitely, as long as it backs off and logs each failure.

See also: pr-review.md § Don't silently swallow errors; OWN-4 (how the retried closure builds its
future).

**Sources.**

- [y-scope/clp#2573](https://github.com/y-scope/clp/pull/2573#discussion_r4295898265): a non-transient "job not found" would stall the cancellation monitor forever
- [y-scope/clp#2402](https://github.com/y-scope/clp/pull/2402#discussion_r3625635109): cap the initial poll backoff at the maximum backoff
- [y-scope/clp#2589](https://github.com/y-scope/clp/pull/2589#discussion_r4350585449): cancelling an already cancelled job should return `Ok`
- [y-scope/clp#2646](https://github.com/y-scope/clp/pull/2646#discussion_r4447938462): name archives `{compression-job-id}-{compression-task-index}-{archive-index-in-the-task}` instead of UUIDs
- [y-scope/clp#2035](https://github.com/y-scope/clp/pull/2035): makes ingestion job termination idempotent
- [y-scope/spider#396](https://github.com/y-scope/spider/pull/396#issuecomment-4974454267): tonic reports transport failures as `Unknown`, so those must retry too
- [y-scope/spider#319](https://github.com/y-scope/spider/pull/319#discussion_r3222266574): make cancellation idempotent; check the DB before reporting job-not-found
- [spider `spider-utils/src/grpc/retry.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-utils/src/grpc/retry.rs#L62-L86): `execute_with_retry`: classifier, retry budget, capped backoff
- [spider `spider-client/src/grpc/job.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-client/src/grpc/job.rs#L78-L106): `JobOrchestrationClient::submit_job` runs `register_job` under `call_with_retry`
- [spider `spider-execution-manager/src/runtime.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/runtime.rs#L335-L435): `Runtime::main_loop` `continue`s on a scheduler error without sleeping
- [RustTraining async-book § Timeouts and Retries](https://microsoft.github.io/RustTraining/async-book/ch13-production-patterns.html#timeouts-and-retries): exponential backoff, plus jitter, for retried operations
- [RustTraining rust-patterns-book § Implementing Your Own Higher-Order APIs](https://microsoft.github.io/RustTraining/rust-patterns-book/ch07-closures-and-higher-order-functions.html#implementing-your-own-higher-order-apis): a retry helper taking an `FnMut` and a `should_retry` classifier

# Error handling

An error is a message to whoever has to react to it. That may be the caller who retries or rejects
the request, the supervisor who restarts the service, or the operator reading the log. Design each
error type around that reaction, keep the cause attached as the error moves up the stack, and handle
each error exactly once. Library code returns typed `thiserror` enums, and `anyhow` stays in
binaries and tests (see pr-review.md § `anyhow` vs custom errors).

## ERR-1: Group error variants by the recovery action they need

**Rule.** Split a component's errors into category enums by what the handler must do, then combine
them in one outer enum. The categories are: internal invariant violation (unsafe to continue,
restart), expected stale-state or precondition rejection (return to the caller), and shutting down
(retryable, never fatal). Document each category's recovery contract on the enum and decide fatality
in one method (`is_fatal()`). Never put a condition that a client request can trigger in the
internal or fatal category.

**Why.** In tokio a panic kills only the current task. The service keeps running on shared state
that can no longer be trusted, so "this must take the service down" has to be a typed error that the
top-level handler recognises. With a flat enum, every handler decides variant by variant, and they
disagree. In Spider, asking for the outputs of a job that hadn't succeeded returned
`InternalError::UnexpectedJobState`, so a single early client request shut storage down. Cancelling
a `CommitReady` job did the same. Before `Stopping` existed, requests cut short by shutdown came
back as fatal `INTERNAL`. In all three cases the error's category decided between a client reply and
an outage.

```rust,ignore
// Bad
#[derive(Debug, thiserror::Error)]
pub enum CacheError {
    #[error("job not found: {0:?}")]
    JobNotFound(JobId),

    #[error("job not succeeded: in state {0:?}")]
    JobNotSucceeded(JobState),

    #[error("task graph corrupted: {0}")]
    TaskGraphCorrupted(String),
}
```

```rust,ignore
// Good
#[derive(Debug, thiserror::Error)]
pub enum CacheError {
    /// Invariant violated; the service must restart and rebuild the cache.
    #[error(transparent)]
    Internal(#[from] InternalError),

    /// Expected race or unmet precondition; reported back to the caller.
    #[error(transparent)]
    StaleState(#[from] StaleStateError),

    #[error("storage service is shutting down")]
    ServiceStopping,
}

impl StorageServerError {
    pub const fn is_fatal(&self) -> bool {
        matches!(
            self,
            Self::Cache(CacheError::Internal(_))
                | Self::Db(DbError::CorruptedDbState(_) | DbError::Fenced { .. })
        )
    }
}
```

Spider writes `is_fatal()` with `matches!`, as above. For a new classifier, prefer an exhaustive
`match` that lists every variant, so that adding a variant forces a decision about its fatality.

**Review.**
- For every new variant, ask which category it belongs to and whether a client can reach it. If a
  client can reach an `Internal` variant, move it to the stale-state or bad-request category.
- If handlers decide fatality themselves (for example, `cancel()` arms copied into several
  handlers), route them through `is_fatal()` or the default handler (ERR-6).
- Moving a variant to another category, or changing the status code it maps to, changes runtime
  behaviour (restart vs reply). Ask for the change to be called out in the PR description.

**Exceptions.** `expect` and `panic!` still apply to a bug confined to the local code, such as an
index the function has just bounds-checked (pr-review.md § Panic vs error returns). Use the fatal
error tier when the broken invariant lives in state that outlives the task: the cache, the DB, or a
shared tree.

See also: pr-review.md § Panic vs error returns (this rule adds a third tier: a returned error that
is fatal to the service), and SRV-4 (when to return an error and when to panic).

**Sources.**

- [spider `spider-storage/src/cache/error.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/cache/error.rs#L9-L175): `CacheError` combines `InternalError` and `StaleStateError`, each documenting its recovery contract
- [spider `spider-storage/src/state/error.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/state/error.rs#L9-L53): `StorageServerError::is_fatal` decides fatality in one method
- [y-scope/spider#290](https://github.com/y-scope/spider/pull/290): introduces the `CacheError` / `InternalError` / `StaleStateError` taxonomy
- [y-scope/spider#293](https://github.com/y-scope/spider/pull/293#issuecomment-4173497229): internal errors act like panics and restart storage; stale-state errors are expected
- [y-scope/spider#354](https://github.com/y-scope/spider/pull/354): a DB error inside a cache operation becomes a fatal `CacheError::Internal`
- [y-scope/spider#524](https://github.com/y-scope/spider/pull/524): cancelling a `CommitReady` job no longer shuts storage down
- [y-scope/spider#525](https://github.com/y-scope/spider/pull/525): outputs of an unsucceeded job become a stale-state error, not a shutdown
- [y-scope/spider#539](https://github.com/y-scope/spider/pull/539): `Stopping` answers `UNAVAILABLE` before any fatal check

## ERR-2: Recover only from the variant you expect; propagate everything else

**Rule.** A fallback matches the exact variant or kind it can handle
(`Err(DbError::JobNotFound(_))`, `Err(e) if e.kind() == io::ErrorKind::NotFound`) and propagates
everything else. Don't map a catch-all `_` or `Err(_)` arm to a domain error. Don't use `.ok()`,
`unwrap_or_default()` or `filter_map(|r| r.ok())` on data the program needs.

**Why.** Mapping to the wrong error is worse than swallowing it. `_ => Err(JobNotFound(job_id))` on
a DB lookup gives the client a confident wrong answer during a DB outage, and fatal classifiers such
as `DbError::Fenced` never fire. `unwrap_or_default()` on a config parse runs production on the
default config. A blanket fallback treats "file missing" the same as "permission denied". Iterator
adapters are the hidden form of the same mistake: `filter_map(.. .ok())` turns corrupt input into a
shorter list that looks valid, and there is no `match` arm to catch the eye in review.
String-matching driver errors breaks with server versions and locales.

```rust,ignore
// Bad
let state = match db.get_state(job_id).await {
    Ok(state) => state,
    _ => return Err(StorageServerError::JobNotFound(job_id)),
};

let ids: Vec<u64> = raw_ids.iter().filter_map(|s| s.parse().ok()).collect();
```

```rust,ignore
// Good
let state = match db.get_state(job_id).await {
    Ok(state) => state,
    Err(DbError::JobNotFound(_)) => return Err(StorageServerError::JobNotFound(job_id)),
    Err(e) => return Err(e.into()),
};

let ids = raw_ids
    .iter()
    .map(|s| s.parse::<u64>().map_err(|source| Error::InvalidId { raw: s.clone(), source }))
    .collect::<Result<Vec<_>, _>>()?;
```

**Review.**
- A `_ =>` or `Err(_) =>` arm that returns a specific domain error → name the expected variant and
  propagate the rest. `e.to_string().contains("Duplicate entry")` → downcast to `MySqlDatabaseError`
  and compare against a named `MYSQL_ER_*` constant.
- `.ok()`, `.ok()?`, `unwrap_or_default()`, `unwrap_or_else(|_| ..)`, `.flatten()` over `Result`s,
  or `filter_map(.. .ok())` on input → collect into `Result<Vec<_>, _>`, or match the recoverable
  kind.
- A miss in a cache that holds only a subset (for example, live jobs) reported as `NotFound` → check
  the source of truth before choosing between not-found and wrong-state
  ([spider#535](https://github.com/y-scope/spider/pull/535)).

**Exceptions.** In a best-effort loop (ERR-9), skipping bad items can be the documented policy. Log
each skipped item with its ID and its error. `.ok()` is fine when "absent" and "invalid" really mean
the same thing; say why in a comment.

See also: pr-review.md § Don't silently swallow errors (this rule adds the wrong-mapping case and
the iterator form), coding-style.md § `map_err` for error translation (the downcast pattern), TYPE-4
and SRV-2 (absence and unknown input).

**Sources.**

- [spider `spider-storage/src/state/service/state.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/state/service/state.rs#L288-L366): `start_job` propagates DB errors; `cancel_job` still has the catch-all `_` arm
- [spider `spider-storage/src/db/mariadb/mysql_error.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/db/mariadb/mysql_error.rs#L1-L92): named `MYSQL_ER_*` constants checked through a `MySqlDatabaseError` downcast
- [y-scope/spider#535](https://github.com/y-scope/spider/pull/535): on a cache miss, check the DB and propagate other DB errors
- [RustTraining type-driven-correctness-book § Parse, Don't Validate](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch07-validated-boundaries-parse-dont-validate.html#parse-dont-validate): parse into a typed result once instead of checking and discarding
- [RustTraining c-cpp-book § Rust error handling](https://microsoft.github.io/RustTraining/c-cpp-book/ch09-error-handling.html#rust-error-handling-3): shows `map_err(|_| ())` and `unwrap_or_default`, the forms this rule rejects
- [RustTraining csharp-book § Error Recovery Patterns](https://microsoft.github.io/RustTraining/csharp-book/ch09-1-crate-level-error-types-and-result-alias.html#error-recovery-patterns): recover from `ErrorKind::NotFound` only, propagate everything else

## ERR-3: Add a variant only when a caller reacts differently, and give it typed fields

**Rule.** Each variant names one condition that some caller handles differently from the other
variants. It carries the facts the caller can't reconstruct (the ID, `{ from, to }`,
`{ expected, actual }`) as named, typed fields. Library code must not use `Result<T, String>`,
`type Error = String`, catch-all `Other(String)` variants, or fields that repeat what the caller
passed in.

**Why.** Callers can't recover from errors they can't tell apart. In
[y-scope/clp#2513](https://github.com/y-scope/clp/pull/2513#pullrequestreview-5286744460), a
finaliser had to tell "lost a race to a terminal state" from "the row is gone", but
`SqlxNoRowsAffected` hid three different situations, so callers swallowed real problems. String
payloads force callers and tests to match on message text, which
[spider#281](https://github.com/y-scope/spider/pull/281#discussion_r2734129660) called "a code
smell". Too many variants is also a failure: variants that no caller tells apart only add match arms
and tests ([spider#449](https://github.com/y-scope/spider/pull/449)). A variant named after a
guessed cause, such as `IllegalResourceGroupId` for what may be a wrong password, sends operators
down the wrong path
([spider#464](https://github.com/y-scope/spider/pull/464#discussion_r3905746575)). Write the message
for the condition the variant represents, not for the first call site, so it stays true when the
variant is reused
([spider#342](https://github.com/y-scope/spider/pull/342#pullrequestreview-4582419883)).

```rust,ignore
// Bad
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("no rows affected: {0}")]
    SqlxNoRowsAffected(String),

    #[error("queue {queue:?} closed")]
    QueueClosed { queue: QueueType },

    #[error("input size mismatch: expected {0}, got {1}")]
    InputSizeMismatch(usize, usize),
}
```

```rust,ignore
// Good
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("invalid query job status transition from {from:?} to {to:?}")]
    InvalidQueryJobStatusTransition { from: QueryJobStatus, to: QueryJobStatus },

    #[error("metadata corrupted for query job {0}: its row no longer exists")]
    QueryJobMetadataCorrupted(QueryJobId),

    #[error("queue closed")]
    QueueClosed,

    #[error("input size mismatch: expected {expected}, got {actual}")]
    InputSizeMismatch { expected: usize, actual: usize },
}
```

**Review.**
- A `String` payload for a condition the code detected itself → typed fields. If there is an
  underlying error, see ERR-4.
- A test that asserts `err.to_string().contains(..)` → either a variant is missing or the
  distinction doesn't matter (TEST-1).
- Two variants that every caller handles the same way → merge them. A field that holds an argument
  the caller already has → drop it. A tuple variant with several payloads of the same type → named
  fields.

**Exceptions.** One variant with a detailed message is enough when no caller can act on the finer
cause, for example "the task graph failed to deserialize"
([spider#281](https://github.com/y-scope/spider/pull/281#discussion_r2734247034)). Errors that cross
a process or FFI boundary, such as Spider's serializable `ExecutorError`, may be string-based. A
custom `Deserialize` impl reports through `serde::de::Error::custom`, which carries only a message.

See also: pr-review.md § `anyhow` vs custom errors, coding-style.md § API design (named fields over
positional tuples).

**Sources.**

- [y-scope/clp#2513](https://github.com/y-scope/clp/pull/2513#pullrequestreview-5286744460): `rows_affected == 0` hid "already terminated", "invalid transition" and "row is gone"
- [y-scope/spider#281](https://github.com/y-scope/spider/pull/281#discussion_r2734129660): reviewer calls matching on error messages "a code smell"
- [y-scope/spider#281](https://github.com/y-scope/spider/pull/281#discussion_r2734247034): one deserialization variant is enough when no caller acts on the cause
- [y-scope/spider#283](https://github.com/y-scope/spider/pull/283#discussion_r2928368454): reviewer proposes typed `{ from, to }` and `{ current, expected }` fields
- [y-scope/spider#309](https://github.com/y-scope/spider/pull/309#discussion_r3131743631): drop `QueueType` from the error, since the caller knows the lane
- [y-scope/spider#342](https://github.com/y-scope/spider/pull/342#pullrequestreview-4582419883): the message must describe the variant's condition, not its first call site
- [y-scope/spider#449](https://github.com/y-scope/spider/pull/449): reuses `DispatchQueueClosed`; a variant no caller acted on was dropped
- [y-scope/spider#464](https://github.com/y-scope/spider/pull/464#discussion_r3905746575): `IllegalResourceGroupId` may be a wrong password; rename it, drop the `String`
- [y-scope/spider#480](https://github.com/y-scope/spider/pull/480): adds `ResourceGroupAlreadyExists` so callers can react to `ALREADY_EXISTS`
- [spider `spider-core/src/task/mod.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/task/mod.rs#L8-L33): task `Error` with message-only variants for task graph deserialization
- [RustTraining type-driven-correctness-book § Case Study: IPMI FRU Data](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch07-validated-boundaries-parse-dont-validate.html#case-study-ipmi-fru-data): `FruError` variants carry typed `{ expected, actual }` fields

## ERR-4: Keep the cause attached; box it instead of turning it into a string or making the error generic

**Rule.** When you translate an error, keep the original as a typed field (bare, `#[source]` or
`#[from]`), as a `Box<dyn std::error::Error + Send + Sync>` when it is large or comes from caller
code. Never use `e.to_string()` or `map_err(|_| ..)` for this. Don't add a type parameter to an
error enum just to hold a foreign error. Box the error instead, and bound generic inputs by
`std::error::Error + Send + Sync + 'static`. Our logs use `error = % e`, which prints only
`Display`, so each wrapping variant's message must include its cause: interpolate `{0}` or
`{source}`, or use `#[error(transparent)]`.

**Why.** Turning an error into a string loses its type. A `JoinError` can no longer answer
`is_panic()` vs `is_cancelled()`, a `tonic::Status` loses its code, and classifiers like
`is_fatal()` or retry checks can't look inside text. `map_err(|_| ..)` loses even more:
`env::var(..).map_err(|_| MissingEnvVar)` reports "not set" for a value that is set but isn't valid
UTF-8. A type parameter on an error enum spreads into every event type, stream type and caller
signature, just so the error can be logged in the end.
[y-scope/clp#2705](https://github.com/y-scope/clp/pull/2705#discussion_r4568983772) boxed the
termination error so that `SessionEvent` stays non-generic. Boxing also keeps `Result` small, which
`clippy::result_large_err` checks. A message-only wrapper such as `#[error("failed to read config")]
Io(#[from] io::Error)` removes the root cause from every `%` log line. Interpolating a `#[source]`
field makes chain printers such as anyhow's `{:#}` show the cause twice; we accept that, because our
logs print `Display`.

```rust,ignore
// Bad
pub enum SessionEventError<TerminationErrorType: Send + 'static> {
    Termination(TerminationErrorType),
    TerminationTaskFailed(String),
}

handle
    .await
    .map_err(|e| SessionEventError::TerminationTaskFailed(e.to_string()))?;
```

```rust,ignore
// Good
#[derive(Debug, thiserror::Error)]
pub enum SessionEventError {
    #[error("waiting for the query job's termination failed: {0}")]
    Termination(Box<dyn std::error::Error + Send + Sync>),

    #[error("the task waiting for the query job's termination failed: {0}")]
    TerminationTaskFailed(JoinError),
}

handle.await.map_err(SessionEventError::TerminationTaskFailed)?;
```

**Review.**
- `map_err(|e| X(e.to_string()))`, helpers like `to_transport_error(impl Display)`, or a
  `Variant(String)` built from a typed error → keep the typed error, boxed if it is large
  (`Box<tonic::Status>`). `map_err(|_| ..)` is acceptable only when the dropped error says nothing
  beyond what the variant already stores, such as a `TryFromIntError` once the value itself is
  recorded.
- A type parameter on an error enum, or an unbounded `ErrorType: Send` → box the error and require
  `std::error::Error + Send + Sync + 'static`.
- A wrapping variant whose message leaves out its cause and isn't `transparent` → interpolate the
  cause.

**Exceptions.** Turn an error into a `String` or a serializable DTO only where it crosses a process,
FFI or wire boundary, and only at that boundary. When one failure is fanned out to several receivers
and the error isn't `Clone`, one owner keeps the typed error and the others may carry its message
(`Session::fail` in the query result listener), or share it through an `Arc`.

**Sources.**

- [y-scope/clp#2705](https://github.com/y-scope/clp/pull/2705#discussion_r4568970549): reviewer asks to box the termination error instead of a type parameter
- [clp `clp-rust-libs/query-result-listener/src/session/event.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/query-result-listener/src/session/event.rs#L33-L44): `SessionEventError` boxes the termination error and keeps `JoinError` typed
- [clp `clp-rust-libs/query-result-listener/src/session/state.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/query-result-listener/src/session/state.rs#L118-L131): `State::fail` keeps the typed error once; the connection gets its message
- [spider `spider-scheduler/src/core_impl/inbound_queue_reader.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/core_impl/inbound_queue_reader.rs#L243-L304): `JoinError` stringified into `SchedulerError::Internal`, losing `is_panic()`
- [spider `spider-client/src/error.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-client/src/error.rs#L3-L54): `String` variants and `to_transport_error(impl Display)` drop the typed cause
- [spider `spider-core/src/types/resource_group.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/types/resource_group.rs#L51-L60): `env::var(..).map_err(|_| MissingEnvVar)` reports a non-UTF-8 value as unset
- [y-scope/spider#283](https://github.com/y-scope/spider/pull/283#discussion_r2934491996): serde errors are boxed into `DbError` variants, not stringified
- [y-scope/spider#353](https://github.com/y-scope/spider/pull/353): a small `UnpackError` keeps `Result` under `clippy::result_large_err`
- [RustTraining type-driven-correctness-book § Error Type Hierarchies as Correctness](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch11-fourteen-tricks-from-the-trenches.html#trick-13--error-type-hierarchies-as-correctness): a nested `#[from]` keeps the cause typed instead of a string

## ERR-5: Handle an error once: return it, or log it where the decision is made

**Rule.** A function either propagates an error (with `?`, adding context) or handles it (logs and
recovers, skips, or cancels), never both. Log in the layer that makes the decision, usually the task
entry point, the spawn or join site, or `main`. Attach the identifying fields (`job_id`, `task_id`)
with `inspect_err`. Log through `tracing`, including in `Drop` impls, and never through `eprintln!`.
A helper returns `Result`; it doesn't log internally and then return `Option`.

**Why.** The Spider scheduler core's error is logged three times: in `run`, in the spawn wrapper,
and in `Runtime::stop`. One failure therefore looks like three incidents. A helper that logs and
then returns `Option` hides which layer made the decision and leaves the caller unable to propagate
the error or add context
([y-scope/clp#2435](https://github.com/y-scope/clp/pull/2435#discussion_r3736535562)). The outermost
boundary is the last place where the job and task IDs are available. Spider's task runtime records
only a status and a message, so a task that returns an error without logging leaves nothing to debug
with ([y-scope/clp#2646](https://github.com/y-scope/clp/pull/2646#discussion_r4438107545)).
`eprintln!` bypasses the file and collector sinks that tracing sets up
([y-scope/clp#2286](https://github.com/y-scope/clp/pull/2286#discussion_r3352377854)). In `main`,
don't let both tracing and anyhow's `Termination` print the same error
([y-scope/clp#1783](https://github.com/y-scope/clp/pull/1783#discussion_r2624419610)).

```rust,ignore
// Bad
async fn try_deserialize_config(&self, job_id: JobId, bytes: &[u8]) -> Option<Config> {
    match ZstdMsgpack::deserialize(bytes) {
        Ok(config) => Some(config),
        Err(e) => {
            tracing::error!(error = % e, "Failed to deserialize config.");
            self.mark_job_failed(job_id, &e.to_string()).await;
            None
        }
    }
}
```

```rust,ignore
// Good
let config: Config = match ZstdMsgpack::deserialize(&row.serialized_config) {
    Ok(config) => config,
    Err(e) => {
        tracing::error!(job_id = % row.id, error = % e, "Failed to deserialize config. Skipping.");
        self.mark_job_failed(row.id, &format!("failed to deserialize config: {e}")).await;
        continue;
    }
};
```

**Review.**
- An inner layer that logs and then returns `Err` (or uses `inspect_err(|e| tracing::error!(..))?`)
  while its caller also logs → keep only the log in the layer that decides. A helper that logs
  internally and returns `Option`, or has hidden side effects such as marking a job failed → return
  `Result`.
- A task entry point, or a step in `main`, that exits through `?` with no log carrying its
  identifying fields → add `inspect_err` with those fields.
- `eprintln!` or `println!` used to report an error → `tracing::error!`. A refactor that deletes a
  log point → carry the log point over to the new code
  ([y-scope/clp#2643](https://github.com/y-scope/clp/pull/2643#discussion_r4437040675)).

**Exceptions.** A helper may log internally when it has to branch both its logging and its reaction
on the error kind (`create_job_handle` in
[y-scope/clp#2435](https://github.com/y-scope/clp/pull/2435#discussion_r3736535562)). An operation
that is best-effort by design logs its own failure and returns `()` (ERR-9).

See also: coding-style.md § Log field formatting, coding-style.md § Error messages, TEST-9
(structured fields and spans).

**Sources.**

- [spider `spider-scheduler/src/runtime.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/runtime.rs#L49-L164): the core's error is logged in the spawn wrapper and again in `Runtime::stop`
- [spider `spider-scheduler/src/core_impl/resource_group_round_robin/implementation.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/core_impl/resource_group_round_robin/implementation.rs#L116-L157): `run` logs the error it also propagates
- [y-scope/clp#1740](https://github.com/y-scope/clp/pull/1740#discussion_r2599931287): the error is already logged at the top level where the task is spawned
- [y-scope/clp#1783](https://github.com/y-scope/clp/pull/1783#discussion_r2624419610): anyhow and tracing would both print the same error from `main`
- [y-scope/clp#2286](https://github.com/y-scope/clp/pull/2286#discussion_r3352377854): use tracing, not stderr, so the logging framework catches the error
- [y-scope/clp#2435](https://github.com/y-scope/clp/pull/2435#discussion_r3736535562): helpers return `Result` and the caller logs; `create_job_handle` is the exception
- [y-scope/clp#2643](https://github.com/y-scope/clp/pull/2643#discussion_r4437040675): a log point dropped by the refactor should be added back
- [y-scope/clp#2646](https://github.com/y-scope/clp/pull/2646#discussion_r4438107545): the task entry point should `inspect_err` with `job_id` and `task_id`
- [y-scope/spider#398](https://github.com/y-scope/spider/pull/398): adds `inspect_err` logs to each fallible step of the storage `main`

## ERR-6: Translate errors to wire responses in one exhaustive place, without leaking internals

**Rule.** At a gRPC or HTTP edge, convert domain errors to `Status` codes or responses in one place.
A default handler decides the log level and whether to cancel the service, and it matches every
variant, nested ones included, with no catch-all arm. Each endpoint's handler matches only the
variants that endpoint can produce and forwards the rest to the default handler. Client-caused
variants get specific codes and their `Display` text. Internal variants get a generic body, and the
full error goes to the log.

**Why.** With a catch-all arm, a new variant quietly gets `INTERNAL` and nobody decides whether it
should be a 404, retryable, or fatal
([spider scheduler grpc.rs](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/grpc.rs#L44-L111)).
Fatal arms copied into each handler drift apart: one refactor made stray errors cancel the storage
service in handlers where they should have been non-fatal
([spider#364](https://github.com/y-scope/spider/pull/364#discussion_r3522530338)). Putting an
internal error (SQL text, an AWS SDK error, a file path) in the response body exposes infrastructure
details ([y-scope/clp#1740](https://github.com/y-scope/clp/pull/1740#discussion_r2599309102)). An
arm for a variant that the path can't produce tells readers that it can happen
([spider#369](https://github.com/y-scope/spider/pull/369#discussion_r3525890576): "This can never
happen for user-interfacing API").

```rust,ignore
// Bad
impl IntoResponse for Error {
    fn into_response(self) -> Response {
        (StatusCode::INTERNAL_SERVER_ERROR, self.to_string()).into_response()
    }
}
```

```rust,ignore
// Good
impl IntoResponse for Error {
    fn into_response(self) -> Response {
        let (status, message) = match &self {
            Self::Manager(ManagerError::Internal(_)) => {
                tracing::error!(error = % self, "Request failed on an internal error.");
                (StatusCode::INTERNAL_SERVER_ERROR, "internal server error".to_owned())
            }
            Self::Manager(ManagerError::JobNotFound(_)) => {
                (StatusCode::NOT_FOUND, self.to_string())
            }
            Self::Manager(ManagerError::InvalidConfig(_)) => {
                (StatusCode::BAD_REQUEST, self.to_string())
            }
        };
        (status, Json(ErrorResponse { error: message })).into_response()
    }
}
```

**Review.**
- An `error =>` or `_ =>` arm in the default handler that maps to `INTERNAL` or 500 → name every
  remaining variant.
- `self.to_string()` or `e.to_string()` in a 5xx body → return a generic message and log the full
  error.
- An arm for a variant the endpoint can't produce, or a `cancel()` arm repeated across handlers →
  forward to the default handler.

See also: BND-9 (what each status code means across the system, and the client-side decoder).

**Sources.**

- [spider `spider-scheduler/src/grpc.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/grpc.rs#L44-L111): `service_error_handler` ends in a catch-all `error =>` arm mapping to `INTERNAL`
- [spider `spider-storage/src/grpc.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/grpc.rs#L386-L477): `default_error_handler` decides log level and fatal shutdown for forwarded errors
- [y-scope/spider#364](https://github.com/y-scope/spider/pull/364#discussion_r3525523065): per-service handlers match their own errors and forward the rest to one default
- [y-scope/spider#369](https://github.com/y-scope/spider/pull/369#discussion_r3525890576): reviewer flags an arm for a variant the user-facing API can't produce
- [y-scope/spider#539](https://github.com/y-scope/spider/pull/539): every handler answers `Stopping` with `UNAVAILABLE`, never fatal
- [y-scope/clp#1740](https://github.com/y-scope/clp/pull/1740#discussion_r2599309102): returning the serialized error could expose internal information
- [y-scope/clp#2058](https://github.com/y-scope/clp/pull/2058#discussion_r2897700947): bad-request errors may show `Display`; internal errors stay behind a generic body
- [clp `log-ingestor/src/routes.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/log-ingestor/src/routes.rs#L81-L107): `IntoResponse` maps each variant; internal errors get a generic body

## ERR-7: Return expected outcomes in `Ok`, and keep `Err` for failures

**Rule.** When absence is a normal answer, a query-style function returns `Ok(None)` and lets the
caller decide whether that is an error. When an operation has several routine non-success results
(the task failed, timed out, or crashed), return them as an outcome enum inside `Ok`. Return `Err`
only when the operation itself failed. That includes a mutation whose target doesn't exist: it
returns a `NotFound` variant carrying the key and must not report success because zero rows were
affected.

**Why.** Spider's process pool returns `Result<Outcome, InternalError>`. With that split, `?` can't
mix up "the user's task failed" (routine, reported) with "the pool is dead" (restart), and callers
have to handle every outcome. Returning `Err` for "not applicable here" makes callers treat normal
control flow as a failure and blocks reuse, for example from cleanup tasks
([spider#390](https://github.com/y-scope/spider/pull/390#discussion_r3567668760)). The opposite
mistake, an `Option` where the empty case is a failure, lets an empty input through as success
([y-scope/clp#2643](https://github.com/y-scope/clp/pull/2643#discussion_r4432515504)). An `UPDATE`
that matches no row returns `Ok`, so cancelling a mistyped job ID returned 200
([y-scope/clp#1964](https://github.com/y-scope/clp/pull/1964#pullrequestreview-3775154122)). Sibling
functions must agree: `get_status` and `request_cancellation` on a missing job should behave the
same way ([y-scope/clp#2617](https://github.com/y-scope/clp/pull/2617#discussion_r4389499797)).

```rust,ignore
// Bad
impl TryFrom<TimeRangeRow> for TimeRange {
    type Error = ();
    // ...
}

let range = TimeRange::try_from(row).ok();

pub async fn execute(&self, request: ExecuteRequest) -> Result<Vec<u8>, PoolError>;
```

```rust,ignore
// Good
impl From<TimeRangeRow> for Option<TimeRange> {
    fn from(row: TimeRangeRow) -> Self {
        let (Some(begin), Some(end)) = (row.begin, row.end) else {
            return None;
        };
        Some(TimeRange { begin, end })
    }
}

pub enum Outcome {
    Success { outputs: Vec<u8> },
    InTaskFailure { error: MsgpackExecutorError },
    Timeout { hard_timeout: Duration },
    ExecutorCrash { exit_status: Option<i32> },
}

pub async fn execute(&self, request: ExecuteRequest) -> Result<Outcome, InternalError>;
```

**Review.**
- `TryFrom` with `Error = ()` followed by `.ok()` → use `From<Row> for Option<T>` when absence is
  legitimate, or a real error type when it isn't.
- An `Option` return where the empty case is a failure → return `Result`. A mutation that treats "no
  row matched" as success → return a `NotFound` variant named after the resource, so sibling
  operations can reuse it.
- An error enum that mostly holds routine outcomes, where callers rarely want `?` → move those
  outcomes into an `Ok` enum. If they have to stay mixed, document fatality on each variant and have
  callers match exhaustively.

See also: TYPE-9 (named outcome enums instead of `bool`).

**Sources.**

- [spider `spider-execution-manager/src/process_pool.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/process_pool.rs#L66-L111): `Outcome` holds routine task results; `InternalError` holds pool failures
- [spider `spider-scheduler/src/core_impl/resource_group_round_robin/scheduling_state.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/core_impl/resource_group_round_robin/scheduling_state.rs#L18-L40): `MakeAssignmentError` mixes routine outcomes and documents fatality per variant
- [clp `api-server/src/webui_client/metadata.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/api-server/src/webui_client/metadata.rs#L553-L572): `From<TimeRangeRowProjection> for Option<TimeRange>` for legitimate absence
- [y-scope/spider#390](https://github.com/y-scope/spider/pull/390#discussion_r3567668760): a query method returns `None` instead of failing, so cleanup tasks can reuse it
- [y-scope/clp#1964](https://github.com/y-scope/clp/pull/1964#pullrequestreview-3775154122): cancelling a nonexistent job returns success
- [y-scope/clp#2058](https://github.com/y-scope/clp/pull/2058#discussion_r2877153906): add `DatasetNotFound` so a missing dataset returns 404, not 500
- [y-scope/clp#2607](https://github.com/y-scope/clp/pull/2607#discussion_r4381182000): `Option` for "no data yet"; `TryFrom<Error = ()>` plus `.ok()` looks like swallowing
- [y-scope/clp#2617](https://github.com/y-scope/clp/pull/2617#discussion_r4389499797): `get_status` and cancellation should treat a missing job the same way
- [y-scope/clp#2643](https://github.com/y-scope/clp/pull/2643#discussion_r4432515504): with no inputs, return an error instead of `Option`

## ERR-8: Use `#[from]` only when the source type has one meaning; write `From` impls by hand when they carry policy

**Rule.** `#[from]` (or any `From` impl) turns every `?` on that source type anywhere in the crate
into that variant, so add it only when that's correct at every call site. When the same source type
can come from several operations, use `map_err` at the call site to build a variant that carries
context. When the conversion classifies the error, write the `From` impl by hand. When converting a
foreign enum, match every variant by name.

**Why.** `ExecutorCreationFailure(#[from] std::io::Error)` labels the next unrelated I/O failure as
a spawn failure. `From<rmp_serde::decode::Error>` mapping to `ErrorPayloadDeserializationFailure`
mislabels every msgpack decode the same way. A blanket `#[from] io::Error` with no path field makes
every `?` report "No such file" without saying which file. A hand-written `From<DbError> for
CacheError` that routes to `Internal` makes the classification "a DB failure means the cache may be
inconsistent" visible in the diff ([spider#354](https://github.com/y-scope/spider/pull/354)). An
exhaustive match means a variant added by a dependency upgrade has to be classified explicitly,
instead of silently landing in the wrong bucket
([y-scope/clp#2649](https://github.com/y-scope/clp/pull/2649)).

```rust,ignore
// Bad
#[derive(Debug, thiserror::Error)]
pub enum CacheError {
    #[error(transparent)]
    Db(#[from] DbError),
}

#[derive(Debug, thiserror::Error)]
pub enum PoolError {
    #[error("failed to create executor: {0}")]
    ExecutorCreationFailure(#[from] std::io::Error),
}
```

```rust,ignore
// Good
impl From<DbError> for CacheError {
    fn from(err: DbError) -> Self {
        Self::Internal(InternalError::Db(err))
    }
}

#[derive(Debug, thiserror::Error)]
pub enum PoolError {
    #[error("failed to create executor: {0}")]
    ExecutorCreationFailure(#[source] std::io::Error),
}

let child = command.spawn().map_err(PoolError::ExecutorCreationFailure)?;
```

**Review.**
- For a new `#[from]`, grep the crate for `?` on that source type. If any of those call sites
  doesn't mean this variant, or if two variants wrap the same source type, use `map_err` instead.
- A `From` impl for a foreign enum with a `_` arm → list the variants explicitly, with a comment
  where the classification isn't obvious.
- A `From` impl that maps to the wrong variant, or that no call site needs, and exists only to make
  `?` compile → remove it.

**Exceptions.** A single generic `impl<E> From<SdkError<E>>` is fine for an SDK whose error type is
parameterized per operation, because the whole family has one meaning
([y-scope/clp#1728](https://github.com/y-scope/clp/pull/1728#discussion_r2594469214)). A
`#[non_exhaustive]` foreign enum (`sqlx::Error`, `io::ErrorKind`) forces a `_` arm: name every
variant you know, and send the `_` arm to the most conservative category, usually internal.

See also: coding-style.md § `map_err` for error translation.

**Sources.**

- [spider `spider-task-executor/src/error.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-task-executor/src/error.rs#L53-L69): blanket `From` impls, including `rmp_serde::decode::Error` to `ErrorPayloadDeserializationFailure`
- [spider `spider-execution-manager/src/process_pool.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/process_pool.rs#L85-L111): `ExecutorCreationFailure(#[from] std::io::Error)`, the pattern this rule flags
- [y-scope/spider#354](https://github.com/y-scope/spider/pull/354): a hand-written `From<DbError> for CacheError` routes DB errors to `Internal`
- [y-scope/clp#2649](https://github.com/y-scope/clp/pull/2649): hand-written `From` impls name every `rmp` decode-error variant
- [y-scope/clp#1728](https://github.com/y-scope/clp/pull/1728#discussion_r2594469214): one generic `From<SdkError<E>>` covers the whole AWS SDK error family
- [RustTraining rust-patterns-book § Public API Design Checklist](https://microsoft.github.io/RustTraining/rust-patterns-book/ch15-crate-architecture-and-api-design.html#public-api-design-checklist): a `#[non_exhaustive]` enum forces downstream `_` arms

## ERR-9: Make best-effort explicit in the signature

**Rule.** An operation that is best-effort by design returns `()`, logs its own failures with
context, and discards the result explicitly with `let _ = op().await.inspect_err(|e|
tracing::warn!(..));`. This covers cleanup, acknowledgements, telemetry, and sends to an actor whose
failure is reported elsewhere. For batch and recovery loops, choose either fail-fast (`?`, and the
supervisor restarts) or per-item best-effort (log each item with its ID and continue), and make the
choice visible.

**Why.** When callers routinely discard a `Result` with `let _ =`, some callers start propagating it
while others drop it, so the same operation behaves differently depending on who calls it
([spider#365](https://github.com/y-scope/spider/pull/365#pullrequestreview-4602898177)). A
`shutdown_and_join` that returns an error that has already been logged forces every caller to write
a log-and-ignore arm, and that arm looks like a swallowed error
([y-scope/clp#2035](https://github.com/y-scope/clp/pull/2035)). On a failure path, cleanup of an
external resource, such as cancelling the Spider job that a failed `start` left behind, must not
replace the original error. Discarding the cleanup failure silently, though, hides why resources
leak ([y-scope/clp#2573](https://github.com/y-scope/clp/pull/2573#discussion_r4332285665)). In a
recovery loop, one bad config row shouldn't stop recovery of every other job, while a lost DB
connection should trigger a restart
([y-scope/clp#2053](https://github.com/y-scope/clp/pull/2053#discussion_r2870591214)).

```rust,ignore
// Bad
if let Err(e) = self.start(spider_job_id).await {
    let _ = self.job_submitter.cancel_query_job(spider_job_id).await;
    return Err(e);
}
```

```rust,ignore
// Good
if let Err(e) = self.start(spider_job_id).await {
    let _ = self
        .job_submitter
        .cancel_query_job(spider_job_id)
        .await
        .inspect_err(|cancel_error| {
            tracing::warn!(
                spider_job_id = % spider_job_id,
                error = % cancel_error,
                "Failed to cancel the Spider job after failing to start the query job."
            );
        });
    return Err(e);
}
```

**Review.**
- A bare `let _ = fallible()` → add `inspect_err` and a log. For a fire-and-forget actor send, a
  one-line comment saying where the failure is surfaced is enough (for example, the actor fires the
  cancellation token).
- A function that returns `Result` and that every caller ignores → move the policy into the function
  and return `()`. An enqueue method whose only failure is a closed receiver, already reported
  elsewhere, and that returns its payload as the error (`Result<(), JobId>`) → make it infallible
  fire-and-forget.
- A loop over independent items that uses `?` and aborts after earlier items already had side
  effects → decide the policy. For best-effort, log each failed item with its ID and `continue`.

See also: pr-review.md § Don't silently swallow errors (this rule is the case where discarding the
error is the intended design, and says how to discard it), and ASYNC-3 (where a spawned task's
failure goes).

**Sources.**

- [y-scope/spider#341](https://github.com/y-scope/spider/pull/341#pullrequestreview-4493746031): the GC handle shouldn't return errors; an actor failure fires the cancellation token
- [y-scope/spider#365](https://github.com/y-scope/spider/pull/365#pullrequestreview-4602898177): `complete_task_assignment` should be best effort and not return an error
- [y-scope/clp#1989](https://github.com/y-scope/clp/pull/1989#discussion_r2807733826): the S3 scanner's shutdown should stop returning an error
- [y-scope/clp#2035](https://github.com/y-scope/clp/pull/2035): `shutdown_and_join` no longer returns errors
- [y-scope/clp#2053](https://github.com/y-scope/clp/pull/2053#discussion_r2870591214): reviewer asks recovery to handle every job and give up only on failed ones
- [y-scope/clp#2573](https://github.com/y-scope/clp/pull/2573#discussion_r4332285665): log the failed cleanup cancel with `inspect_err` instead of a bare `let _`
- [clp `log-ingestor/src/ingestion_job_manager.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/log-ingestor/src/ingestion_job_manager.rs#L374-L418): best-effort recovery loop logs each failed job by ID and continues

## ERR-10: Give fallible trait methods an associated `Error` type

**Rule.** If any reasonable implementation of a trait method can fail (encoding, I/O, parsing),
declare `type Error: std::error::Error + Send + Sync + 'static;` and return `Result<_,
Self::Error>`. When one trait binds another, tie their error types together (`type Encoder:
ResultEncoder<Error = Self::Error>`). Infallible implementations use `std::convert::Infallible`
(TLC-5).

**Why.** The trait author doesn't know every implementation, and an encoder that writes to a file or
a stricter format can fail. An infallible signature then forces implementers to call `expect`. The
panic kills the spawned connection task without telling the session's consumer, so results are
silently lost and the job can still be reported as succeeded
([y-scope/clp#2690](https://github.com/y-scope/clp/pull/2690#discussion_r4530595289),
[y-scope/clp#2702](https://github.com/y-scope/clp/pull/2702)). With a typed error, the caller can
fail the session and log the error where someone will see it.

```rust,ignore
// Bad
trait ResultEncoder {
    fn encode(&mut self, ts: i64, message: &str);
}

impl ResultEncoder for SseEncoder {
    fn encode(&mut self, ts: i64, message: &str) {
        serde_json::to_writer(&mut self.buf, message).expect("serialization should succeed");
    }
}
```

```rust,ignore
// Good
trait ResultEncoder {
    type Error: std::error::Error + Send + Sync + 'static;

    fn encode(&mut self, ts: i64, message: &str) -> Result<(), Self::Error>;
}

impl ResultEncoder for SseEncoder {
    type Error = serde_json::Error;

    fn encode(&mut self, ts: i64, message: &str) -> Result<(), Self::Error> {
        serde_json::to_writer(&mut self.buf, message)
    }
}
```

**Review.**
- `expect`, `unwrap_or_default` or a silent fallback on a fallible operation inside a trait impl →
  add an associated `Error` to the trait.
- An associated `Error` without the `std::error::Error + Send + Sync + 'static` bound → add the
  bound, so callers can box and log the error (ERR-4).

**Exceptions.** Don't make a method fallible "just in case": `take_batch` stayed infallible in
[y-scope/clp#2702](https://github.com/y-scope/clp/pull/2702) because no implementation can fail.

See also: pr-review.md § Panic vs error returns, TLC-5 (associated types and `Infallible`).

**Sources.**

- [y-scope/clp#2690](https://github.com/y-scope/clp/pull/2690#discussion_r4530595289): `ResultEncoder` should take an error type instead of panicking
- [y-scope/clp#2702](https://github.com/y-scope/clp/pull/2702): makes `ResultEncoder` fallible; `take_batch` stays infallible
- [clp `clp-rust-libs/query-result-listener/src/encoding.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/query-result-listener/src/encoding.rs#L5-L67): `ResultEncoding` ties its `Encoder`'s `Error` to its own

# Designing types and their methods

A type is where an invariant lives, so its public surface should make that invariant impossible to
break from outside. In practice that means private fields, one validated way in, methods named for
domain operations instead of for the containers behind them, and cleanup that runs on every exit
path because the type guarantees it. Callers should only be able to do the right things, and the
compiler should check most of them. The rules are ordered by importance: the first three prevent
silent corruption or lost cleanup, and the last ones keep APIs honest and easy to review.

## OBJ-1: Keep invariant-carrying fields private and make the validating path the only way in

**Rule.** If a type has an invariant, keep the fields it constrains private and check the invariant
on every way of creating the value: the constructor, the builder, `Deserialize` (through
`#[serde(try_from = "Raw")]`) and any decoder. Where you can, design mutation APIs so that they can
only express valid states, instead of validating afterwards. TYPE-2 lists the construction paths to
seal; this rule adds the design of the type's own methods.

**Why.** A validating `new` protects nothing if the same type also derives `Deserialize` or exposes
the constrained field as `pub`. `TaskContext::new` rejected "commit task without outputs", but a
decoded or mutated `TaskContext` could still break the invariant that `get_task_graph_outputs`
relied on. The strongest version of this rule is an API that cannot express the bad state at all.
Spider's `TaskGraph::insert_task` can only refer to tasks that are already in the graph, so every
graph is acyclic by construction, and deserialization replays the same inserts to get the same
guarantee. No `validate_acyclic` pass is needed.

```rust,ignore
// Bad
#[derive(serde::Deserialize)]
pub struct TaskContext {
    pub task_id: TaskId,
    pub outputs: Option<Vec<u8>>,
}

impl TaskContext {
    pub fn new(task_id: TaskId, outputs: Option<Vec<u8>>) -> Result<Self, Error> { /* validates */ }
}
```

```rust,ignore
// Good
#[derive(serde::Deserialize)]
#[serde(try_from = "RawTaskContext")]
pub struct TaskContext {
    task_id: TaskId,
    outputs: Option<Vec<u8>>,
}

impl TaskContext {
    pub fn new(task_id: TaskId, outputs: Option<Vec<u8>>) -> Result<Self, Error> { /* validates */ }
}

impl TryFrom<RawTaskContext> for TaskContext {
    type Error = Error;

    fn try_from(raw: RawTaskContext) -> Result<Self, Self::Error> {
        Self::new(raw.task_id, raw.outputs)
    }
}

#[derive(serde::Deserialize)]
struct RawTaskContext {
    task_id: TaskId,
    outputs: Option<Vec<u8>>,
}
```

**Review.**
- Flag a validating `new` or `validate_and_create` on a type that also derives `Deserialize` without
  `serde(try_from)`, or that has `pub` constrained fields. The fix is private fields plus
  `serde(try_from)` routed through the same constructor.
- Flag after-the-fact checkers (`validate_acyclic`, `check_references`) and convenience APIs that
  reopen the invalid space, such as batch inserts with forward references. Change the mutation API
  instead.
- Flag fields widened to `pub(super)` "so tests can inspect them". Keep them private and, if a test
  really needs it, add a narrow `#[cfg(test)]` accessor. Also check that handles minted by a builder
  (e.g. `SharedInputId { raw }`) are still bounds-checked where they are used: a handle proves that
  *a* builder made it, not that *this* builder did.

**Exceptions.** Plain records with no cross-field invariant, such as `sqlx::FromRow` rows, wire
DTOs, or raw configs that are validated into a `Validated*` type, may have `pub` fields.

See also: coding-style.md § Type-Level Validation, TYPE-2 and BND-1.

**Sources.**

- [y-scope/spider#390](https://github.com/y-scope/spider/pull/390): `TaskContext::new` checks the commit-outputs invariant; the accessor trusts it
- [y-scope/spider#397](https://github.com/y-scope/spider/pull/397#pullrequestreview-4698875645): credentials resolved inside `serde` (`try_from` a raw type), not afterwards
- [y-scope/spider#280](https://github.com/y-scope/spider/pull/280#issuecomment-3797846035): inserts one by one, so no task can reference a missing task
- [y-scope/spider#281](https://github.com/y-scope/spider/pull/281): deserialization replays `insert_task` for each serialized `TaskDescriptor`
- [spider `spider-core/src/types/io/task_graph_input.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/types/io/task_graph_input.rs#L128-L183): `TaskGraphInput`: private fields, invariant enforced by builder and decoder
- [spider `spider-scheduler/src/core_impl/resource_group_round_robin/implementation.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/core_impl/resource_group_round_robin/implementation.rs#L45-L75): counterexample: every field `pub(super)` so tests can inspect state

## OBJ-2: Return a ready-to-use value from every factory function

**Rule.** A factory function acquires the resources the type needs and runs its one-time setup
before it returns `Ok(Self)`. Each distinct creation situation (fresh, or recovered from state X)
gets its own factory that builds exactly the fields that situation needs. Do not construct and then
patch, and do not require a follow-up `init()` call.

**Why.** If a type has a separate `initialize()` step, a value can exist in an unusable state, and
callers can forget the call or make it twice. When that step was a trait method, every
implementation had to carry it. Building a generic value and then calling `restore_outputs` had to
write through a handle that was deliberately read-only. Recovery factories are where this bites
hardest: `TaskGraph::recover_from_commit_ready` hard-coded `cleanup_task: None`, so after a restart,
cancelling a recovered job requested the wrong transition and shut storage down. Happy-path tests
never restart, so none of them caught it.

```rust,ignore
// Bad
let pool = MySqlPoolOptions::new().connect(&url).await?;
let connector = MariaDbStorageConnector::new(pool);
connector.initialize().await?;

let mut graph = TaskGraph::create(submission).await?;
graph.restore_outputs(outputs).await?;
```

```rust,ignore
// Good
impl MariaDbStorageConnector {
    pub async fn connect(config: &DatabaseConfig) -> Result<Self, DbError> {
        let pool = MySqlPoolOptions::new()
            .max_connections(config.max_connections)
            .connect_with(config.connect_options())
            .await?;
        let connector = Self { pool };
        connector.create_tables().await?;
        Ok(connector)
    }
}

let graph = match state {
    JobState::Running => TaskGraph::create(submission).await?,
    JobState::CommitReady => {
        let Some(commit) = submission.commit_task else {
            return Err(InternalError::MissingCommitTask.into());
        };
        TaskGraph::recover_from_commit_ready(commit, submission.cleanup_task, outputs)
    }
    JobState::CleanupReady => {
        let Some(cleanup) = submission.cleanup_task else {
            return Err(InternalError::MissingCleanupTask.into());
        };
        TaskGraph::recover_from_cleanup_ready(cleanup)
    }
    other => return Err(InternalError::UnexpectedJobState(other).into()),
};
```

**Review.**
- Flag `init`, `initialize` or `setup` methods (especially trait methods) that must be called after
  construction. Fold them into the factory as private helpers.
- Flag `restore_*` or "fix up" calls after construction. Replace them with one factory per case,
  dispatched in a single `match` whose arms check their own preconditions with `let ... else`.
- In a recovery factory (`recover_*`, `from_row`), compare every field with the creation path, and
  ask for a test showing that a recovered object behaves like a freshly created one. If many methods
  repeat `.as_ref().expect(..)` on the same `Option` config field, resolve it once in the factory
  (return an error, or document the panic as `from_config` does) and store the inner value in a
  non-`Option` field.

**Exceptions.** A fallible resource that only some code paths need should not be resolved at
startup. Resolve it lazily, for example with a function returning `Result<&'static T, E>` over a
`static OnceLock`, so that S3-only jobs don't fail when `/mnt/logs` is absent.

**Sources.**

- [y-scope/spider#283](https://github.com/y-scope/spider/pull/283#discussion_r2920992760): a call-once init trait method belongs in the private factory
- [y-scope/spider#285](https://github.com/y-scope/spider/pull/285#discussion_r2976155403): factory creates the pool and initializes tables before returning
- [y-scope/spider#339](https://github.com/y-scope/spider/pull/339#discussion_r3383142317): restoring outputs wrote through a read-only reader handle
- [y-scope/spider#339](https://github.com/y-scope/spider/pull/339#pullrequestreview-4471850284): don't mutate the task graph after construction; add per-case factories
- [y-scope/spider#524](https://github.com/y-scope/spider/pull/524): recovered `CommitReady` job lacked its cleanup task; cancelling shut storage down
- [y-scope/clp#1927](https://github.com/y-scope/clp/pull/1927#discussion_r2737006531): check the `Option` config once in the factory; wrap the `expect`
- [y-scope/clp#2661](https://github.com/y-scope/clp/pull/2661#discussion_r4474008260): lazily initialized static mount point, so S3 jobs don't need it

## OBJ-3: Tie mandatory cleanup to a guard's `Drop`, and give the normal path a consuming method

**Rule.** Anything that must happen on every exit runs from the `Drop` of a guard created right
after the acquire step: deregistration, killing a child process, cancelling tasks, escalating a
half-applied mutation, restoring state after a `with_*` closure. If the cleanup can fail or has to
be awaited, also provide a consuming `close(self)`, `commit(self)` or `disarm(self)` for the normal
path, and keep `Drop` as the synchronous, best-effort fallback that never blocks and logs failures
instead of discarding them.

**Why.** An early `?`, a panic and a dropped future all skip a `close()` that callers have to
remember. Before [y-scope/clp#2702](https://github.com/y-scope/clp/pull/2702), dropping a session
only unregistered it, and its open connections kept streaming. Spider's `PartialMutationGuard` turns
"the cache was mutated but the DB write returned `Err` or was cancelled" from a silent inconsistency
into a fatal shutdown, which recovery then repairs from the DB (DEF-1). `Drop` cannot `.await`, so
the only async work it can start is a spawned task, and that task cannot report back: `tokio::spawn`
panics if the value is dropped outside a runtime, and a `let _ =` inside the task swallows the one
error the caller cared about. That is why awaited, fallible cleanup needs a consuming method the
caller can `?`. Note also that `Drop::drop` runs before the struct's own fields are dropped, so a
value that must be dropped after the guard's action, such as a reply sender that wakes a waiter,
belongs inside the guard.

```rust,ignore
// Bad
async fn handle(&self, job_id: JobId) -> Result<(), Error> {
    self.cache.mutate(job_id)?;
    self.db.write(job_id).await?;
    Ok(())
}
```

```rust,ignore
// Good
#[must_use = "dropping the guard without disarming it shuts the service down fatally"]
pub struct PartialMutationGuard<'shutdown_handle> {
    shutdown_handle: Option<&'shutdown_handle ShutdownHandle>,
}

impl<'shutdown_handle> PartialMutationGuard<'shutdown_handle> {
    pub const fn new(shutdown_handle: &'shutdown_handle ShutdownHandle) -> Self {
        Self { shutdown_handle: Some(shutdown_handle) }
    }

    pub fn disarm(mut self) {
        self.shutdown_handle.take();
    }
}

impl Drop for PartialMutationGuard<'_> {
    fn drop(&mut self) {
        if let Some(shutdown_handle) = self.shutdown_handle.take() {
            tracing::error!("Handler body stopped after a partial mutation.");
            shutdown_handle.shut_down_fatally();
        }
    }
}

let guard = PartialMutationGuard::new(&self.shutdown_handle);
self.cache.mutate(job_id)?;
self.db.write(job_id).await?;
guard.disarm();
```

**Review.**
- Flag `fn cleanup(&mut self)` or `close(&self)` methods that callers must remember, and teardown
  written as a statement after `f(..)` or after an `.await`. Move it into a guard's `Drop`. Use
  `Command::kill_on_drop(true)` for child processes and a stored `_cancel_guard: DropGuard` for
  tokens. Flag a hand-written `tx.rollback()` on every error branch, since `sqlx::Transaction`
  already rolls back on drop. A guard only undoes what it owns, though: session state set on the
  pooled connection outside the transaction outlives it.
- Flag guard types without `#[must_use = "..."]`, and guards bound to `_`, which drops them
  immediately. rustc already rejects `let _ = std_mutex.lock()`, but nothing catches
  `let _ = tokio_mutex.lock().await`, `let _ = span.enter()` or a `DropGuard` bound to `_`. Bind
  them with `let _guard = ...`.
- Flag `Drop` impls that `block_on`, discard an error with `let _ =`, or spawn the only copy of
  cleanup whose failure matters. Ask for a consuming `async fn close(self) -> Result<..>` for the
  normal path, and leave `Drop` to cancel, abort, log (`tracing::warn!(err = % err, "Failed to close
  session on drop.")`), or spawn a best-effort fallback through
  `tokio::runtime::Handle::try_current()` so a drop outside a runtime does not panic.

See also: coding-style.md § Take ownership when the value mustn't be used afterwards (keep the state
`Drop` needs in an `Option`; don't use `mem::forget` to skip `Drop`; spawning is for `Drop` only).

**Sources.**

- [y-scope/clp#2689](https://github.com/y-scope/clp/pull/2689): dropping a session unregisters it; dropping the listener stops accepting
- [y-scope/clp#2702](https://github.com/y-scope/clp/pull/2702): dropping a session now also cuts off its open connections
- [y-scope/clp#2014](https://github.com/y-scope/clp/pull/2014#discussion_r2841594925): `sqlx::Transaction` rolls back on drop; no explicit `rollback` needed
- [y-scope/clp#2286](https://github.com/y-scope/clp/pull/2286#discussion_r3364933661): `TelemetryGuard` is an RAII guard that shuts telemetry down on drop
- [y-scope/clp#2286](https://github.com/y-scope/clp/pull/2286#discussion_r3364924355): log the drop-path shutdown failure with `tracing::error!`
- [spider `spider-storage/src/partial_mutation.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/partial_mutation.rs#L8-L95): `PartialMutationGuard`: consuming `disarm`, fatal shutdown in `Drop`
- [spider `spider-storage/src/state/tree_committer/mod.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/state/tree_committer/mod.rs#L168-L234): guard owns reply senders so they drop after `Drop::drop`
- [spider `spider-execution-manager/src/process_pool.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/process_pool.rs#L213-L289): `spawn_executor` sets `kill_on_drop(true)` on the child process
- [spider `spider-execution-manager/src/runtime.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/runtime.rs#L87-L113): `Runtime` stores `_cancel_guard: DropGuard` for its token
- [RustTraining async-book § No Async Drop](https://microsoft.github.io/RustTraining/async-book/ch12-common-pitfalls.html#no-async-drop): `Drop` can't await; offer `async fn close(self)`, `Drop` as safety net
- [RustTraining rust-patterns-book § The `with` Pattern — Bracketed Resource Access](https://microsoft.github.io/RustTraining/rust-patterns-book/ch07-closures-and-higher-order-functions.html#the-with-pattern--bracketed-resource-access): `with_*` bracketing; its teardown after `f()` is skipped on panic
- [RustTraining rust-patterns-book § Public API Design Checklist](https://microsoft.github.io/RustTraining/rust-patterns-book/ch15-crate-architecture-and-api-design.html#public-api-design-checklist): `#[must_use = "..."]` on guard types

## OBJ-4: Give a type exactly the dependencies it owns

**Rule.** A constructor takes only what exists before the object starts its job. A collaborator the
type cannot work without is a required, non-`Option` constructor parameter, never a config field. A
shared `Arc<Context>` holds only process-wide state, and per-job or per-item values travel with the
job or item.

**Why.** Spider's `ServiceState` once had an `Option<GcHandle>` and two constructors, `new` and
`new_with_gc`, only so that old tests compiled unchanged. Production never runs without GC, but any
caller that picked the wrong constructor silently disabled it, and every use site had to branch on
`None`. Putting a log handle in `ProcessPoolConfig` made the config impossible to deserialize.
Putting a per-query `OutputHandle` in a context shared by all jobs either forces one context per job
or applies one job's setting to another. Likewise, `QueryJobHandle::new(.., archives_to_search)`
took the result of planning, which is the handle's own job.

```rust,ignore
// Bad
pub struct ServiceState {
    db: Db,
    gc: Option<GcHandle>,
}

impl ServiceState {
    pub const fn new(db: Db) -> Self { Self { db, gc: None } }
    pub const fn new_with_gc(db: Db, gc: GcHandle) -> Self { Self { db, gc: Some(gc) } }
}

struct JobHandleContext {
    db_pool: MySqlPool,
    output_handle: OutputHandle,
}
```

```rust,ignore
// Good
pub struct ServiceState {
    db: Db,
    gc: GcHandle,
}

impl ServiceState {
    pub const fn new(db: Db, gc: GcHandle) -> Self { Self { db, gc } }
}

struct JobHandleContext {
    db_pool: MySqlPool,
    spider_option: SpiderOption,
}

struct ArchiveSearchTask {
    archive: ArchiveMetadata,
    execution_policy: ExecutionPolicy,
}

fn submit(output_handle: OutputHandle, tasks: Vec<ArchiveSearchTask>) { /* ... */ }
```

**Review.**
- Flag an `Option` field for a dependency that every production caller provides, the
  `let Some(x) = &self.x else { return; }` branches that come with it, and any second constructor
  that exists only to spare tests. Make the dependency required, and have tests pass a no-op one
  (e.g. `GcHandle::new(mpsc::unbounded_channel().0)`).
- Flag clients, senders, tokens or log sinks inside a `Deserialize` config struct. Move them to
  separate `new` parameters, and delete config fields whose only consumer is gone.
- Flag a shared-context field whose value differs per job, and a constructor parameter that is the
  output of the object's own work. Move the first onto the job. Turn the second into a method stage
  (`run` → `plan` → `submit` → `to_completion`).

See also: coding-style.md § API design, coding-style.md § What deserves a unit test (no test-only
seams in production code).

**Sources.**

- [y-scope/spider#341](https://github.com/y-scope/spider/pull/341#pullrequestreview-4493746031): make the GC handle required; drop the test-only second constructor
- [y-scope/spider#418](https://github.com/y-scope/spider/pull/418): log handle moves out of `ProcessPoolConfig` into a `ProcessPool::new` argument
- [y-scope/clp#2513](https://github.com/y-scope/clp/pull/2513#discussion_r4055064033): `OutputHandle` is per-job, so it doesn't belong in the shared context
- [y-scope/clp#2513](https://github.com/y-scope/clp/pull/2513#discussion_r3963934405): `archives_to_search` is the handle's own planning output, not a parameter
- [y-scope/clp#2504](https://github.com/y-scope/clp/pull/2504#discussion_r3915961824): execution policy is per-task, so pair it with each archive
- [y-scope/clp#2564](https://github.com/y-scope/clp/pull/2564): each archive's timeouts derive from that archive's own size

## OBJ-5: Share state through a cloneable handle over one private `Arc`

**Rule.** Expose state that is shared across tasks as `#[derive(Clone)] pub struct X { inner:
Arc<XInner> }` with a private inner type, whose `&self` methods own all locking and whose protected
data lives inside the lock. Do not hand `Arc<Mutex<_>>`, bare atomics, or (when cancelling can mean
more than one thing) a raw `CancellationToken` to other modules. Wrap them in a handle whose methods
name each allowed operation.

**Why.** A single `Arc` makes a clone cost one refcount bump instead of one per field (six, in
`ServiceState`), and it keeps every clone pointing at one coherent state. If every call site locks
for itself, every call site picks its own lock scope. With a raw `Arc<AtomicU64>`, any holder can
`store` a session ID that moves backwards. With a bare token, a fatal error and a SIGTERM are the
same `cancel()` call, so the process cannot choose an exit code. `SessionTracker::try_advance` and
`ShutdownHandle::shut_down_fatally` keep each protocol in one place.

```rust,ignore
// Bad
#[derive(Clone)]
pub struct ServiceState {
    pub registry: Arc<Mutex<HashMap<ExecutionManagerId, State>>>,
    pub latest_session_id: Arc<AtomicU64>,
    pub shutdown_token: CancellationToken,
}

let (runtime, token) = create_runtime(&config).await?;
token.cancel();
```

```rust,ignore
// Good
#[derive(Clone)]
pub struct Registry {
    inner: Arc<RegistryInner>,
}

impl Registry {
    pub fn register(&self, id: ExecutionManagerId, state: State) -> bool {
        let mut em_table = self.inner.em_table.write().expect("registry lock poisoned");
        em_table.insert(id, state).is_none()
    }
}

#[derive(Clone, Debug, Default)]
pub struct ShutdownHandle {
    token: CancellationToken,
    fatal: Arc<AtomicBool>,
}

impl ShutdownHandle {
    pub fn shut_down_fatally(&self) {
        self.fatal.store(true, Ordering::Release);
        self.token.cancel();
    }
}

struct RegistryInner {
    em_table: RwLock<HashMap<ExecutionManagerId, State>>,
}
```

**Review.**
- Flag `#[derive(Clone)]` on a state struct whose fields are several `Arc`s. Ask for one
  `Arc<Inner>`, and name the type callers hold after the domain concept. If the inner type has its
  own single-threaded `&mut self` API (as `TaskControlBlock` does), name the inner `Xxx` and the
  handle `SharedXxx`, lock once per public operation, and take locks in a fixed structural order
  (parent before child).
- Flag `Mutex<()>` or a lock field sitting beside the data it guards, and `Cell`, `RefCell` or
  `Mutex` in a `pub` field or signature. Put the data inside the lock and keep the cell private.
- Flag interior mutability on a type that is not actually shared. Use `&mut self` and plain fields.

**Exceptions.** A small handle that pairs two Arc-backed primitives that are always used together,
like `ShutdownHandle`'s token and fatal flag, does not need an extra `Arc<Inner>`. When several
handlers and a background loop all write the shared state and its invariants span several fields,
prefer a single owning actor (ASYNC-9).

**Sources.**

- [y-scope/spider#319](https://github.com/y-scope/spider/pull/319#discussion_r3204135606): one `Arc<ServiceStateInner>` instead of cloning six `Arc`s
- [y-scope/spider#365](https://github.com/y-scope/spider/pull/365#pullrequestreview-4602898177): reviewer adds an `inner` layer to the service state
- [y-scope/spider#360](https://github.com/y-scope/spider/pull/360): `ConnectionPool` is a cheaply cloneable `Arc`-backed handle
- [y-scope/spider#527](https://github.com/y-scope/spider/pull/527): `ShutdownHandle` replaces raw token use and records whether shutdown is fatal
- [y-scope/spider#290](https://github.com/y-scope/spider/pull/290): `SharedTaskControlBlock` wraps the single-threaded `TaskControlBlock`
- [y-scope/spider#309](https://github.com/y-scope/spider/pull/309#discussion_r3107874938): name the inner `XXX` and the `Arc` wrapper `SharedXXX`
- [y-scope/clp#1740](https://github.com/y-scope/clp/pull/1740#discussion_r2599395151): name the handle callers hold after the concept; inner gets `Inner`
- [spider `spider-core/src/session.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/session.rs#L13-L68): `SessionTracker::try_advance` keeps the monotonic CAS protocol in one place
- [spider `spider-utils/src/shutdown.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-utils/src/shutdown.rs#L9-L58): `ShutdownHandle` pairs token and fatal flag without an `Arc<Inner>`
- [RustTraining type-driven-correctness-book § Mutex Transforms !Sync into Sync](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch16-send-sync-compile-time-concurrency-proofs.html#mutex-transforms-sync-into-sync): data inside the `Mutex`, so the compiler forces locking
- [RustTraining c-cpp-book § Memory Management](https://microsoft.github.io/RustTraining/c-cpp-book/ch17-best-practices.html#memory-management): keep interior mutability out of public APIs

## OBJ-6: Expose domain operations, not the container or the call protocol

**Rule.** Make a collection or channel that several modules touch a struct with private fields and
methods named for domain operations. Fold an order-sensitive sequence of calls into one method with
private steps. Give each role its own handle that holds only the capabilities that role uses. When
correctness needs a single writer, make the writer non-`Clone` and give it `&mut self` methods.

**Why.** With `type SessionRegistry = DashMap<..>`, the rules about who may insert or remove a
session were spread over three files. Once it became a type, routing became a synchronous method
that can be unit-tested without a TCP connection. Spider's dispatch path had three ordering rules
that every call site had to follow (publish, then sample occupancy, then hint). Moving them into
`try_send` left one function body to review. A `NOTE: must not be called concurrently` on a `Clone`
writer with `&self` methods is enforced by nothing: the next clone handed to another task breaks
session consistency, and everything still compiles.

```rust,ignore
// Bad
pub(crate) type SessionRegistry = DashMap<SessionToken, Arc<State>>;

/// NOTE: `enqueue` and `bump_session_id` must not be called concurrently.
#[derive(Clone)]
pub struct DispatchQueueWriter {
    inner: Arc<DispatchQueueWriterInner>,
}

writer.sender().try_send(assignment)?;
if let Some(hint) = writer.try_make_hint() {
    writer.broadcast_sender().try_send(hint)?;
}
```

```rust,ignore
// Good
pub(crate) struct SessionRegistry {
    sessions: DashMap<SessionToken, Arc<State>>,
}

impl SessionRegistry {
    pub fn join(&self, handshake: &Handshake) -> Result<Connection, ConnectionError> { /* ... */ }
    fn unregister(&self, token: &SessionToken) { /* ... */ }
}

pub struct DispatchQueueWriter { /* ... */ }

impl DispatchQueueWriter {
    pub fn enqueue(&mut self, assignment: TaskAssignment) -> Result<(), SchedulerError> { /* ... */ }
    pub fn bump_session_id(&mut self, session_id: SessionId) { /* ... */ }
}

pub fn create_ready_queue(
    capacity: usize,
) -> (ReadyQueueSender, ReadyQueueReceiver, ReadyQueueResetter) { /* ... */ }
```

**Review.**
- Flag a type alias over a shared map or channel, and `pub` fields of shared state read from another
  module. Wrap them in a type with domain methods, and keep I/O out of those methods so they stay
  synchronous and testable.
- Flag docstrings that say "call X before Y" or "must not be called concurrently" on a `Clone` +
  `&self` type. Fold the sequence into one method, or make the type non-`Clone` with `&mut self`.
- Flag several handle types that all wrap the same all-owning `Inner`. Split the state so that each
  handle holds only what its role uses (TLC-2 applies the same idea to trait bounds).

**Exceptions.** This does not conflict with coding-style.md § Type Aliases for External Types: an
alias that renames an external value type (`pub type UuidBytes = uuid::Bytes`) is fine. The rule
targets aliases that name shared, mutable state.

**Sources.**

- [y-scope/clp#2689](https://github.com/y-scope/clp/pull/2689#discussion_r4507729225): make the registry a real type instead of a `DashMap` alias
- [y-scope/spider#449](https://github.com/y-scope/spider/pull/449): `try_send` folds three call-site ordering rules into one method
- [y-scope/spider#309](https://github.com/y-scope/spider/pull/309#discussion_r3107834514): each ready-queue handle should hold only what its role needs
- [y-scope/spider#443](https://github.com/y-scope/spider/pull/443): core owns a concrete `DispatchQueueWriter`; trait methods become inherent
- [spider `spider-scheduler/src/dispatch_queue.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/dispatch_queue.rs#L50-L106): counterexample: `Clone` writer whose NOTE forbids concurrent calls
- [spider `spider-scheduler/src/core_impl/resource_group_round_robin/dispatch_queue.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/core_impl/resource_group_round_robin/dispatch_queue.rs#L23-L81): non-`Clone` `RgDispatchQueueWriter` exposing only `try_send` and `queue_len`

## OBJ-7: Take required builder arguments up front and finish with a consuming `build(self)`

**Rule.** Pass required values to the builder's own constructor (`Type::builder(required)`), and
make optional settings consuming `#[must_use]` setters. `build(self)` is the only way to get the
target: it runs any mandatory finalization itself and keeps those steps private. A fallible `add`
validates its input before it changes any state (DEF-1).

**Why.** `CompressionInputBuilder` once had a public `flush(&mut self)` next to a consuming getter,
so a caller who forgot to flush silently lost every buffered object. Finishing a builder through
`impl From<Builder> for Vec<Manifest>` hides a real step, the final partition flush, behind syntax
that readers expect to be a plain conversion. A builder that takes required fields as `Option`s
turns a mistake the compiler could catch into a runtime error ("endpoint required"). Positional
constructors break every caller each time a setting is added.

```rust,ignore
// Bad
impl InputBuilder {
    pub fn add(&mut self, object: ObjectMetadata) { self.buffer.push(object); }
    pub fn flush(&mut self) { /* emits the last partition */ }
    pub fn into_inputs(self) -> Vec<Input> { self.inputs }
}

impl From<InputBuilder> for Vec<Input> { /* flushes, then converts */ }

let client = SpiderClient::builder().max_retries(10).connect().await?;
```

```rust,ignore
// Good
impl InputBuilder {
    pub fn add(&mut self, object: ObjectMetadata) -> Result<(), Error> {
        if object.bucket != self.bucket {
            return Err(Error::S3BucketMismatch(object.bucket));
        }
        self.buffer.push(FileMetadata::new(object.key, object.size));
        Ok(())
    }

    #[must_use]
    pub fn build(mut self) -> Vec<Input> {
        self.flush();
        self.inputs
    }

    fn flush(&mut self) { /* ... */ }
}

let client = SpiderClient::builder(endpoint).max_retries(10).connect().await?;
```

**Review.**
- Flag a public `flush` or `finalize` next to a consuming getter, a `From`/`Into` impl that runs a
  processing step, and a `build()` that returns `Err("x is required")`.
- Flag an `add` that mutates state before it validates, so a rejected item leaves a partial trace.
- Flag a positional constructor that keeps gaining optional arguments, and switch it to a builder.
  If it has many *required* arguments, use a `pub` params struct (as Spider's `ServiceStateParams`
  does) and destructure it in the constructor with no `..`, so that a new field fails to compile
  until it is wired in. The same exhaustive `let Config { a, b, c } = config;` applies to any
  factory that consumes a config.

**Exceptions.** If a public builder has three or more required fields and leaving one out would
silently produce an incomplete value, a typestate builder (`Builder<Missing>` → `Builder<Set<T>>`,
with `build` only on the fully set state) is worth its extra type parameters (TLC-9). For one or
two required fields, constructor arguments are enough.

See also: coding-style.md § Take ownership when the value mustn't be used afterwards.

**Sources.**

- [y-scope/clp#2403](https://github.com/y-scope/clp/pull/2403#pullrequestreview-4739365794): `flush` made private; `add` validates the bucket before mutating
- [y-scope/clp#2620](https://github.com/y-scope/clp/pull/2620#discussion_r4414143465): finish a builder with `build`, not `Vec::from(builder)`
- [y-scope/spider#396](https://github.com/y-scope/spider/pull/396): `SpiderClient::builder(endpoint)` with consuming setters replaces positional `connect`
- [y-scope/spider#374](https://github.com/y-scope/spider/pull/374): `ServiceStateParams` bundles required arguments; `new` destructures it
- [spider `spider-scheduler/src/runtime.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/runtime.rs#L109-L164): `create_runtime` destructures `RuntimeConfig` exhaustively
- [spider `spider-storage/src/state/service/state.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/state/service/state.rs#L72-L164): `ServiceStateParams`, destructured with no `..` in `ServiceState::new`
- [RustTraining type-driven-correctness-book § Typestate Builder](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch11-fourteen-tricks-from-the-trenches.html#trick-4--typestate-builder): `build` exists only once every required field is set
- [RustTraining csharp-book § Builder Pattern Implementation](https://microsoft.github.io/RustTraining/csharp-book/ch05-1-constructor-patterns.html#builder-pattern-implementation): consuming setters; its `build` returns `Err("Host is required")`, the flagged shape

## OBJ-8: Name methods for their contract

**Rule.** Use prefixes in their std sense: `as_` for a cheap borrowed view, `to_` for a new owned
value made from `&self`, `into_` for a method that consumes `self`, `try_` for the fallible form of
an operation, `expect_`/`unwrap_` only for methods that panic, `check_`/`validate_` for methods that
return `Result`, and `is_`/`has_` for `bool`. A method that mutates is not named `compute_`, `get_`
or `check_`, and a bulk operation has a plural name that states its selection. For plain getters,
follow the crate's existing convention.

**Why.** Reviewers judge control flow and blast radius from names. `expect_num_fields` returned
`Err`, so it looked like a panic path and was reviewed as one. A `cancel` that only records a
request leads callers to assume the job has stopped. A `compute_dependencies` that also updated the
graph invites a second call, or a call from a read-only path. A bare `delete_all` gets called where
a single-row delete was meant. When reviewers tried to give `reset_non_terminated_jobs` a precise
name, they found it had no behavior worth defining, and it was removed.

```rust,ignore
// Bad
fn expect_num_fields(actual: u32, expected: u32) -> Result<(), DecodeError>;
async fn cancel(&self, job_id: QueryJobId) -> Result<(), DbError>;
fn compute_dependencies(&mut self, inputs: &[TaskInput]) -> Vec<TaskIndex>;
async fn delete_all(&self, expire_after_sec: u64) -> Result<u64, DbError>;
```

```rust,ignore
// Good
fn check_num_fields(actual: u32, expected: u32) -> Result<(), DecodeError>;
async fn request_cancellation(&self, job_id: QueryJobId) -> Result<(), DbError>;
fn compute_and_update_dependencies_from_inputs(&mut self, inputs: &[TaskInput]) -> Vec<TaskIndex>;
async fn delete_expired_terminated_jobs(&self, expire_after_sec: u64) -> Result<u64, DbError>;
```

**Review.**
- Read each new or changed method name against its body. Does `expect_` panic? Does `get_` or
  `compute_` write? Does `cancel` cancel? Does `into_` consume `self`? Does `finish_` finish
  something that has started (if not, rename it, e.g. to `run_compression`)?
- If a method's semantics cannot be stated in one accurate name, question whether the method should
  exist.

See also: coding-style.md § Rename a function once its behaviour narrows.

**Sources.**

- [y-scope/clp#2649](https://github.com/y-scope/clp/pull/2649#discussion_r4438359900): rename `expect_num_fields` to `check_num_fields`; `expect` implies a panic
- [y-scope/clp#2617](https://github.com/y-scope/clp/pull/2617#discussion_r4389439608): rename `cancel` to `request_cancellation`
- [y-scope/clp#2646](https://github.com/y-scope/clp/pull/2646#discussion_r4438244070): a `finish_*` that starts the work should be `run_compression`
- [y-scope/spider#280](https://github.com/y-scope/spider/pull/280#discussion_r2726264860): `compute` is misleading for a method that mutates the graph
- [y-scope/spider#286](https://github.com/y-scope/spider/pull/286#discussion_r2947525390): replace `delete_all` with `delete_expired_terminated_jobs`
- [y-scope/spider#286](https://github.com/y-scope/spider/pull/286#discussion_r2947548467): naming `reset_non_terminated_jobs` showed it does nothing; removed

## OBJ-9: Convert through the std traits

**Rule.** Parse text with `FromStr`, so callers write `raw.parse::<T>()`. Convert between domain,
wire and DB types with `From` when the conversion cannot fail, and with `TryFrom` (with the crate's
error enum as `type Error`) when it can. Do not add an inherent `parse_str`, free `a_to_b`
functions, or a homegrown conversion trait.

**Why.** Std conversions compose with `?`, `.into()`, `.map(B::from)`, serde's `try_from`/`into` and
sqlx `Decode`, and readers know their contract without opening the body. Spider's `ResponseUnpack`
trait was "literally `TryFrom`" with a `String` error: it added no guarantee and lost the typed
error. Free converters like `storage_error_to_liveness_error` get rewritten in every client and
drift apart. Reviewers removed the same pattern in two consecutive PRs, and `ArchiveId::parse_str`
became `impl FromStr for ArchiveId`.

```rust,ignore
// Bad
impl ArchiveId {
    pub fn parse_str(value: &str) -> Result<Self, ParseArchiveIdError> { /* ... */ }
}

pub trait ResponseUnpack {
    type Unpacked;
    fn unpack(self) -> Result<Self::Unpacked, String>;
}

fn storage_error_to_client_error(error: proto::StorageError) -> ClientError { /* ... */ }
```

```rust,ignore
// Good
impl FromStr for ArchiveId {
    type Err = ParseArchiveIdError;

    fn from_str(value: &str) -> Result<Self, Self::Err> { /* ... */ }
}

impl From<proto::StorageError> for ClientError {
    fn from(error: proto::StorageError) -> Self { /* ... */ }
}

impl TryFrom<proto::Response> for proto::Payload {
    type Error = ClientError;

    fn try_from(response: proto::Response) -> Result<Self, Self::Error> {
        match response.result {
            Some(proto::ResponseResult::Payload(payload)) => Ok(payload),
            Some(proto::ResponseResult::Error(error)) => Err(error.into()),
            None => Err(ClientError::EmptyResponse),
        }
    }
}

let archive_id: ArchiveId = raw.parse()?;
```

**Review.**
- Flag `fn parse_str`, `fn a_to_b(a: A) -> B`, and single-method traits that reimplement `TryFrom`,
  and replace them with the std trait. Clippy's `should_implement_trait` only catches an inherent
  method literally named `from_str`, so a review has to catch the rest. Prefer `FromStr` to
  `TryFrom<&str>` for parsing, since only `FromStr` enables `str::parse`.
- Flag field-by-field mapping inlined at a call site (e.g. building `SearchJobConfig` from a
  `QueryConfig` inside a client). Move it into a `From` impl, kept in the crate that owns the wire
  types (MOD-4).

**Exceptions.** A conversion that needs extra context (a second argument) or has side effects is a
named method or factory, not `From` (see OBJ-7). `TryFrom<String>` is fine when
`#[serde(try_from = "String")]` needs it, as long as it delegates to `from_str`.

See also: coding-style.md § What deserves a unit test (hand-written `From`/`TryFrom` impls that map
fields are tested).

**Sources.**

- [y-scope/clp#2531](https://github.com/y-scope/clp/pull/2531#discussion_r4075373368): `parse_str` misleads; use `from_str` or `TryFrom`
- [y-scope/clp#2550](https://github.com/y-scope/clp/pull/2550): replaces `ArchiveId`'s `TryFrom<&str>` with `FromStr`
- [y-scope/clp#2581](https://github.com/y-scope/clp/pull/2581#discussion_r4332827673): move call-site field mapping into `From<QueryConfig> for SearchJobConfig`
- [y-scope/spider#340](https://github.com/y-scope/spider/pull/340#pullrequestreview-4489303309): replace `storage_error_to_liveness_error` with an `impl From`
- [y-scope/spider#342](https://github.com/y-scope/spider/pull/342#discussion_r3478695903): the `ResponseUnpack` trait is literally `TryFrom`
- [y-scope/spider#342](https://github.com/y-scope/spider/pull/342#discussion_r3482583018): use the crate's error enum, not `String` errors
- [clp `clp-rust-libs/clp-rust-utils/src/types.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/clp-rust-utils/src/types.rs#L23-L44): `impl FromStr for ArchiveId`

## OBJ-10: Derive std traits when they are needed and when they mean the right thing

**Rule.** Derive a trait when a concrete caller needs it, and remove it once the last user is gone.
Before deriving, check what the trait means for this type: no `Clone`/`Copy` on single-use values or
unique handles, `Default` only when the default value is valid, and `PartialOrd`/`Ord` on an enum
only when declaration order is the real order, stated in the docstring. Hand-write `Debug` for types
carrying bulky or sensitive payloads, and otherwise prefer a derive to a hand-written equivalent.

**Why.** Every derive is API. One `#[derive(Clone)]` lets a caller duplicate a commit token and use
it twice (TLC-4), and removing `Clone` later is a breaking change. With a derived `Ord`,
alphabetizing the variants silently flips every `>=` severity check. `Default` on a type whose empty
value is invalid lets `..Default::default()` build broken values. A derived `Debug` on an event that
carries megabytes of task outputs floods the logs every time it is logged with `?`. In the other
direction, a hand-written `Clone` that only does what the derive would do falls out of date when
fields are added.

```rust,ignore
// Bad
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Severity {
    Info,
    Critical,
    Warning,
}

#[derive(Clone)]
pub struct CommitToken {
    txn_id: u64,
}

#[derive(Debug)]
pub enum TreeEventKind {
    RegularTasksDone { outputs: Vec<TaskOutput> },
}
```

```rust,ignore
// Good
/// Variants are declared in increasing severity; the derived `Ord` relies on this order.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Severity {
    Info,
    Warning,
    Critical,
}

pub struct CommitToken {
    txn_id: u64,
}

impl std::fmt::Debug for TreeEventKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::RegularTasksDone { outputs } => f
                .debug_struct("RegularTasksDone")
                .field("num_outputs", &outputs.len())
                .finish(),
        }
    }
}
```

**Review.**
- Flag derives with no user in the diff (bots often suggest `Debug, Clone, PartialEq, Eq` up front;
  the team's answer in
  [y-scope/spider#272](https://github.com/y-scope/spider/pull/272#discussion_r2702772149) was "add
  it in future PRs on demand"), and derives such as `strum::EnumIter` whose last user was removed.
- Flag `Clone` on guards, tokens and single-writer handles, `Ord` on an enum with no stated order,
  `Default` for connections, handles, or configs with required fields, and a derived `Debug` on
  payload-carrying types that get logged.
- Flag a manual impl that matches the derive. Keep it, with a short *why* comment, only if the
  derive would add bounds the fields don't need (e.g. `T: Clone` on a struct that only holds
  `Arc<..T..>`; TLC-1 shows the same trap for phantom markers).

**Exceptions.** `Debug` is needed by almost every type that is logged, used as an error, or passed
through `expect`, so deriving it on such types needs no further justification. The on-demand rule is
aimed at `Clone`, `Copy`, `PartialEq`/`Eq`, `Hash`, `PartialOrd`/`Ord`, `Default` and
`Serialize`/`Deserialize`.

See also: pr-review.md § Trait surface minimization (the same "only what callers use" logic, applied
to traits).

**Sources.**

- [y-scope/spider#272](https://github.com/y-scope/spider/pull/272#discussion_r2702772149): bot-suggested derives declined: "add it in future PRs on demand"
- [y-scope/spider#285](https://github.com/y-scope/spider/pull/285#discussion_r2972593594): derive the enum's MySQL string support instead of hard-coding `'Ready'`
- [y-scope/spider#290](https://github.com/y-scope/spider/pull/290): derives `Debug`/`Clone`/`Eq`/`PartialEq` on `TaskState` when the cache needs them
- [y-scope/spider#341](https://github.com/y-scope/spider/pull/341#pullrequestreview-4493746031): derive `Clone` instead of implementing it by hand
- [spider `spider-storage/src/cache/tree/event.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/cache/tree/event.rs#L91-L111): hand-written `Debug` logs output counts instead of payloads
- [RustTraining type-driven-correctness-book § Move Semantics as Linear Types](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch03-single-use-types-cryptographic-guarantee.html#move-semantics-as-linear-types): single-use values are deliberately neither `Clone` nor `Copy`
- [RustTraining c-cpp-book § When NOT to Implement Traits](https://microsoft.github.io/RustTraining/c-cpp-book/ch17-best-practices.html#when-not-to-implement-traits): no `Default` for handles or connections, no `Copy` on heap data

# Ownership, borrowing and performance

Ownership in a signature is a promise. A parameter taken by value says the callee keeps the value or
sends it onward, a borrow says the callee only reads it, and a returned reference lets the caller
decide whether to copy. When signatures match what the code actually does, needless clones go away
without any tuning, and the allocations that remain are the ones the design needs. Both repositories
deny clippy's `pedantic` and `nursery` groups, which already catch part of this (`ptr_arg`,
`needless_pass_by_value` on sync functions, `needless_collect`, `map_clone`), so the rules below
build on coding-style.md § Ownership and Efficiency and concentrate on what clippy misses: async and
trait signatures, return types, closures that produce futures, and the shape of data structures.

## OWN-1: Take ownership exactly where the value must outlive the call

**Rule.** Borrow (`&T`, `&[T]`, `&str`) when the callee only uses the value before it returns,
including an `async fn` the caller awaits. Take it by value when the callee stores it, moves it into
a spawned task, sends it through a channel, or returns it; public constructors that store a string
or path may take `impl Into<String>` / `impl Into<PathBuf>`.

**Why.** Ownership taken "just in case" makes every caller clone to keep its copy, and a borrow that
the callee then copies into a channel does the same from the other side; either way one piece of
data is allocated twice. The deciding question is not how big the value is but whether it has to
outlive the call: registering a job only reads the task graph, so it borrows, while the ready queue
forwards indices through a channel, so it takes the `Vec` and moves it. Clippy's
`needless_pass_by_value` flags a sync function that only reads a by-value parameter, but it skips
`async fn`s and trait methods, which is exactly where storage and scheduler APIs live, so review has
to catch those.

```rust,ignore
// Bad
#[async_trait]
pub trait JobStore {
    async fn register(&self, task_graph: TaskGraph) -> Result<JobId, DbError>;
}

pub async fn send_ready(
    sender: &Sender<Vec<TaskIndex>>,
    task_indices: &[TaskIndex],
) -> Result<(), QueueError> {
    sender.send(task_indices.to_vec()).await.map_err(|_| QueueError::Closed)
}
```

```rust,ignore
// Good
#[async_trait]
pub trait JobStore {
    async fn register(&self, task_graph: &TaskGraph) -> Result<JobId, DbError>;
}

pub async fn send_ready(
    sender: &Sender<Vec<TaskIndex>>,
    task_indices: Vec<TaskIndex>,
) -> Result<(), QueueError> {
    sender.send(task_indices).await.map_err(|_| QueueError::Closed)
}

impl ValueTypeDescriptor {
    pub fn struct_from_name(name: impl Into<String>) -> Result<Self, Error> {
        let name = NonEmptyString::new(name.into()).map_err(|_| Error::InvalidStructName)?;
        Ok(Self::Struct(name))
    }
}
```

**Review.**
- For each by-value parameter of an `async fn` or a trait method, check that the body moves it into
  a field, a `spawn`, a `send`, or the return value. If the body only reads it, ask for `&T`.
- For each borrowed parameter, look for `.to_vec()`, `.clone()` or `.to_owned()` whose result is
  then stored or sent, and ask for ownership instead (see also: coding-style.md § Pass ownership
  instead of borrowing when the callee needs owned data).

**Exceptions.** Keep private and crate-internal helpers concrete (`String`, `&str`). Use
`impl Into<..>` only on public entry points, where it saves a `.to_owned()` at every call site; in
internal code each extra generic costs compile time and can break type inference at call sites.

See also: pr-review.md § Conversely: don't take ownership when a reference suffices, pr-review.md §
Prefer references over `Arc`/`Vec` when ownership isn't needed.

**Sources.**

- [y-scope/spider#292](https://github.com/y-scope/spider/pull/292#discussion_r3035019529): reviewer asks for `&TaskGraph`, since registration never runs detached
- [y-scope/spider#293](https://github.com/y-scope/spider/pull/293#discussion_r3024970704): ready queue takes the `Vec` to send it without a copy
- [y-scope/spider#310](https://github.com/y-scope/spider/pull/310#discussion_r3107608498): reviewer questions taking ownership of a record that is only read
- [spider `spider-core/src/task/type_descriptor.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/task/type_descriptor.rs#L172-L187): `struct_from_name` takes `impl Into<String>` and stores it
- [RustTraining rust-patterns-book § Quick Reference: Which to Use](https://microsoft.github.io/RustTraining/rust-patterns-book/ch15-crate-architecture-and-api-design.html#quick-reference-which-to-use): own via `impl Into<T>` when storing, borrow when only reading

## OWN-2: Expose the borrowed view, not the container

**Rule.** In parameters and return types, use the borrowed form of the inner type: `&[T]` instead of
`&Vec<T>`, `&str` instead of `&String`, and `Option<&T>` / `Option<&str>` / `Option<&[T]>` instead
of `&Option<T>`. A getter returns a borrow of a non-`Copy` field, never a clone of it.

**Why.** A `-> &Vec<T>` return makes the storage type part of the API: switching later to `Box<[T]>`
or a `SmallVec` breaks every caller, and callers gain nothing over a slice. A
`&Option<NonEmptyString>` parameter only accepts callers that already hold that exact `Option`, so a
caller with a plain `&str` or a literal has to build one first, and the callee goes through an extra
indirection to reach the bytes. A getter that returns `self.items.clone()` looks free at the call
site but copies O(n) data on every call. Clippy covers only part of this: `ptr_arg` rejects
`&Vec`/`&String` parameters and `ref_option` rejects `&Option<T>` parameters of private functions,
but neither checks return types or `&Option<T>` parameters of `pub` functions.

```rust,ignore
// Bad
impl Task {
    pub const fn get_parent_indices(&self) -> &Vec<TaskIndex> {
        &self.parent_indices
    }

    pub fn get_outputs(&self) -> Vec<TaskOutput> {
        self.outputs.clone()
    }
}

pub fn build_args(dataset: &Option<NonEmptyString>, archive_id: &NonEmptyString) -> Vec<String>;
```

```rust,ignore
// Good
impl Task {
    pub const fn get_parent_indices(&self) -> &[TaskIndex] {
        self.parent_indices.as_slice()
    }

    pub fn get_outputs(&self) -> &[TaskOutput] {
        &self.outputs
    }

    pub fn get_label(&self) -> Option<&str> {
        self.label.as_deref()
    }
}

pub fn build_args(dataset: Option<&str>, archive_id: &str) -> Vec<String>;

let args = build_args(dataset.as_ref().map(NonEmptyString::as_str), archive_id.as_str());
```

**Review.**
- Search the diff for `-> &Vec<`, `-> &String`, `-> &Option<`, `: &Option<` on `pub` functions, and
  getters whose body ends in `.clone()`. Each has a direct borrowed replacement: `.as_slice()`,
  `.as_str()`, `.as_ref()`, `.as_deref()`.
- For a computed collection that callers only iterate, such as `.flat_map(|task|
  task.input_dep_indices.clone()).collect()`, suggest returning `impl Iterator<Item = T> + '_` for
  `Copy` items (or `Item = &T` otherwise) instead of a fresh `Vec`.

**Exceptions.** Return an owned value when the getter computes it, or when the field is `Copy` or a
cheap handle (`Arc`, a tonic client, a sqlx pool) that the caller is meant to keep.

See also: coding-style.md § Use `&str` for read-only string access.

**Sources.**

- [y-scope/clp#2512](https://github.com/y-scope/clp/pull/2512#discussion_r3982795813): reviewer explains why `Option<&str>` beats `&Option<NonEmptyString>` as a parameter
- [spider `spider-core/src/task/task_graph.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/task/task_graph.rs#L238-L241): `get_parent_indices` still returns `&Vec<TaskIndex>`
- [spider `spider-core/src/task/task_graph.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/task/task_graph.rs#L598-L609): `get_task_graph_input_indices` clones per task into a fresh `Vec`
- [RustTraining csharp-book § Deref Coercion: Automatic Smart Pointer Unwrapping](https://microsoft.github.io/RustTraining/csharp-book/ch07-3-smart-pointers-beyond-single-ownership.html#deref-coercion-automatic-smart-pointer-unwrapping): why APIs take `&str`/`&[T]` rather than `&String`/`&Vec<T>`

## OWN-3: Consume at-most-once state with `Option::take` and `std::mem::take`/`replace`

**Rule.** When a value must be used at most once from inside a loop, or a buffer must be handed off
and left empty, move it out with `Option::take()`, `std::mem::take`, or `std::mem::replace` (for a
type without a `Default`). Do not copy or clone it, and do not keep a separate "already sent" flag.

**Why.** Spider's execution manager long-polls the scheduler in a loop and reports the previous
assignment in each request. Because the record is `Copy`, `prev_assignment.map(Into::into)` compiled
happily and re-sent the same completed assignment on every iteration; the scheduler had already
dropped it, so an idle execution manager logged a warning on every poll (151 MB of logs in one
session). With `take()`, the first iteration sends `Some` and every later one sends `None`, so
"first iteration only" holds by construction. `Copy` and `Clone` are exactly what let the compiler
accept the reuse, so they are the types to watch. Draining with `mem::take` hands off the whole
buffer without a copy and leaves a valid empty value behind, so `&mut self` stays usable.

```rust,ignore
// Bad
loop {
    let request = NextTaskRequest {
        prev_assignment: prev_assignment.map(Into::into),
    };
    if let Some(assignment) = self.poll(request).await? {
        return Ok(assignment);
    }
}
```

```rust,ignore
// Good
loop {
    let request = NextTaskRequest {
        prev_assignment: prev_assignment.take().map(Into::into),
    };
    if let Some(assignment) = self.poll(request).await? {
        return Ok(assignment);
    }
}

pub(super) fn take_ready_tasks(&mut self) -> VecDeque<TaskIndex> {
    std::mem::take(&mut self.ready_task_queue)
}
```

**Review.**
- In every loop, look for a loop-carried `Option` or buffer that is read on each iteration but
  semantically consumed once, whether by `.clone()`, by copying a `Copy` value, or through a `bool`
  "already sent" flag. Replace it with `take()`.
- Flag `let v = self.buf.clone(); self.buf.clear();` (clippy does not), and ask for
  `std::mem::take(&mut self.buf)`.

**Exceptions.** When the whole value, not one field, is dead after the call, take `self` by value
instead (see also: coding-style.md § Take ownership when the value mustn't be used afterwards, which
also covers `take()` inside `Drop` types).

**Sources.**

- [y-scope/spider#430](https://github.com/y-scope/spider/pull/430): fix uses `Option::take` to send `prev_assignment` at most once
- [y-scope/spider#429](https://github.com/y-scope/spider/issues/429): bug report: the `Copy` record is re-sent on every long-poll iteration
- [spider `spider-execution-manager/src/client/grpc/scheduler.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/client/grpc/scheduler.rs#L55-L84): `next_task` long-poll loop with `prev_assignment.take()`
- [spider `spider-scheduler/src/core_impl/resource_group_round_robin/job_registry.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/core_impl/resource_group_round_robin/job_registry.rs#L70-L77): `take_ready_tasks` drains the queue with `std::mem::take`
- [spider `spider-scheduler/src/core_impl/resource_group_round_robin/scheduling_state.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/core_impl/resource_group_round_robin/scheduling_state.rs#L206-L223): `apply_downgrades` drains both buffers with `std::mem::take`

## OWN-4: Make a future-producing closure return an owned `async move` future

**Rule.** A closure that the callee calls repeatedly to produce futures (retry, polling) clones its
handles in, builds its request inside the closure, and returns an `async move { .. }` block that
owns everything it uses. A helper that needs those futures to be `Send` bounds the closure as
`FnMut() -> FutureType` with `FutureType: Future<Output = ..> + Send`, not as `AsyncFnMut`.

**Why.** Spider's retry helper was bounded by `AsyncFnMut() -> Result<..>`, and callers passed
`async || { self.pool.get_client().start_job(request.clone()).await }`. An `AsyncFnMut` bound cannot
name the future it returns, so the helper could not require that future to be `Send`, and the
compiler could not prove it `Send` for every lifetime of the borrowed `self`. Every public client
method built on the helper failed `Send` with "implementation of `Send` is not general enough", so
callers could not `tokio::spawn` them. Splitting the bound into a closure type and a future type
lets the helper state `FutureType: Send`, and a closure that builds a fresh client and request for
each call makes every attempt independent, with no state shared between attempts.

```rust,ignore
// Bad
pub async fn call_with_retry<
    ResponseType,
    GrpcCall: AsyncFnMut() -> Result<ResponseType, Status>,
>(retry_config: RetryConfig, grpc_call: GrpcCall) -> Result<ResponseType, Status>;

call_with_retry(self.retry_config, async || {
    let request = JobIdRequest { job_id: job_id.get() };
    self.pool.get_client().start_job(request).await
})
.await
```

```rust,ignore
// Good
pub async fn call_with_retry<
    ResponseType,
    GrpcCall: FnMut() -> FutureType,
    FutureType: Future<Output = Result<ResponseType, Status>> + Send,
>(retry_config: RetryConfig, grpc_call: GrpcCall) -> Result<ResponseType, Status>;

let pool = self.pool.clone();
call_with_retry(self.retry_config, move || {
    let mut client = pool.get_client();
    let request = JobIdRequest { job_id: job_id.get() };
    async move { client.start_job(request).await }
})
.await
```

**Review.**
- In retry and poll closures, check that the returned future is `async move` and owns its inputs,
  and that the helper's bound states `Send` on the future when callers spawn it. For a public client
  crate's async API, ask for a compile-time `Send` assertion on its futures, as spider-client does
  (ASYNC-10). Shared counters in such closures, including in tests, must be `Sync` (`AtomicUsize`,
  not `Cell<usize>`).
- Compare each callback bound with how the body calls it: `FnOnce` if called once, `FnMut` if called
  repeatedly in sequence, `Fn` only for shared or concurrent calls, and `Send + 'static` only when
  the closure is spawned or stored. A stronger bound rejects valid closures and forces callers into
  `Arc`.

**Exceptions.** Async callbacks that run in place and whose futures are never spawned may take
`AsyncFnMut` ([y-scope/clp#2224](https://github.com/y-scope/clp/pull/2224#discussion_r3144410113);
see ASYNC-10).

See also: SRV-5 (what a retry helper must classify and bound).

**Sources.**

- [y-scope/spider#404](https://github.com/y-scope/spider/pull/404): `AsyncFnMut` futures can't be bound `Send`; split into closure and future types
- [spider `spider-utils/src/grpc/retry.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-utils/src/grpc/retry.rs#L107-L122): `call_with_retry` bounds `FnMut() -> FutureType` with `FutureType: Send`
- [spider `spider-client/src/grpc/job.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-client/src/grpc/job.rs#L120-L134): `start_job` closure clones the pool and returns an `async move` block
- [spider `spider-client/src/client.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-client/src/client.rs#L326-L349): `assert_client_futures_send` checks every public future is `Send`
- [RustTraining rust-patterns-book § Fn, FnMut, FnOnce — The Closure Traits](https://microsoft.github.io/RustTraining/rust-patterns-book/ch07-closures-and-higher-order-functions.html#fn-fnmut-fnonce--the-closure-traits): which closure trait a callback bound should require

## OWN-5: Keep per-item hot paths borrowed and allocation-free in the common case

**Rule.** Trait methods called once per record (encode, write, visit) take the record's parts as
borrowed primitives (`timestamp_millisecs: i64, message: &str`), not an owned struct, and values
that are constant per instance go to the constructor once. A transform that usually returns its
input unchanged returns `Cow<'_, str>`.

**Why.** An `encode(result: QueryResult)` that owns a `message: String` forces an allocation and a
copy per result before the encoder even reads it, and it passes per-connection constants such as the
archive ID on every call. Taking `&str` lets an implementer encode straight from the decode buffer
and lets the one implementation that needs ownership pay for it alone. In the same way, a normalizer
that returns `String` allocates on every log line even when nothing changed; `Cow` makes the
unchanged case free and still derefs to `&str`. The listener's own `read_str` does this, borrowing
valid UTF-8 from the frame and allocating only for a lossy repair (BND-7).

```rust,ignore
// Bad
pub trait ResultEncoder {
    type Error: std::error::Error;

    fn encode(&mut self, result: QueryResult) -> Result<(), Self::Error>;
}

fn normalize_key(key: &str) -> String {
    key.replace('.', "_")
}
```

```rust,ignore
// Good
pub trait ResultEncoder: Sized {
    type Error: std::error::Error;

    fn new(archive_id: ArchiveId) -> Result<Self, Self::Error>;

    fn encode(&mut self, timestamp_millisecs: i64, message: &str) -> Result<(), Self::Error>;
}

fn normalize_key(key: &str) -> Cow<'_, str> {
    if key.contains('.') {
        Cow::Owned(key.replace('.', "_"))
    } else {
        Cow::Borrowed(key)
    }
}
```

**Review.**
- On per-item paths, flag owned `String`/`Vec` parameters that most implementations only read, and
  arguments that are identical on every call for one instance.
- Flag `-> String` functions where most paths return `input.to_owned()` and suggest `Cow`. If every
  path allocates, `String` is correct; if no path does, return `&str`.

**Exceptions.** Outside hot paths (config loading, one-off setup), a plain `String` return is fine;
don't spread `Cow` through APIs where it buys nothing.

**Sources.**

- [y-scope/clp#2664](https://github.com/y-scope/clp/pull/2664#discussion_r4474408651): reviewer proposes `encode(timestamp_millisecs, message: &str)` to encode from the buffer
- [y-scope/clp#2690](https://github.com/y-scope/clp/pull/2690): SSE encoder builds the per-connection prefix, including archive ID, once
- [clp `clp-rust-libs/query-result-listener/src/encoding.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/query-result-listener/src/encoding.rs#L21-L67): `ResultEncoder` takes the archive ID in `new`, borrowed parts in `encode`
- [clp `clp-rust-libs/query-result-listener/src/protocol.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/query-result-listener/src/protocol.rs#L284-L318): `read_str` returns `Cow`, allocating only for a lossy UTF-8 repair
- [RustTraining c-cpp-book § When to use `Cow`](https://microsoft.github.io/RustTraining/c-cpp-book/ch17-1-avoiding-excessive-clone.html#when-to-use-cow): `Cow` when input usually passes unchanged; `String` or `&str` otherwise

## OWN-6: Don't force `Arc` on callers; make shared ownership opt-in

**Rule.** Generic APIs take the abstraction by value with a `Clone` bound (`LivenessClientType:
LivenessClient + Clone + 'static`), not as `Arc<LivenessClientType>`. When some callers need shared
ownership, add a forwarding `impl<LivenessClientType: LivenessClient + ?Sized> LivenessClient for
Arc<LivenessClientType>`.

**Why.** `Arc<ClientType>` in a signature makes an ownership choice for every caller, and it
double-wraps types that are already cheap `Arc`-backed handles, such as tonic clients and sqlx
pools. With a by-value `Clone` bound, the common case stays a plain value; a test that needs to keep
its own handle on a mock still passes `Arc<Mock>`, because the forwarding impl makes `Arc` satisfy
the bound. Spider's execution manager moved from the first shape to the second when it gained a real
gRPC liveness client.

```rust,ignore
// Bad
pub fn spawn<LivenessClientType: LivenessClient + 'static>(
    client: Arc<LivenessClientType>,
) -> LivenessHandle;
```

```rust,ignore
// Good
pub fn spawn<LivenessClientType: LivenessClient + Clone + 'static>(
    client: LivenessClientType,
) -> LivenessHandle;

#[async_trait]
impl<LivenessClientType: LivenessClient + ?Sized> LivenessClient for Arc<LivenessClientType> {
    async fn heartbeat(
        &self,
        em_id: ExecutionManagerId,
    ) -> Result<SessionId, LivenessResponseError> {
        (**self).heartbeat(em_id).await
    }
}
```

**Review.**
- Flag `Arc<SomeTypeParam>` in public generic signatures and fields. Suggest a by-value `Clone`
  bound and, if a caller needs sharing, the forwarding impl.
- Flag `Arc::new(client)` where `client` is already a cheap `Clone` handle.

See also: pr-review.md § Prefer references over `Arc`/`Vec` when ownership isn't needed, TLC-8 (when
a blanket or forwarding impl is appropriate).

**Sources.**

- [y-scope/spider#362](https://github.com/y-scope/spider/pull/362): drops the forced `Arc` from the liveness API; adds forwarding impl
- [spider `spider-execution-manager/src/client/liveness.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/client/liveness.rs#L99-L115): forwarding `impl LivenessClient for Arc<LivenessClientType>`
- [spider `spider-execution-manager/src/runtime.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/runtime.rs#L145-L234): `Runtime::create` takes the liveness client by value with a `Clone` bound

## OWN-7: Treat a clone that silences the borrow checker as a design smell

**Rule.** Before adding `.clone()` to fix a borrow error, try, in order: make the callee take `&T`,
borrow the fields directly (or destructure `self`) instead of calling a `&mut self` method that
borrows the whole struct, end the conflicting borrow earlier with a block, or split the struct so
the two borrows touch different fields. Clone only when the copy is part of the design.

**Why.** A clone added to quiet the compiler hides an ownership question nobody answered. In a loop
it costs an allocation per iteration, and worse, it can split the source of truth into two copies of
state that are then updated separately and drift apart. Most such conflicts come from a `&mut self`
helper: the call borrows all of `self`, while borrowing `self.logger` and `self.config` separately
lets the compiler see that they are disjoint. Clones that are part of the design look different: an
`Arc` or cheap client handle (O(1)), owned data moved into a spawned task, or an owned value
returned because the caller needs one.

```rust,ignore
// Bad
fn report(&mut self) {
    let name = self.config.name.clone();
    self.log(&name);
}
```

```rust,ignore
// Good
fn report(&mut self) {
    self.logger.log(&self.config.name);
}
```

**Review.**
- For each new `.clone()` of a value that is neither `Copy` nor a cheap handle, ask what would break
  without it. If the answer is "the borrow checker", ask for one of the restructurings above.
- Clippy already rejects mechanical clones (`redundant_clone`, `clone_on_copy`, `map_clone`); spend
  review attention on clones that create a second copy of mutable state that is later updated on its
  own.

See also: pr-review.md § Conversely: don't take ownership when a reference suffices.

**Sources.**

- [RustTraining c-cpp-book § Checklist: Should I clone?](https://microsoft.github.io/RustTraining/c-cpp-book/ch17-1-avoiding-excessive-clone.html#checklist-should-i-clone): borrow or restructure first; clone for `Arc`, threads, closures
- [RustTraining c-cpp-book § Case Study 4: God object → Composable state](https://microsoft.github.io/RustTraining/c-cpp-book/ch16-cases-3-5-lifetime-borrowing.html#case-study-4-god-object--composable-state): split state structs so helpers borrow only the part they need

## OWN-8: Borrow with in-task concurrency; spawn only for parallelism or detachment

**Rule.** For I/O-bound fan-out over borrowed data, run the futures on the current task with
`tokio::try_join!`, `FuturesUnordered`, or `stream::iter(..).buffer_unordered(n)`, and let them
borrow. Use `tokio::spawn` with owned data only when the work must run on other threads or outlive
the caller.

**Why.** `spawn` requires `Send + 'static`, so code that spawns ends up cloning every input or
wrapping it in `Arc` only to satisfy the bound. In-task concurrency has no such requirement, so the
clones disappear and lifetimes stay simple. The trade-off is that all the futures share one task:
they make progress concurrently but not in parallel, so CPU-heavy work still belongs in
`spawn_blocking` or `spawn`.

```rust,ignore
// Bad
async fn lookup_all(&self, keys: &[String]) -> Vec<Entry> {
    let mut tasks = JoinSet::new();
    for key in keys {
        let (key, store) = (key.clone(), self.store.clone());
        tasks.spawn(async move { store.lookup(&key).await });
    }
    tasks.join_all().await
}
```

```rust,ignore
// Good
async fn lookup_all(&self, keys: &[String]) -> Vec<Entry> {
    stream::iter(keys)
        .map(|key| self.store.lookup(key))
        .buffer_unordered(MAX_CONCURRENT_LOOKUPS)
        .collect()
        .await
}
```

**Review.**
- Flag `spawn`/`JoinSet` loops whose only purpose is concurrency and whose body clones each borrowed
  input. Suggest `try_join!` for a fixed set of futures and `buffer_unordered` for a collection
  (`buffered` if results must keep input order).
- Check that unbounded fan-out (`join_all` over a caller-sized input) has a concurrency limit.

**Exceptions.** Background loops, work that must survive the caller's cancellation, and CPU-bound
work need `spawn`, and owned or `Arc` captures are correct there. Every such spawn needs an owner
(ASYNC-3).

**Sources.**

- [spider `spider-client/src/client.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-client/src/client.rs#L296-L314): `SpiderClientBuilder::connect` connects both pools with `tokio::try_join!`
- [RustTraining async-book § Alternatives to `tokio::spawn`](https://microsoft.github.io/RustTraining/async-book/ch09-when-tokio-isnt-the-right-fit.html#alternatives-to-tokiospawn): `FuturesUnordered` borrows items with no `spawn` and no `'static`
- [RustTraining async-book § Decision Quick Reference](https://microsoft.github.io/RustTraining/async-book/ch16-summary-and-reference-card.html#decision-quick-reference): non-`'static` futures use `FuturesUnordered`; CPU-bound work goes elsewhere

## OWN-9: Model graphs as an owning arena with indices, not `Rc`/`Arc` links

**Rule.** For trees and graphs with parent links or cross-links, store all nodes in one owning `Vec`
and link them by a named index type. Never link nodes with strong `Rc`/`Arc` pointers in both
directions.

**Why.** Strong links in both directions form a cycle whose reference count never reaches zero, so
the whole graph leaks silently, and every node needs a `Mutex` or `RefCell` just so a neighbor can
mutate it. An arena has one owner and many viewers: indices cannot form ownership cycles, nodes sit
in contiguous memory, and mutation goes through `&mut` on the arena. Spider's `TaskGraph` is built
this way, with `parent_indices` and `child_indices` per task.

```rust,ignore
// Bad
struct Task {
    parents: Vec<Arc<Mutex<Task>>>,
    children: Vec<Arc<Mutex<Task>>>,
}
```

```rust,ignore
// Good
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct TaskIndex(usize);

pub struct TaskGraph {
    tasks: Vec<Task>,
}

pub struct Task {
    parent_indices: Vec<TaskIndex>,
    child_indices: Vec<TaskIndex>,
}
```

Spider's `TaskIndex` is currently a `usize` alias; a newtype, as shown, also keeps it from being
mixed up with other indices (TYPE-3).

**Review.**
- Flag `Rc`/`Arc` fields that point at the node's own type, or at a type that points back.
- Check that arena lookups use `get(index)`, returning `Option<&T>`, when the index can come from
  outside; direct indexing is acceptable only for indices the arena itself produced (DEF-4). When
  one structure holds two index spaces of the same integer type, ask for newtypes so they cannot be
  swapped.

**Exceptions.** When nodes are mutated concurrently by independent tasks under per-node locks,
one-directional `Arc` links are acceptable, as in spider's runtime task control blocks, which hold
`Arc` handles to their children and only a counter of unfinished parents.

**Sources.**

- [spider `spider-core/src/task/task_graph.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/task/task_graph.rs#L402-L409): `TaskGraph` owns all tasks in one `Vec<Task>`
- [spider `spider-core/src/task/task_graph.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/task/task_graph.rs#L185-L202): `Task` links neighbors by `parent_indices` and `child_indices`
- [spider `spider-storage/src/cache/task.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/cache/task.rs#L1093-L1107): `TaskControlBlock` holds child `Arc` handles and a parent counter
- [RustTraining c-cpp-book § Case Study 2: shared_ptr tree → Arena/index pattern](https://microsoft.github.io/RustTraining/c-cpp-book/ch16-case-studies.html#case-study-2-shared_ptr-tree--arenaindex-pattern): replaces a `shared_ptr` tree with an arena and indices

## OWN-10: Use iterator adapters for pipelines and plain loops for multi-output state

**Rule.** Replace flag-and-break loops and push loops with `any`, `all`, `find`, `position`,
`filter`, `map` and `collect`, and use `collect::<Result<Vec<_>, _>>()` to stop at the first error.
Use a `for` loop when one pass builds several outputs, a branch `.await`s, or the body is a state
machine.

**Why.** Named adapters state the intent, remove mutable flags, and compile to the same code as the
loop. `iter.map(f).collect::<Vec<_>>()[0]` allocates a whole `Vec` and panics on empty input, while
`.next()` or `.first()` does neither; clippy's `needless_collect` catches that one, but not a
hand-written flag-and-break loop. The opposite mistake is just as real: logic forced into `fold`
with tuple accumulators, or a chain of more than about four adapters, is harder to read than the
loop it replaced, so split long chains into named intermediate steps.

```rust,ignore
// Bad
let mut has_failed = false;
for task in &tasks {
    if task.is_failed() {
        has_failed = true;
        break;
    }
}
let mut job_ids = Vec::new();
for raw_id in &raw_ids {
    job_ids.push(raw_id.parse::<JobId>()?);
}
```

```rust,ignore
// Good
let has_failed = tasks.iter().any(Task::is_failed);
let job_ids = raw_ids
    .iter()
    .map(|raw_id| raw_id.parse::<JobId>())
    .collect::<Result<Vec<_>, _>>()?;
```

**Review.**
- Flag `let mut flag = false; for .. { if .. { flag = true; break; } }` and `push` loops that only
  filter, map or propagate an error.
- Also flag the reverse: a `fold` or a long adapter chain carrying several outputs, side effects or
  `.await`s. Ask for a `for` loop.

**Sources.**

- [y-scope/spider#290](https://github.com/y-scope/spider/pull/290#discussion_r2984258245): reviewer asks for `into_iter`, `filter` and `collect` over a loop
- [RustTraining rust-patterns-book § Iterator Chains vs. Loops: The Decision Framework](https://microsoft.github.io/RustTraining/rust-patterns-book/ch08-functional-vs-imperative-when-elegance-wins.html#83-iterator-chains-vs-loops-the-decision-framework): when iterator chains win and when loops win

# Async and concurrency

Async Rust rests on two facts. A future is a plain value: it does nothing until it is polled, and
dropping it cancels it at whichever `.await` it last reached. A spawned task works the other way
round: it runs on its own and outlives every handle to it until someone joins it or aborts it. Most
async bugs in our services come from forgetting one of these facts: lost results, half-applied
state, shutdowns that hang, tasks that die without anyone noticing. The rules below make it visible
in the code how long each future and task lives, and what happens when it ends early.

## ASYNC-1: Make every future you race, time out or serve safe to drop

**Rule.** Any future that is a `select!` branch, is wrapped in `timeout`, or is a request handler
can be dropped at any `.await`. It must not hold state that would be lost or left half-applied when
that happens. Don't move state out of your own collections into a raced future. Don't `.await`
between taking an item and recording its new owner. Document what dropping the future loses in a
`# Cancel safety` docstring section on any async fn (or future-returning fn) that callers may race.

**Why.** Cancellation in Rust is silent and immediate: the branch of a `select!` that loses is
simply dropped. A branch future's arguments are evaluated before the race starts, so
`pending_acks.pop_front()` passed into a branch loses the acknowledgment every time another branch
wins. Spider's scheduler `next_task` handler dequeues an assignment and then awaits
`registry.assign`, which waits for a table lock. If the client disconnects in that window, the
assignment ends up in neither place and nothing reschedules it. Some tokio operations are not
cancel-safe either: `read_line`, `read_exact` and `write_all` lose bytes they had already read or
written, and `mpsc::Sender::send` drops its message.

```rust,ignore
// Bad
loop {
    let response = tokio::select! {
        _ = heartbeat.tick() => {
            client.heartbeat().await?;
            continue;
        }
        result = client.next_task(pending_acks.pop_front()) => result?,
    };
    pending_acks.push_back(handle(response).await?);
}
```

```rust,ignore
// Good
loop {
    let ack = pending_acks.front().cloned();
    let response = tokio::select! {
        _ = heartbeat.tick() => {
            client.heartbeat().await?;
            continue;
        }
        result = client.next_task(ack) => result?,
    };
    pending_acks.pop_front();
    pending_acks.push_back(handle(response).await?);
}

// Hand on the claimed batch first; race only the read, whose buffer lives outside the future.
sender.send(claimed_batch).await.map_err(|_| Error::ConsumerGone)?;
let num_bytes_read = tokio::select! {
    biased;
    () = end_signal.cancelled() => return Err(Error::SessionEnded),
    read = read_more(stream, &mut buffer) => read?,
};
```

**Review.**
- For each `select!` branch and `timeout` future, check the cancel-safety section of its docs.
  `recv()`, `cancelled()`, `Lines::next_line`, `reserve()` and `read_buf` into a buffer declared
  outside the future are safe. `read_line`, `read_exact`, `write_all`, and a `send` whose message
  must survive are not. The fix is to call `reserve()` first, or to pin one long-lived future
  outside the loop and poll it by `&mut`.
- Flag `pop_*`, `take`, `remove` or `std::mem::take` inside a branch expression. The fix is to peek
  or clone, then commit the removal after the future completes (the receiver must then accept a
  repeated item).
- Flag any `.await` between a dequeue or receive and the bookkeeping that records the item's new
  owner. The fix is to make that step synchronous, to record ownership first, or to move the whole
  step into a body the caller can't cancel (ASYNC-2).

**Sources.**

- [spider `spider-scheduler/src/service.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/service.rs#L79-L123): `next_task` dequeues, then awaits `registry.assign`: the unsafe window
- [spider `spider-scheduler/src/core_impl/resource_group_round_robin/dispatch_queue.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/core_impl/resource_group_round_robin/dispatch_queue.rs#L462-L483): `Hint::consume_and_try_recv`, kept synchronous, with a `# Cancel safety` section
- [y-scope/clp#2676](https://github.com/y-scope/clp/pull/2676#discussion_r4488180940): reviewer wants one `read_more`, so cancellation never covers a claimed batch's send
- [y-scope/clp#2702](https://github.com/y-scope/clp/pull/2702): races only socket reads against the session's end; claimed batches still go out
- [clp `clp-rust-libs/query-result-listener/src/session/connection/mod.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/query-result-listener/src/session/connection/mod.rs#L143-L219): `Connection::run` sends the pending batch, then races only `read_more`
- [RustTraining async-book § Cancellation Hazards](https://microsoft.github.io/RustTraining/async-book/ch12-common-pitfalls.html#cancellation-hazards)

## ASYNC-2: Run multi-step mutations where the caller can't cancel them

**Rule.** A request handler whose body changes shared or durable state across more than one `.await`
must do one of two things. Either each step is a single guarded, idempotent write that recovery can
redo, or the body runs as a task in a `TaskTracker` owned by the service and the handler awaits its
result. Never leave a multi-step mutation inside the handler future itself.

**Why.** tonic (through hyper) drops the handler future when the client resets the stream, closes
the connection, or its `grpc-timeout` expires. In Spider
([#522](https://github.com/y-scope/spider/issues/522)) this could cut a handler off between the
cache update and enqueuing the successor tasks. The job stayed `Running` until the next restart, and
nothing was logged. Running the body as a spawned task makes its lifetime independent of the
request. Spider's helper also holds a tracker token across the shutdown check, so
`TaskTracker::wait()` can't return in the gap between the check and the spawn. It also wraps the
handle in a guard whose `Drop` keeps watching the abandoned body. Without that guard, a dropped
`JoinHandle` would discard a later panic or fatal error
([#541](https://github.com/y-scope/spider/pull/541#discussion_r4381726163)).

```rust,ignore
// Bad
async fn succeed_task(&self, request: Request) -> Result<Reply, Error> {
    self.cache.mark_succeeded(request.task_id).await?;
    self.enqueue_successors(request.task_id).await?;
    Ok(Reply::default())
}
```

```rust,ignore
// Good
async fn succeed_task(&self, request: Request) -> Result<Reply, Error> {
    let this = self.clone();
    self.spawn_body(async move {
        this.cache.mark_succeeded(request.task_id).await?;
        this.enqueue_successors(request.task_id).await?;
        Ok(Reply::default())
    })
    .await
}

async fn spawn_body<ReturnType: Send + 'static>(
    &self,
    body: impl Future<Output = Result<ReturnType, Error>> + Send + 'static,
) -> Result<ReturnType, Error> {
    let task_tracker_token = self.task_tracker.token();
    if self.shutdown_handle.is_cancelled() {
        return Err(Error::Stopping);
    }
    let join_handle = self.task_tracker.spawn(body);
    drop(task_tracker_token);
    let mut join_guard = BodyJoinGuard::new(join_handle, self.task_tracker.clone());
    tokio::select! {
        biased;
        result = &mut join_guard => result.map_err(Error::BodyFailed)?,
        () = self.shutdown_handle.cancelled() => Err(Error::Stopping),
    }
}
```

**Review.**
- In handlers, look for two or more state-changing awaits in a row, such as a cache write then a DB
  write, or a DB write then an RPC. The fix is to route the body through the service's
  `spawn_body`-style helper, or to collapse it into one guarded transaction (BND-3).
- If a spawned body's `JoinHandle` can be dropped without anyone observing it, require a drop guard
  that keeps watching for panics and fatal errors, or an `AbortOnDropHandle` if aborting the body is
  acceptable.

**Exceptions.** Read-only handlers. Loops where every write is a single-row transaction guarded by a
status check, and restart recovery redoes interrupted work: there a plain `select!` on the
cancellation token is enough. The query-coordinator cancellation monitor
([y-scope/clp#2573](https://github.com/y-scope/clp/pull/2573#discussion_r4332472724)) is an example.

**Sources.**

- [y-scope/spider#522](https://github.com/y-scope/spider/issues/522): a dropped handler future leaves the job cache half-updated, stuck `Running`
- [y-scope/spider#541](https://github.com/y-scope/spider/pull/541#discussion_r4381726163): reviewer: dropping `spawn_body` discards the body's later fatal error
- [y-scope/spider#555](https://github.com/y-scope/spider/pull/555): splits `state/service.rs` into `state/service/`, where `spawn_body` now lives
- [spider `spider-storage/src/state/service/state.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/state/service/state.rs#L1114-L1175): `ServiceState::spawn_body`: tracker token, shutdown check, drop guard
- [y-scope/clp#2573](https://github.com/y-scope/clp/pull/2573#discussion_r4332472724): guarded single-row writes make cutting the monitor off mid-flight safe

## ASYNC-3: Give every spawned task an owner and a failure destination

**Rule.** Every `tokio::spawn` has an owner that joins it or aborts it. The owner can be a
`JoinHandle` stored in the struct that owns the subsystem, a `JoinSet`, a `TaskTracker`, or an
`AbortOnDropHandle` tied to the value the task serves. Decide at the spawn site where the task's
failure goes. A critical task logs its error and fires the service's shutdown handle. A best-effort
task logs and returns `()` (ERR-9).

**Why.** Dropping a `JoinHandle` does not cancel the task; it detaches it. A detached task keeps
holding connections and locks after its owner is gone, it escapes graceful shutdown, and its panic
or `Err` is never seen. Spider hit this several times. A GC loop and the task-instance pool exited
on error, and nobody noticed until shutdown ([#387](https://github.com/y-scope/spider/pull/387),
[#391](https://github.com/y-scope/spider/pull/391)). A failed `resend_ready_tasks` left jobs stalled
([#374](https://github.com/y-scope/spider/pull/374)). `tokio::time::timeout(d, handle)` is the same
leak in disguise: on timeout it drops the handle, and the task keeps running.

```rust,ignore
// Bad
tokio::spawn(async move {
    let _ = job_cache.resend_ready_tasks().await;
});

tokio::time::timeout(stop_timeout, self.core_join_handle)
    .await
    .map_err(|_| Error::Stopping)?;
```

```rust,ignore
// Good
let shutdown_handle = self.shutdown_handle.clone();
self.task_tracker.spawn(async move {
    if let Err(e) = job_cache.resend_ready_tasks().await {
        tracing::error!(error = % e, "Failed to resend ready tasks. Shutting down.");
        shutdown_handle.shut_down_fatally();
    }
});

let mut core_join_handle = self.core_join_handle;
match tokio::time::timeout(stop_timeout, &mut core_join_handle).await {
    Ok(join_result) => log_core_exit(join_result),
    Err(_) => {
        core_join_handle.abort();
        return Err(Error::Stopping);
    }
}
```

**Review.**
- Flag every `tokio::spawn(..)` whose handle is discarded, including `let _ = tokio::spawn(..)`, and
  handles that get dropped by an early `?` or `try_join!`. The fix is to spawn into the owner's
  `TaskTracker` or `JoinSet`, or to store the handle. Use `AbortOnDropHandle` when the task's
  lifetime should follow a value, such as a stream.
- Flag `timeout(d, join_handle)` that takes the handle by value. The fix is
  `timeout(d, &mut handle)` followed by `handle.abort()` on expiry.
- For a spawned future that returns `Result`, ask who sees the `Err`. If nobody sees it until
  shutdown, add `inspect_err` plus `shut_down_fatally()` at the spawn site, once, rather than in
  every implementation.
- For work that only needs to run concurrently inside one function, prefer `try_join!` on the
  futures themselves, or a `JoinSet` (which aborts its tasks when dropped), over detached spawns
  (OWN-8).

**Exceptions.** A detached task whose end is guaranteed and documented at the spawn site. For
example, Spider's stderr forwarder ends when `kill_on_drop` kills the child and closes the pipe.
Also a join deadline that expires right before the process exits, since dropping the runtime aborts
what is left. A temporary fire-and-forget is acceptable only when review explicitly acknowledges it,
with a comment at the spawn site
([y-scope/clp#1736](https://github.com/y-scope/clp/pull/1736#discussion_r2595245383)). See also:
pr-review.md § Don't silently swallow errors.

**Sources.**

- [y-scope/spider#374](https://github.com/y-scope/spider/pull/374): spawned ready-task resend cancels the service if it fails
- [y-scope/spider#387](https://github.com/y-scope/spider/pull/387): background storage tasks exited silently on error; now they fire cancellation
- [y-scope/spider#391](https://github.com/y-scope/spider/pull/391): the same fix for the scheduler core's task
- [y-scope/spider#309](https://github.com/y-scope/spider/pull/309#discussion_r3107850946): the service, not the queue, holds the abort handle and cancels before exit
- [y-scope/clp#1736](https://github.com/y-scope/clp/pull/1736#discussion_r2595245383): reviewer explicitly accepts leaving the job detached for now
- [y-scope/clp#2705](https://github.com/y-scope/clp/pull/2705): the termination wait runs in a task that dropping the stream stops
- [spider `spider-scheduler/src/runtime.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/runtime.rs#L138-L155): the core's spawn logs its error and cancels the runtime
- [spider `spider-execution-manager/src/process_pool.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/process_pool.rs#L436-L440): detached stderr forwarder whose end `kill_on_drop` guarantees
- [RustTraining async-book § JoinHandle and Task Cancellation](https://microsoft.github.io/RustTraining/async-book/ch08-tokio-deep-dive.html#joinhandle-and-task-cancellation)

## ASYNC-4: Shut down through one token tree, with one deadline and an honest exit code

**Rule.**
- Create one root shutdown handle per runtime: a `CancellationToken` plus a fatal flag, like
  Spider's `ShutdownHandle` (OBJ-5).
- Give each long-running loop a clone of the root, or a `child_token()` if that loop needs to be
  cancelled on its own.
- Route every trigger into that root: internal fatal errors, `ctrl_c()`, and Unix `SIGTERM`.
- `stop(self)` cancels, drops the owners of actor senders, and joins all background tasks
  concurrently under one timeout. It treats `Ok(Ok)`, `Ok(Err)` and `Err(JoinError)` as separate
  outcomes and returns an error if any task failed or the deadline expired.
- `main` returns a non-zero `ExitCode` after a fatal shutdown, a failed phase, or an expired
  deadline.

**Why.** Kubernetes sends SIGTERM, not SIGINT. Binaries that handled only Ctrl-C used up the grace
period and were SIGKILLed, losing buffered output
([y-scope/spider#416](https://github.com/y-scope/spider/pull/416)). Spider-storage exited 0 after a
fatal error, so `on-failure` restart policies never fired. With no deadline, a single handler that
never returned kept the process alive, and the open socket kept passing health checks
([#527](https://github.com/y-scope/spider/pull/527)). Separate timers for each shutdown phase can
add up past the orchestrator's kill deadline. A `let _ = timeout(.., join!(..))` that threw away the
task results made a crashed pool look like a clean stop. Also, `JoinError` means "panicked *or*
cancelled", so code that labels it as a panic reports the wrong cause
([clp cd8eef5f](https://github.com/y-scope/clp/pull/2705/commits/cd8eef5f5ec37303897ed66d8903fb2c31693545)).

```rust,ignore
// Bad
pub async fn stop(&mut self) {
    self.token.cancel();
    let _ = tokio::time::timeout(self.stop_timeout, async {
        tokio::join!(&mut self.pool_join_handle, &mut self.gc_join_handle)
    })
    .await;
}
```

```rust,ignore
// Good
pub async fn stop(self) -> Result<(), Error> {
    self.shutdown_handle.shut_down_gracefully();
    self.task_tracker.close();
    let (is_pool_stopped, is_gc_stopped, ()) = tokio::time::timeout(self.stop_timeout, async {
        tokio::join!(
            join_and_log("Task instance pool", self.pool_join_handle),
            join_and_log("Job cache GC", self.gc_join_handle),
            self.task_tracker.wait(),
        )
    })
    .await
    .map_err(|_| Error::Stopping("background task stop timed out".to_owned()))?;
    if !is_pool_stopped || !is_gc_stopped {
        return Err(Error::Stopping("background task exited on an error or a panic".to_owned()));
    }
    Ok(())
}
```

`join_and_log` matches `Ok(Ok(()))`, `Ok(Err(e))` ("Background task exited on error.") and `Err(e)`
("Background task panicked or was cancelled.") separately, and returns whether the task stopped
cleanly.

**Review.**
- Each binary must listen for both `ctrl_c()` and `signal(SignalKind::terminate())?` and cancel the
  same token. The server's shutdown future must also wait on that token, so that an internal fatal
  error stops serving.
- Look for timeouts per phase. The fix is one pinned deadline future that starts when cancellation
  fires and is reused across the server-drain `select!` and `runtime.stop()`. Also check that `main`
  derives its exit code from `is_fatal()` (ERR-1) and from the result of each phase.
- An actor that drains until its channel closes can't exit while a sender is alive. Check that the
  sender owners are dropped (for example `drop(process_pool)`) before the actor is joined. The fatal
  flag must be stored with `Release` before `cancel()` and loaded with `Acquire`. `stop` consumes
  `self`: see also coding-style.md § Take ownership when the value mustn't be used afterwards.

**Sources.**

- [y-scope/spider#341](https://github.com/y-scope/spider/pull/341): the job-cache GC loop gets a clone of the runtime's token
- [y-scope/spider#346](https://github.com/y-scope/spider/pull/346#pullrequestreview-4554495319): the server stops on the token, so error handlers can end the runtime
- [y-scope/spider#368](https://github.com/y-scope/spider/pull/368): one token shared by core and registry; `stop` joins the core under a timeout
- [y-scope/spider#416](https://github.com/y-scope/spider/pull/416): adds `SIGTERM` listeners so Kubernetes termination is graceful
- [y-scope/spider#418](https://github.com/y-scope/spider/pull/418): `Runtime::run` drops the process pool before joining the log actor
- [y-scope/spider#527](https://github.com/y-scope/spider/pull/527): `ShutdownHandle` fatal flag, one 30 s deadline, non-zero `ExitCode`
- [spider `spider-storage/src/state/runtime.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/state/runtime.rs#L69-L137): `Runtime::stop` joins everything under one timeout, fails on error or panic
- [spider `spider-storage/src/bin/grpc_server.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/bin/grpc_server.rs#L154-L215): `wait_for_shutdown` shares one deadline across drain and stop, derives exit code
- [spider `spider-utils/src/shutdown.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-utils/src/shutdown.rs#L9-L58): `ShutdownHandle`: token plus fatal flag with `Release`/`Acquire`
- [y-scope/clp commit cd8eef5f](https://github.com/y-scope/clp/pull/2705/commits/cd8eef5f5ec37303897ed66d8903fb2c31693545): renames `TerminationPanicked`, since the task can also be cancelled

## ASYNC-5: Never hold a lock across an `.await` that waits on someone else

**Rule.**
- Never hold a `std::sync` guard, or a `DashMap` `Ref`/`Entry`, across `.await`. Scope it in a
  block, or `drop(guard)` before the next await.
- Use a `tokio::sync` lock only when the critical section itself must span an `.await`. Say in the
  field's docs what the lock excludes, and take nested locks in a fixed order.
- While holding any guard, never await something that may need the same lock, or something you don't
  control: an actor's reply, a `send` on a bounded channel, or a timeout the client chose.

**Why.** A std guard held across `.await` makes the future `!Send`, which shows up as a confusing
error at `tokio::spawn`. If it does compile (on a current-thread runtime, or for a `Send` guard such
as a `DashMap` shard lock), another task that tries to take the lock blocks its whole worker thread,
or deadlocks the runtime if it is on the same thread. Spider replaced `DashMap` with
`tokio::sync::RwLock<HashMap>` ([#321](https://github.com/y-scope/spider/pull/321)) so that no shard
lock is held across an `.await`. Spider's committer takes `job_execution_state.write()`. A handler
that awaited the committer's reply while still holding the read guard would never get that reply, so
`job.rs` drops the guard explicitly before submitting. A bounded `send` made while holding a cache
lock deadlocked the inbound queue ([#523](https://github.com/y-scope/spider/issues/523), fixed in
[#526](https://github.com/y-scope/spider/pull/526)). Tokio's `RwLock` can't upgrade a read guard to
a write guard. If you drop the read guard and then take the write guard, another task can change the
state in between, so check it again under the write guard (DEF-2).

```rust,ignore
// Bad
let job = state.read().await;
let outputs = job.collect_outputs();
tree.submit(Event::Done { outputs }).await?;

let is_running = state.read().await.is_running();
if is_running {
    state.write().await.commit_outputs(new_outputs);
}
```

```rust,ignore
// Good
let job = state.read().await;
let outputs = job.collect_outputs();
drop(job);
tree.submit(Event::Done { outputs }).await?;

let mut job = state.write().await;
job.ensure_running()?;
job.commit_outputs(new_outputs);
```

**Review.**
- For every guard, find the next `.await` and ask what it waits on. If that wait can need the same
  lock, or depends on another component's progress, ask for the guard to be released before the
  await, or for the send to happen outside the lock.
- Don't ask authors to remove an explicit `drop(guard)` that looks redundant.
  `clippy::significant_drop_tightening` asks for it, and it marks where the critical section ends
  ([y-scope/clp#1704](https://github.com/y-scope/clp/pull/1704#discussion_r2593538780),
  [y-scope/spider#549](https://github.com/y-scope/spider/pull/549#discussion_r4436730894)).
- Flag read-then-write sequences and wrappers that claim to "promote" a lock. The fix is a single
  write guard, or an accessor like `validate_and_write(check)` that checks the state again under the
  write guard.

**Exceptions.** A tokio lock held across an await of purely local work that it is meant to
serialize. Examples are Spider's `Mutex<Option<ExecutorHandle>>` in the process pool (where `None`
means the pool is dead), and the execution-manager registry, which takes the table lock and then the
entry lock and documents what that excludes.

**Sources.**

- [y-scope/spider#293](https://github.com/y-scope/spider/pull/293#discussion_r3025264447): tokio can't promote locks; a wrapper would hide the guard being dropped
- [y-scope/spider#293](https://github.com/y-scope/spider/pull/293#discussion_r3024975470): explicit `drop` before return shortens the critical section, per clippy
- [y-scope/spider#321](https://github.com/y-scope/spider/pull/321): replaces `DashMap` so no shard lock is held across `.await`
- [y-scope/spider#526](https://github.com/y-scope/spider/pull/526): makes inbound lanes unbounded so no send waits under a cache lock
- [y-scope/spider#549](https://github.com/y-scope/spider/pull/549#discussion_r4436730894): author keeps an explicit `drop` because clippy flags its removal
- [y-scope/clp#1704](https://github.com/y-scope/clp/pull/1704#discussion_r2593538780): explicit `drop` answers clippy's request to shorten the guard's lifetime
- [y-scope/clp#2117](https://github.com/y-scope/clp/pull/2117#discussion_r2996931367): lock, check, then `drop` the guard before waiting again
- [spider `spider-storage/src/cache/job.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/cache/job.rs#L528-L591): `succeed_task_instance` drops the read guard before submitting to the committer
- [spider `spider-scheduler/src/execution_manager_registry.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/execution_manager_registry.rs#L163-L211): `upsert_em_state`: table lock, then entry lock, with what it excludes
- [spider `spider-execution-manager/src/process_pool.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/process_pool.rs#L154-L211): `ProcessPool::execute` holds the tokio mutex across the run; `None` means dead
- [RustTraining async-book § Holding MutexGuard Across .await](https://microsoft.github.io/RustTraining/async-book/ch12-common-pitfalls.html#holding-mutexguard-across-await)

## ASYNC-6: Bound every queue, and handle every channel outcome

**Rule.**
- Create channels bounded, with the capacity from config or a named constant. An unbounded channel
  needs a comment where it is created that names what else bounds it.
- Handle every outcome. A failed `send` means the consumer is gone, so stop producing. `recv()`
  returning `None` is the only end-of-stream, so drop the original `Sender` after cloning it. A
  `broadcast` `Lagged(n)` is logged and handled, not ignored.
- To cap spawned work, call `acquire_owned()` on a semaphore *before* `spawn` and move the permit
  into the task.

**Why.** An unbounded queue turns a slow consumer into unbounded memory growth. A leftover `Sender`
keeps the channel open, so the consumer loop never ends and shutdown hangs. `let _ = tx.send(..)`
keeps a worker taking jobs whose results nobody will receive. Taking the permit *inside* the spawned
task limits how many tasks run, but not how many exist. Polling with `try_acquire` turns the loop
into a busy spin
([y-scope/clp#2435](https://github.com/y-scope/clp/pull/2435#discussion_r3700473081)). Spider
documents each of its unbounded lanes, because the admission threshold already caps them and a
bounded send made under a lock deadlocked ([#526](https://github.com/y-scope/spider/pull/526)). A
consumer that stops when the job's status says "done", instead of when the channel closes, loses a
batch that was claimed but is still waiting for room in the channel
([y-scope/clp#2702](https://github.com/y-scope/clp/pull/2702)).

```rust,ignore
// Bad
let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();
for shard in shards {
    let tx = tx.clone();
    tokio::spawn(async move {
        while let Some(item) = produce_next(&shard).await {
            let _ = tx.send(item);
        }
    });
}
while let Some(item) = rx.recv().await { /* never ends: `tx` is still alive */ }
```

```rust,ignore
// Good
let (tx, mut rx) = tokio::sync::mpsc::channel(config.channel_capacity.get());
let mut producers = JoinSet::new();
for shard in shards {
    let tx = tx.clone();
    producers.spawn(async move {
        while let Some(item) = produce_next(&shard).await {
            if tx.send(item).await.is_err() {
                break;
            }
        }
    });
}
drop(tx);
while let Some(item) = rx.recv().await { /* ... */ }

let permit = Arc::clone(&self.job_semaphore)
    .acquire_owned()
    .await
    .map_err(Error::JobSemaphoreClosed)?;
jobs.spawn(async move {
    let _permit = permit;
    run(job).await
});
```

**Review.**
- Flag `unbounded_channel()` / `async_channel::unbounded()` without a comment naming the bound. Flag
  `let _ = tx.send(..)` in a producer, and channel loops that break on an out-of-band status. See
  also: pr-review.md § Don't silently swallow errors.
- Flag `while let Ok(x) = rx.try_recv()` drain loops that have no cap on items or bytes per pass
  (SRV-3). Put the cap in one owner, and move an item that doesn't fit back to the front of its
  queue.
- Flag semaphore permits acquired inside the spawned task, `try_acquire` polling loops, and
  configured limits that aren't validated against `Semaphore::MAX_PERMITS` (`Semaphore::new` panics
  above it).

**Exceptions.** Inside an actor, `let _ = reply.send(..)` on a `oneshot` is fine, because it only
means the requester went away. Say so in a comment. An unbounded lane is right when a bound already
exists elsewhere and a channel capacity could only reject sends the design depends on (Spider's
inbound queue and per-group dispatch queues).

**Sources.**

- [y-scope/spider#309](https://github.com/y-scope/spider/pull/309#pullrequestreview-4122192679): a bounded buffer should block when full and unblock as the consumer progresses
- [y-scope/spider#526](https://github.com/y-scope/spider/pull/526): unbounded lanes: jobs times tasks already bound them, and bounded sends deadlocked
- [y-scope/spider#557](https://github.com/y-scope/spider/pull/557): a round takes at most 256 events; the pending queue alone owns the cap
- [y-scope/clp#2435](https://github.com/y-scope/clp/pull/2435#discussion_r3716842837): get a permit before spawning, so the semaphore blocks task creation
- [y-scope/clp#2435](https://github.com/y-scope/clp/pull/2435#discussion_r3700473081): acquiring a semaphore in a busy loop is not a good design
- [y-scope/clp#2702](https://github.com/y-scope/clp/pull/2702): the result stream's end, not the job's status, marks the end of results
- [spider `spider-scheduler/src/core_impl/resource_group_round_robin/dispatch_queue.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/core_impl/resource_group_round_robin/dispatch_queue.rs#L83-L94): `DispatchQueueRegistry` documents why every queue is unbounded
- [spider `spider-execution-manager/src/executor_log_collection.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/executor_log_collection.rs#L101-L105): `LINE_CHANNEL_CAP`: a named, deliberately bounded capacity for backpressure
- [RustTraining rust-patterns-book § Bounded vs Unbounded and Backpressure](https://microsoft.github.io/RustTraining/rust-patterns-book/ch05-channels-and-message-passing.html#bounded-vs-unbounded-and-backpressure)
- [RustTraining async-book § Backpressure with Bounded Channels](https://microsoft.github.io/RustTraining/async-book/ch13-production-patterns.html#backpressure-with-bounded-channels)

## ASYNC-7: Don't block the executor, and put a deadline on every external wait

**Rule.** Inside async code, never call blocking APIs: `std::fs`, `std::thread::sleep`, synchronous
clients, or long CPU loops. Use the tokio equivalent or `spawn_blocking`. Bound every await on
another party with a deadline: an RPC, a DB call, a remote lock, or a channel that cannot close. Use
`tokio::time::timeout`, or the client's own request timeout if it has one. Take the duration from
config and map `Elapsed` to its own error variant that carries the duration.

**Why.** A future that blocks holds its worker thread, so every task scheduled on that thread
starves. Throughput drops, timeouts fire late, or the service looks hung at 0% CPU. Nothing fails to
compile and nothing is logged, so review is the only place this gets caught. Without a deadline, one
peer that never answers holds a task, a permit or a lock forever. In Spider, the dispatch-queue
registry owns both ends of its broadcast channel, so `recv()` can never return `None`. That makes a
deadline mandatory there ([#449](https://github.com/y-scope/spider/pull/449)). A separate
`Timeout(Duration)` variant lets callers retry or report a timeout differently from a real failure.

```rust,ignore
// Bad
async fn load_manifest(&self, path: &Path) -> Result<Manifest, Error> {
    let bytes = std::fs::read(path)?;
    let digest = compute_digest(&bytes);
    self.client.fetch_manifest(digest).await
}
```

```rust,ignore
// Good
async fn load_manifest(&self, path: &Path) -> Result<Manifest, Error> {
    let bytes = tokio::fs::read(path).await?;
    let digest = tokio::task::spawn_blocking(move || compute_digest(&bytes))
        .await
        .map_err(Error::BlockingTaskFailed)?;
    let fetch_timeout = Duration::from_secs(self.config.fetch_timeout_sec);
    tokio::time::timeout(fetch_timeout, self.client.fetch_manifest(digest))
        .await
        .map_err(|_| Error::Timeout(fetch_timeout))?
}
```

**Review.**
- Flag `std::fs`, `std::thread::sleep`, `std::process::Command::output`, blocking HTTP or DB
  clients, and unbounded CPU loops inside `async fn`. If large blocks end up wrapped in
  `spawn_blocking`, the logic should probably move to a sync module that the async layer calls.
- Flag awaits on RPCs, DB calls or channels that have no deadline, and production timeouts written
  as literals. Config durations are whole seconds: see also coding-style.md § Prefer `u64` seconds
  over `Duration` for time config.
- When a sync-only decoder has to consume an async stream (`rmp_serde` over an S3 `ByteStream`),
  make the buffering deliberate and document its memory bound
  ([y-scope/clp#1728](https://github.com/y-scope/clp/pull/1728#discussion_r2594459618)). Never read
  synchronously on the runtime thread to work around it.

**Exceptions.** Short synchronous work, such as parsing a small payload or a short
`std::sync::Mutex` section, is fine inline. A join deadline for an internal task may be a named
constant, such as `CANCELLATION_MONITOR_JOIN_TIMEOUT`
([y-scope/clp#2573](https://github.com/y-scope/clp/pull/2573#discussion_r4298545773)).

**Sources.**

- [y-scope/spider#449](https://github.com/y-scope/spider/pull/449): the queue can't close while the registry lives, so `next_hint` takes a `wait_time`
- [y-scope/clp#1728](https://github.com/y-scope/clp/pull/1728#discussion_r2594459618): sync `rmp_serde` over an S3 stream needs the whole file; document it
- [y-scope/clp#2573](https://github.com/y-scope/clp/pull/2573#discussion_r4298545773): reviewer asks for a deadline on the monitor's join; 10 s hardcoded is fine
- [spider `spider-scheduler/src/core_impl/resource_group_round_robin/dispatch_queue.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/core_impl/resource_group_round_robin/dispatch_queue.rs#L203-L230): `next_hint` bounds the broadcast `recv` with `timeout`
- [RustTraining async-book § Blocking the Executor](https://microsoft.github.io/RustTraining/async-book/ch12-common-pitfalls.html#blocking-the-executor)
- [RustTraining async-book § Timeouts and Retries](https://microsoft.github.io/RustTraining/async-book/ch13-production-patterns.html#timeouts-and-retries)
- [RustTraining async-book § The `spawn_blocking` Smell](https://microsoft.github.io/RustTraining/async-book/ch14-async-is-an-optimization-not-an-architecture.html#the-spawn_blocking-smell)

## ASYNC-8: Write `biased;` when `select!` priority is part of correctness

**Rule.** Sometimes the result depends on which ready branch wins: a cancellation or failure must
beat ready work, or an end signal must beat an EOF that is already available. In those cases write
`biased;`, list the branches in priority order, and add a one-line comment above the `select!`
explaining why the order matters.

**Why.** `tokio::select!` picks at random among the branches that are ready. Without `biased;`, a
connection of a session that has already failed can still be acknowledged, because its EOF happened
to be polled first ([y-scope/clp#2702](https://github.com/y-scope/clp/pull/2702)). These races show
up only some of the time: removing `biased` in
[#2702](https://github.com/y-scope/clp/pull/2702#pullrequestreview-5865892568) failed the targeted
test in only 7 of 12 runs, so a missing keyword gets past CI. `biased;` has a cost of its own: a
branch that is always ready starves every branch after it. So list the rarely ready, must-win
branches (cancellation, session end) first, and don't add `biased;` where fairness is the goal.

```rust,ignore
// Bad
tokio::select! {
    result = check_eof(stream, &mut buffer) => result?,
    end = state.ended() => return Err(end.into()),
}
```

```rust,ignore
// Good
// `biased` must check the end first, so that a connection of a failed session isn't
// acknowledged, even if its EOF is already ready.
tokio::select! {
    biased;
    end = state.ended() => return Err(end.into()),
    result = check_eof(stream, &mut buffer) => result?,
}
```

**Review.**
- For every `select!` that has a cancellation, shutdown or end branch next to a work branch, ask
  what happens if the work branch wins once more after the end has fired. If that acknowledges,
  commits or sends something it shouldn't, require `biased;` with the must-win branch first and a
  comment saying why. If one extra iteration is harmless (an extra heartbeat), leave it unbiased.
- Flag `biased;` when a branch that is almost always ready (a busy channel, an interval that is
  behind) comes before branches that must still make progress.
- Tests for ordering bugs must use real time and be run repeatedly before you trust them. See also:
  coding-style.md § Prefer real-time testing for complex async code.

**Sources.**

- [y-scope/clp#2702](https://github.com/y-scope/clp/pull/2702#pullrequestreview-5865892568): removing `biased` fails the targeted test in only 7 of 12 runs
- [y-scope/clp#2705](https://github.com/y-scope/clp/pull/2705): a session failure takes priority over an already available terminal status
- [y-scope/spider#341](https://github.com/y-scope/spider/pull/341): adds the job-cache GC loop's `select!` over shutdown, terminated jobs and ticks
- [clp `clp-rust-libs/query-result-listener/src/session/connection/mod.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/query-result-listener/src/session/connection/mod.rs#L202-L208): the EOF race under `biased`, end first, with the comment saying why
- [RustTraining async-book § select! Fairness and Starvation](https://microsoft.github.io/RustTraining/async-book/ch12-common-pitfalls.html#select-fairness-and-starvation)

## ASYNC-9: Give shared mutable state one owning actor

**Rule.** When several tasks mutate one structure, or a background job (GC, flush) also touches it,
and its invariants span more than one field, give the structure to a single owning task. That task
receives typed commands over a channel and runs a `select!` loop over shutdown, commands (exiting on
`None`), and timers with an explicit `MissedTickBehavior`.
- The factory returns `(Handle, JoinHandle)`.
- Handle methods return a `Result` when the actor is gone.
- A dropped reply `oneshot` is an internal "poisoned" error, never a success.
- On shutdown, `close()` the receiver, drain it with `recv().await`, and answer every pending
  request.

**Why.** While each handler wrote a Spider job's state under its own locks, three race bugs reached
production: a cancel racing a terminal failure, a cancel of a Ready job that had a cleanup task, and
a failure that didn't cancel sibling tasks ([#514](https://github.com/y-scope/spider/issues/514),
[#516](https://github.com/y-scope/spider/issues/516),
[#517](https://github.com/y-scope/spider/issues/517)). Making the tree committer the only writer
turned these into ordered decisions made in one place
([#551](https://github.com/y-scope/spider/pull/551)). A pool owned by one task needs no mutex, and
its GC can't race registration
([#310](https://github.com/y-scope/spider/pull/310#discussion_r3107587053)). The default
`MissedTickBehavior::Burst` fires cycles back-to-back after a stall. After `close()`, `try_recv` can
miss a send that is still in flight, and a request that was drained but never answered leaves its
caller waiting forever.

```rust,ignore
// Bad
#[derive(Clone)]
struct Pool {
    instances: Arc<Mutex<Vec<Entry>>>, // registration and a GC task both lock it
}

impl PoolHandle {
    pub async fn register(&self, entry: Entry) {
        let _ = self.sender.send(Message::Register(entry)).await;
    }
}
```

```rust,ignore
// Good
pub fn spawn(config: &PoolConfig, shutdown: ShutdownHandle) -> (PoolHandle, JoinHandle<Result<(), Error>>) {
    let (sender, receiver) = mpsc::channel(config.message_channel_capacity.get());
    let mut gc_interval = tokio::time::interval(Duration::from_secs(config.gc_interval_sec));
    gc_interval.set_missed_tick_behavior(MissedTickBehavior::Delay);
    let pool = Pool { instances: Vec::new(), receiver, gc_interval };
    (PoolHandle { sender }, tokio::spawn(pool.run(shutdown)))
}

async fn run(mut self, shutdown: ShutdownHandle) -> Result<(), Error> {
    loop {
        tokio::select! {
            biased;
            () = shutdown.cancelled() => break,
            _ = self.gc_interval.tick() => self.run_gc_cycle().await?,
            message = self.receiver.recv() => match message {
                Some(message) => self.handle(message).await?,
                None => return Ok(()),
            },
        }
    }
    self.receiver.close();
    while let Some(message) = self.receiver.recv().await {
        message.reject(Error::ServiceStopping);
    }
    Ok(())
}
```

**Review.**
- Flag `Arc<Mutex<_>>` state written by several handlers plus a background loop. Suggest an actor,
  especially when the invariants span more than one field.
- Check the actor's handle methods: no `let _ =` on the command send, no `expect` on the reply. Both
  should map to a typed error such as `ActorStopped` or `TreePoisoned`.
- Check the actor's exit paths: every pending waiter is answered, intervals set
  `MissedTickBehavior`, and slow work awaited inside a branch body has its own timeout, because it
  is not raced against the other branches.

**Exceptions.** If the state has a trivial invariant and is touched only in short synchronous
sections, a `std::sync::Mutex` behind a handle (OBJ-5) is simpler. If queued items must not be lost
(a log sink), stop the actor by closing its channel rather than through cancellation, and treat the
token as fire-only ([y-scope/spider#418](https://github.com/y-scope/spider/pull/418)).

**Sources.**

- [y-scope/spider#309](https://github.com/y-scope/spider/pull/309#discussion_r3107850946): one coroutine owns all the receivers; the service holds its handle
- [y-scope/spider#310](https://github.com/y-scope/spider/pull/310#discussion_r3107587053): a single coroutine owns the pool's state, so no mutex is needed
- [y-scope/spider#418](https://github.com/y-scope/spider/pull/418): the log actor stops on channel closure; its token is fire-only
- [y-scope/spider#546](https://github.com/y-scope/spider/pull/546): `TreeControlBlock::submit` queues events for the tree's one committer
- [y-scope/spider#549](https://github.com/y-scope/spider/pull/549): adds the committer that applies tree events one round at a time
- [y-scope/spider#551](https://github.com/y-scope/spider/pull/551): the committer becomes the only writer of a job's state, fixing three races
- [spider `spider-storage/src/task_instance_pool.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/task_instance_pool.rs#L261-L283): `TaskInstancePool` owns all pool state inside one spawned task
- [spider `spider-storage/src/state/tree_committer/mod.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/state/tree_committer/mod.rs#L189-L220): `close_and_answer` closes, drains with `recv().await`, answers every event
- [spider `spider-execution-manager/src/liveness.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/liveness.rs#L49-L80): `spawn` returns `(LivenessHandle, JoinHandle)` and sets `MissedTickBehavior::Skip`
- [RustTraining rust-patterns-book § Actor Pattern with Channels](https://microsoft.github.io/RustTraining/rust-patterns-book/ch05-channels-and-message-passing.html#actor-pattern-with-channels)

## ASYNC-10: Design async APIs around laziness and `Send`

**Rule.**
- If a call's side effect must happen when the call is made (enqueuing an event, reserving a slot),
  write a synchronous `fn` that performs it and then returns `impl Future<Output = _> + Send +
  use<>`. Don't write an `async fn` for this.
- Futures that callers may spawn must be `Send`. For traits with async methods, use
  `#[async_trait]`, whose futures are `Send` by default. A public client crate, whose futures are
  spawned only by other crates, asserts this at compile time for each async method, not only for
  the handle type.

**Why.** An `async fn` does nothing until it is polled. The order in which events reach the actor
then depends on when callers poll, not on when they call, and a future that is dropped before it is
polled never sends anything. With `use<>`, the returned future doesn't borrow `self`, so the caller
can release locks on `self` before awaiting the reply. An async closure's future type can't be
named, so it can't be given a `Send` bound. In Spider it silently became `!Send`, and `SpiderClient`
calls could not be spawned on a multi-threaded runtime
([#404](https://github.com/y-scope/spider/pull/404)). Checking only that the handle is `Send + Sync`
doesn't catch that: a future that holds a non-`Send` value across an `.await` breaks spawnability
while the handle stays `Send + Sync`.

```rust,ignore
// Bad
pub async fn submit(&self, event: TreeEvent) -> TreeEventReply {
    let (reply, receiver) = oneshot::channel();
    self.sender.send(Pending { event, reply }).map_err(|_| CacheError::ServiceStopping)?;
    receiver.await.unwrap_or_else(|_| Err(InternalError::TreePoisoned.into()))
}
```

```rust,ignore
// Good
pub fn submit(&self, event: TreeEvent) -> impl Future<Output = TreeEventReply> + Send + use<> {
    let (reply, receiver) = oneshot::channel();
    let is_refused = self.sender.send(Pending { event, reply }).is_err();
    async move {
        if is_refused {
            return Err(CacheError::ServiceStopping);
        }
        receiver.await.unwrap_or_else(|_| Err(InternalError::TreePoisoned.into()))
    }
}
```

**Review.**
- Async callbacks that run in place may take `AsyncFnMut`
  ([y-scope/clp#2224](https://github.com/y-scope/clp/pull/2224#discussion_r3144410113)). When the
  produced future must be `Send` (it is spawned, or it backs a public client), use the
  `FnMut() -> FutureType` bound with an owned `async move` future described in OWN-4 (Spider's
  `execute_with_retry`).
- APIs that hand a future or closure to `tokio::spawn` should state `Send + 'static` on their own
  signature, so a violation is reported at the caller. A public client crate should have one
  `assert_send(&client.method(..))` per async method, next to a `const _` `Send + Sync` assertion
  on the handle, as `spider-client` does. Inside a workspace, the crate's own `tokio::spawn` calls
  already check this, so other types need no assertion.
- Flag `#[async_trait(?Send)]` on a trait whose futures are spawned or held across tasks.
- Flag a call to an `async fn` whose result is never awaited or spawned, and an `async fn` whose
  first statement is a send or reservation that callers expect to happen at call time.

**Sources.**

- [y-scope/spider#404](https://github.com/y-scope/spider/pull/404): async closures' futures can't be bounded `Send`; adds per-method assertions
- [y-scope/spider#546](https://github.com/y-scope/spider/pull/546): `submit` queues the event at the call and returns a future of the reply
- [y-scope/clp#2224](https://github.com/y-scope/clp/pull/2224#discussion_r3144410113): `AsyncFnMut` is preferred but hits the HRTB `Send` pitfall
- [spider `spider-storage/src/cache/tree/control_block.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/cache/tree/control_block.rs#L50-L93): `TreeControlBlock::submit`: sync fn returning `impl Future + Send + use<>`
- [spider `spider-utils/src/grpc/retry.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-utils/src/grpc/retry.rs#L33-L86): `execute_with_retry` takes `FnMut() -> FutureType` with `FutureType: Send`
- [spider `spider-client/src/client.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-client/src/client.rs#L319-L349): `Send + Sync` assertion on the handles plus one `assert_send` per method
- [RustTraining type-driven-correctness-book § Function Bounds as Theorems](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch16-send-sync-compile-time-concurrency-proofs.html#function-bounds-as-theorems)
- [RustTraining async-book § Holding MutexGuard Across .await](https://microsoft.github.io/RustTraining/async-book/ch12-common-pitfalls.html#holding-mutexguard-across-await): a non-`Send` value held across `.await` only fails at `spawn`

# Serialization, config and external boundaries

Config files, request bodies, protobuf messages, database rows, environment variables, and bytes
from a peer or a child process all come from outside the process, so none of them can be trusted
yet. Parse such data once, at the edge, and strictly, into types that cannot hold an invalid value,
so the code behind the edge never checks it again. Every implicit behavior at a boundary should
become an explicit, visible choice: serde ignoring unknown keys, a default value, an `Option`
quietly turning into a default, a catch-all status-code arm, a non-locking read. Data going back out
should carry only what its consumer needs, and no secrets or internal details.

## BND-1: Validate external data while deserializing it, not afterwards

**Rule.** Deserialize external data directly into types whose fields are already valid: `NonZero*`,
`NonEmptyString`, or a newtype with `#[serde(try_from = "Unchecked...")]` whose `TryFrom` calls the
type's checking constructor. Don't walk a `serde_json::Value`, and don't deserialize into a type and
then call a `validate(&self)` on that same type.

**Why.** Indexing a `Value` returns `Null` for a misspelled or missing key, so the mistake surfaces
deep in business logic as a `None` or a panic instead of as one parse error at load time. With a
separate `validate()` step, an invalid value exists for a while and leaks wherever someone forgets
the call. It also splits the checks across layers: in the API server, `max_num_results` was rejected
during deserialization while the bucket size was checked later in the handler, so the same kind of
mistake got a different status code and message (raised in review of
[y-scope/clp#2567](https://github.com/y-scope/clp/pull/2567#discussion_r4277862603), fixed in
[y-scope/clp#2581](https://github.com/y-scope/clp/pull/2581)). With `try_from`, the deserialized
value is valid by construction, the error names the offending value and its position, and there is
only one validation code path.

```rust,ignore
// Bad
#[derive(Deserialize)]
struct QueryRequest {
    bucket_size_millisecs: i64,
}

async fn query(Json(request): Json<QueryRequest>) -> Response {
    if request.bucket_size_millisecs <= 0 {
        return (StatusCode::BAD_REQUEST, "bad bucket size").into_response();
    }
    // ...
}
```

```rust,ignore
// Good
#[derive(Deserialize)]
#[serde(try_from = "UncheckedTimeRange")]
pub struct TimeRange {
    begin_timestamp_millisecs: Option<i64>,
    end_timestamp_millisecs: Option<i64>,
}

impl TryFrom<UncheckedTimeRange> for TimeRange {
    type Error = ReversedTimeRangeError;

    fn try_from(raw: UncheckedTimeRange) -> Result<Self, Self::Error> {
        Self::new(raw.begin_timestamp_millisecs, raw.end_timestamp_millisecs)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct UncheckedTimeRange {
    begin_timestamp_millisecs: Option<i64>,
    end_timestamp_millisecs: Option<i64>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct QueryRequest {
    bucket_size_millisecs: Option<PositiveI64>,
    time_range: TimeRange,
}
```

**Review.**
- Flag `json["a"]["b"].as_str()` or `.get(..).and_then(..)` chains outside the parsing edge, and
  handler-side checks such as `if field <= 0` on deserialized values. The fix is to give the field a
  validating type.
- Flag a `validate(&self)` called after `from_str`, and a hand-written `Deserialize` that only
  parses a primitive and then calls a constructor. Replace both with `#[serde(try_from = ...)]`,
  plus `into = ...` if the type is also serialized. Container attributes such as
  `deny_unknown_fields` belong on the `Unchecked*` struct: serde ignores them on the `try_from`
  type.
- Test the `TryFrom` once, in the type's own module, not again in every struct that embeds the type.

**Exceptions.** A payload that is schemaless by design, such as opaque user metadata passed through
unchanged, may stay a `Value` as long as no code inspects it. When validation needs context the
value doesn't carry (another config section, a client, the file system), deserialize a raw type and
convert it into a separate `Validated*` type that the loader returns; the raw type never leaves the
loader. When a type's invariants are enforced as it is built up piece by piece (a graph built with
`insert_*` calls), hand-write `Deserialize` so that it replays the checked constructor, as spider's
`TaskGraph::from_json` does.

See also: coding-style.md § Type-Level Validation, TYPE-1 (parse at the boundary) and TYPE-2 (seal
every construction path).

**Sources.**

- [y-scope/clp#2567](https://github.com/y-scope/clp/pull/2567#discussion_r4277862603): reviewer notes the two fields are validated at different stages
- [y-scope/clp#2572](https://github.com/y-scope/clp/issues/2572): asks for one status code and error format for invalid values
- [y-scope/clp#2581](https://github.com/y-scope/clp/pull/2581): rejects invalid bucket sizes with the same 422 as `max_num_results`
- [y-scope/clp#2484](https://github.com/y-scope/clp/pull/2484#discussion_r3818189641): reviewer: an unvalidated bucket size gets a 200, then the job fails
- [clp `clp-rust-libs/clp-rust-utils/src/job_config/search.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/clp-rust-utils/src/job_config/search.rs#L55-L115): `TimeRange` deserialized through `try_from = "UncheckedTimeRange"`
- [clp `clp-rust-libs/clp-rust-utils/src/types.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/clp-rust-utils/src/types.rs#L140-L183): `PositiveI64` with `try_from = "NonZeroU64"` and `into = "i64"`
- [spider `spider-core/src/task/task_graph.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/task/task_graph.rs#L956-L1063): `TaskGraphVisitor` replays the checked `TaskGraph::new` and `insert_task`
- [y-scope/spider#320](https://github.com/y-scope/spider/pull/320#discussion_r3211197530): reviewer: name the checking constructor `create`, not `validate`
- [RustTraining type-driven-correctness-book § Parse, Don't Validate](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch07-validated-boundaries-parse-dont-validate.html#parse-dont-validate): parse once into a type that carries validity
- [RustTraining type-driven-correctness-book § The Untyped Redfish Client](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch17-redfish-applied-walkthrough.html#the-untyped-redfish-client): indexing `serde_json::Value` with `unwrap()` at every use

## BND-2: Reject unknown keys in every schema you own, and tag enums explicitly

**Rule.** Put `#[serde(deny_unknown_fields)]` on every struct and enum deserialized from config, job
configs, or requests to an API you own, including nested section structs and the struct inside each
enum variant. Select enum variants with an explicit tag field: `tag = "type"` for messages, or the
adjacently tagged `tag = "policy", content = "config"` for config. Don't use `untagged`, and don't
use the default externally tagged representation for config.

**Why.** By default serde silently drops keys it doesn't recognize. Combined with
`#[serde(default)]`, a typo such as `queue_capcity: 64` throws away the user's setting and runs with
0 without any error; spider's scheduler and storage `RuntimeConfig` structs have exactly this gap
around their `#[serde(default)]` sections. On an adjacently tagged enum, `deny_unknown_fields`
checks only the keys next to `tag` and `content`, so the variant's own struct needs the attribute
too. An untagged enum tries variants in order: a payload that also fits an earlier variant decodes
as the wrong one, and a payload that fits none gets only "data did not match any variant". With our
YAML crate (`yaml_serde`), an externally tagged enum accepts only a YAML tag such as `!RoundRobin`
and rejects the nested-map form, and Helm values cannot express YAML tags
([y-scope/spider#412](https://github.com/y-scope/spider/pull/412)).

```rust,ignore
// Bad
#[derive(Deserialize)]
pub enum SchedulerConfig {
    RoundRobin(RoundRobinConfig), // needs a `!RoundRobin` YAML tag
}

#[derive(Deserialize)]
pub struct RoundRobinConfig {
    #[serde(default)]
    pub queue_capacity: usize, // `queue_capcity: 64` is ignored and this becomes 0
}
```

```rust,ignore
// Good
#[derive(Deserialize)]
#[serde(tag = "policy", content = "config", rename_all = "snake_case", deny_unknown_fields)]
pub enum SchedulerConfig {
    RoundRobin(RoundRobinConfig),
    ResourceGroupRoundRobin(ResourceGroupRoundRobinConfig),
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RoundRobinConfig {
    pub queue_capacity: NonZeroUsize,
}
```

**Review.**
- Check every `#[derive(Deserialize)]` in the diff for `deny_unknown_fields`, especially types with
  `#[serde(default)]` fields, section structs, and structs wrapped by enum variants.
- Flag `#[serde(untagged)]`, externally tagged config enums, and a `HashMap<String, _>` or
  `#[serde(flatten)]` catch-all used for a closed set of keys; use a struct.
- A rename, a restructure, a new required field, or newly added `deny_unknown_fields` on a
  deserialized schema changes what every producer may send (Python config, templates, Compose, Helm,
  test configs). Mark the PR as breaking (MOD-2).

**Exceptions.** Leave the attribute off responses from third-party services, which must tolerate new
fields, and off partial mirrors of Python types that deliberately discard fields (the mirror's
docstring says so). It cannot be combined with `#[serde(flatten)]`. Use `untagged` only when the
variants' shapes cannot overlap, such as a string-or-number union. Don't write tests that check
unknown keys or unknown tags are rejected; that is declarative serde behavior.

See also: coding-style.md § Mirroring Python Types, coding-style.md § What deserves a unit test.

**Sources.**

- [spider `spider-scheduler/src/config.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/config.rs#L36-L50): `SchedulerConfig` adjacently tagged with `deny_unknown_fields`
- [spider `spider-scheduler/src/runtime.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/runtime.rs#L24-L40): `RuntimeConfig` has `#[serde(default)]` fields but no `deny_unknown_fields`
- [spider `spider-storage/src/config.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/config.rs#L74-L80): `DatabasePoolConfig` pairs struct-level `default` with `deny_unknown_fields`
- [spider `spider-storage/src/state/runtime.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/state/runtime.rs#L32-L40): `RuntimeConfig` has defaulted sections but no `deny_unknown_fields`
- [y-scope/spider#412](https://github.com/y-scope/spider/pull/412): externally tagged enum needs YAML tags; switches to adjacent tagging
- [y-scope/spider#433](https://github.com/y-scope/spider/pull/433): renaming config keys breaks old configs; Helm values updated in lockstep
- [y-scope/clp#1663](https://github.com/y-scope/clp/pull/1663#discussion_r2562757119): reviewer adds `deny_unknown_fields` to the API's `QueryConfig`
- [y-scope/clp#1828](https://github.com/y-scope/clp/pull/1828#issuecomment-3720487052): schema change without a Helm update fails deployments with "missing field"
- [y-scope/clp#2452](https://github.com/y-scope/clp/pull/2452#discussion_r3725303501): reviewer: the Rust mirror of the changed Python config wasn't updated
- [y-scope/clp#2613](https://github.com/y-scope/clp/pull/2613#discussion_r4383980759): reviewer adds `deny_unknown_fields` to a new job-config struct
- [y-scope/clp#2652](https://github.com/y-scope/clp/pull/2652): `QueryOutput` tagged by `type`; every config struct denies unknown fields
- [RustTraining rust-patterns-book § Enum Representations](https://microsoft.github.io/RustTraining/rust-patterns-book/ch11-serialization-zero-copy-and-binary-data.html#enum-representations): the four serde enum representations and when to use each

## BND-3: Guard read-then-write DB transitions in the statement itself

**Rule.** Write a state transition as one `UPDATE ... WHERE id = ? AND <every precondition>` and
check `rows_affected()`. The preconditions are the valid previous states and, where writers can be
superseded, the writer's session or fence. If a transaction must read a value before deciding what
to write, read it with `SELECT ... FOR UPDATE` (or `LOCK IN SHARE MODE` when nothing in the
transaction later writes that row). Failure paths are no exception: marking a job failed also names
the states it may move from. Each storage method is one transaction, and a failed call leaves no
side effects.

**Why.** In InnoDB and MariaDB, a plain `SELECT` inside a transaction reads a snapshot and takes no
lock. The team once assumed otherwise, and the resulting inconsistent status check needed a
dedicated fix ([y-scope/clp#2045](https://github.com/y-scope/clp/pull/2045)). Read, check in Rust,
then write is a TOCTOU race, and upgrading a shared lock to an exclusive one deadlocks under
concurrency, which is why spider's transitions bind both the expected and the target state
([y-scope/spider#283](https://github.com/y-scope/spider/pull/283#discussion_r2921926472)). An
ownership check done only in memory let a superseded storage process keep committing transitions
after its replacement took over, so jobs ran twice; the fix fences every write in SQL (issue
[y-scope/spider#520](https://github.com/y-scope/spider/issues/520), fixed in
[y-scope/spider#532](https://github.com/y-scope/spider/pull/532)). In clp, marking a query job failed
"regardless of its current status" could overwrite a terminal `Cancelled` set by the API server
([y-scope/clp#2513](https://github.com/y-scope/clp/pull/2513#discussion_r4077243068)).

```rust,ignore
// Bad
let state: JobState = sqlx::query_scalar("SELECT `state` FROM `jobs` WHERE `id` = ?")
    .bind(job_id)
    .fetch_one(&mut **tx)
    .await?;
if !state.can_transition_to(JobState::Running) {
    return Err(DbError::InvalidJobState(job_id));
}
sqlx::query("UPDATE `jobs` SET `state` = ? WHERE `id` = ?")
    .bind(JobState::Running)
    .bind(job_id)
    .execute(&mut **tx)
    .await?;
```

```rust,ignore
// Good
let result = sqlx::query("UPDATE `jobs` SET `state` = ? WHERE `id` = ? AND `state` = ?")
    .bind(JobState::Running)
    .bind(job_id)
    .bind(JobState::Ready)
    .execute(&mut **tx)
    .await?;
if result.rows_affected() != 1 {
    return Err(classify_failed_transition(tx, job_id).await);
}
```

**Review.**
- In every read-then-write transaction, ask which lock each read holds. Flag a decision made from an
  unlocked `SELECT`, an `UPDATE` whose `WHERE` omits the expected state or the writer's fence, and
  an `UPDATE` that ignores `rows_affected()`.
- Treat a `rows_affected()` mismatch as a corruption error such as `CorruptedDbState`, not a silent
  skip. A second "confirmation" `SELECT` that could only disagree if the DB were corrupt adds round
  trips and locks without adding safety.
- Flag a storage method split into several transactions without a measured reason and a docstring
  stating what a partial failure leaves behind.
- Flag `ON UPDATE CURRENT_TIMESTAMP` on columns with a meaning (`end_at`, `death_confirmed_at`);
  write them explicitly in the transition. Flag vendor-only SQL such as `INSERT ... RETURNING` in
  crates that support both MariaDB and MySQL; use `last_insert_id()`.

**Exceptions.** Large `IN` lists may be batched in bounded transactions; the method's docstring then
says it is not atomic.

See also: coding-style.md § SQL and Database Patterns, DEF-2 (the same race in memory).

**Sources.**

- [y-scope/clp#2045](https://github.com/y-scope/clp/pull/2045): a plain read takes a snapshot, not a lock; adds `LOCK IN SHARE MODE`
- [y-scope/clp#2038](https://github.com/y-scope/clp/pull/2038#discussion_r2856964175): reviewer assumes the unlocked status read already holds an `S` lock
- [y-scope/spider#283](https://github.com/y-scope/spider/pull/283#discussion_r2921926472): pass expected and target states for one conditional update, avoiding lock-promotion deadlocks
- [y-scope/spider#292](https://github.com/y-scope/spider/pull/292#discussion_r3041909365): reviewer objects to splitting a method into non-atomic transactions
- [y-scope/spider#314](https://github.com/y-scope/spider/pull/314#discussion_r3149589314): reviewer: name it `death_confirmed_at`, without `ON UPDATE CURRENT_TIMESTAMP`
- [y-scope/spider#450](https://github.com/y-scope/spider/pull/450): replaces MariaDB-only `RETURNING id` with `last_insert_id()` for MySQL
- [y-scope/spider#493](https://github.com/y-scope/spider/pull/493#discussion_r4090973454): select-then-insert races, and deadlocks on gap locks
- [y-scope/spider#520](https://github.com/y-scope/spider/issues/520): an in-memory-only session check lets a superseded process keep committing
- [y-scope/spider#532](https://github.com/y-scope/spider/pull/532): fences every database write with the storage session
- [y-scope/spider#540](https://github.com/y-scope/spider/pull/540): multi-job updates in one fenced, state-guarded statement or transaction
- [y-scope/spider#557](https://github.com/y-scope/spider/pull/557): commits up to 256 planned events in one fenced transaction
- [y-scope/clp#2513](https://github.com/y-scope/clp/pull/2513#discussion_r4077243068): the precondition must be checked even when marking a job failed
- [y-scope/clp#2513](https://github.com/y-scope/clp/pull/2513#pullrequestreview-5286744460): `from: None` overwrote terminal statuses; a locked read reports which failure applied
- [y-scope/clp#2617](https://github.com/y-scope/clp/pull/2617): `request_cancellation` reads and updates the status in one transaction
- [y-scope/spider#373](https://github.com/y-scope/spider/pull/373#discussion_r3539743682): a confirmation `SELECT` is meaningless; check the affected-row count instead
- [spider `spider-storage/src/db/mariadb/tree_transition.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/db/mariadb/tree_transition.rs#L366-L378): `UpdateStatement::ensure_every_row_matched` turns a guarded-update mismatch into `CorruptedDbState`

## BND-4: Convert wire messages to domain types in one fallible layer

**Rule.** Convert each protobuf or other wire message into its domain type in exactly one place, a
`TryFrom` impl or a `RequestUnpack::unpack` in the crate that owns the proto types (MOD-4). A
missing sub-message, an unset `oneof`, or an `Unspecified = 0` enum value maps to a named error
variant; integer widths change with `try_from` (TYPE-8); the result is a struct with named fields,
not a tuple. In the outbound direction, keep an `Option` as an `Option` (proto `optional`) instead
of applying `unwrap_or_default`.

**Why.** In proto3 every message field is optional and every enum defaults to 0, so an outdated or
buggy client sends `None` or `Unspecified` without any warning. `unwrap_or_default` there makes a
bad request look valid, and `as` wraps or truncates silently: a client's `task_index: -1` becomes
`18446744073709551615`. On the way out, the execution manager's
`serialized_outputs.unwrap_or_default()` means storage cannot tell `None` from `Some(vec![])`, so it
cannot enforce the trait's documented rule that commit and cleanup tasks report no outputs. A tuple
such as `(SessionId, JobId, TaskId, TaskInstanceId, Vec<u8>)` lets two handlers destructure the
fields in different orders without a compiler error;
[y-scope/spider#471](https://github.com/y-scope/spider/pull/471) turned such a tuple into
`NextTaskRequestPayload` for that reason.

```rust,ignore
// Bad
impl From<proto::ExecutionContext> for ExecutionContext {
    fn from(context: proto::ExecutionContext) -> Self {
        Self {
            task_index: context.task_index as usize,
            timeout_policy: context.timeout_policy.map(Into::into).unwrap_or_default(),
        }
    }
}
```

```rust,ignore
// Good
impl TryFrom<proto::ExecutionContext> for ExecutionContext {
    type Error = Error;

    fn try_from(context: proto::ExecutionContext) -> Result<Self, Self::Error> {
        let task_index = usize::try_from(context.task_index)
            .map_err(|_| Error::TaskIndexOutOfRange(context.task_index))?;
        let timeout_policy = context.timeout_policy.ok_or(Error::TimeoutPolicyMissing)?;
        Ok(Self {
            task_index,
            timeout_policy: timeout_policy.try_into()?,
        })
    }
}
```

**Review.**
- Flag `.unwrap_or_default()`, `.expect(..)`, and `as` casts on proto fields (clippy's pedantic
  `cast_sign_loss` and `cast_possible_truncation` catch the casts), and any read of a raw proto
  field outside the unpack layer. A client's input must never be able to panic the server.
- Flag `type Unpacked = (..)` with three or more values or with two values of the same type, and
  opaque `bytes` fields carrying what should be a typed message. Each hand-written conversion gets
  one rejection test per error variant.
- Keep unpacking a pure translation. Don't reject a field there because one backend doesn't support
  it yet; that backend returns a typed `Unsupported` error itself
  ([y-scope/spider#471](https://github.com/y-scope/spider/pull/471)).

**Exceptions.** A domain-to-wire conversion that cannot fail on any supported target may use
`expect("...")` stating why.

See also: coding-style.md § API design (named fields over positional tuples), coding-style.md § What
deserves a unit test.

**Sources.**

- [spider `spider-proto-rust/src/unpack/mod.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-proto-rust/src/unpack/mod.rs#L31-L48): `RequestUnpack`, the one fallible proto-to-native conversion layer
- [spider `spider-proto-rust/src/unpack/storage.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-proto-rust/src/unpack/storage.rs#L84-L113): `ReportTaskSuccessRequest` still unpacks into a five-value tuple
- [spider `spider-proto-rust/src/unpack/scheduler.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-proto-rust/src/unpack/scheduler.rs#L16-L44): `NextTaskRequestPayload`, a named-field struct instead of a tuple
- [spider `spider-proto-rust/src/job.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-proto-rust/src/job.rs#L23-L39): `TryFrom` maps `JobState::Unspecified` to a named error
- [spider `spider-execution-manager/src/client/storage.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/client/storage.rs#L78-L109): `report_task_success` requires `None` outputs for commit and cleanup tasks
- [spider `spider-execution-manager/src/client/grpc/storage.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/client/grpc/storage.rs#L91-L114): `serialized_outputs.unwrap_or_default()` erases `None` versus empty
- [y-scope/spider#353](https://github.com/y-scope/spider/pull/353): introduces `RequestUnpack` to convert proto requests into native types
- [y-scope/spider#354](https://github.com/y-scope/spider/pull/354): typed `ExecutionContext` via `TryFrom`, failing on missing nested messages
- [y-scope/spider#471](https://github.com/y-scope/spider/pull/471): unpacking yields `NextTaskRequestPayload`; the core, not the protocol, refuses groups

## BND-5: Load config and env vars at startup, and tell absent apart from invalid

**Rule.** Load and validate config in `main` or the component's factory function, return any error
from there, and pass the validated config down. When reading an env var, match on `VarError`: only
`NotPresent` may fall back to a default, while `NotUnicode`, a parse failure, or a partially set
group of variables is an error that names the variable. Resolve a "config value, else env" fallback
inside deserialization, and use an upstream crate's own loader and env-var names for its
credentials.

**Why.** The execution manager reads its resource-group credentials with
`from_env().inspect_err(..).ok()`. An operator who sets the ID but forgets the password gets one
warning and an execution manager that is not dedicated to any resource group, so it takes tasks from
all of them: a silent isolation failure. `map_err(|_| MissingEnvVar(..))` also reports a non-Unicode
value as "not set". A lazily initialized global that `expect`s moves a startup failure to whichever
request first touches it. Defining your own env-var names for a dependency's credentials gives two
schemas that drift apart
([y-scope/clp#2532](https://github.com/y-scope/clp/pull/2532#discussion_r4106135253)).

```rust,ignore
// Bad
let credentials = Credentials::from_env().ok();
let concurrency: usize = std::env::var("CONCURRENCY").ok().and_then(|v| v.parse().ok()).unwrap_or(8);
```

```rust,ignore
// Good
pub fn from_env() -> Result<Option<Credentials>, CredentialsError> {
    match (read_env(ID_ENV)?, read_env(PASSWORD_ENV)?) {
        (None, None) => Ok(None),
        (Some(id), Some(password)) => Ok(Some(Credentials::new(id, password.into()))),
        _ => Err(CredentialsError::PartiallySet),
    }
}

fn read_env(key: &'static str) -> Result<Option<String>, CredentialsError> {
    match std::env::var(key) {
        Ok(value) => Ok(Some(value)),
        Err(VarError::NotPresent) => Ok(None),
        Err(VarError::NotUnicode(_)) => Err(CredentialsError::NotUnicode(key)),
    }
}
```

**Review.**
- Flag `.ok()`, `.unwrap_or(..)`, and `map_err(|_| ..)` on env reads and their parsing, and a pass
  after loading that patches the config from env vars; use `#[serde(try_from = "Option<Raw>")]` on
  the field instead, as spider's `DatabaseCredentials` does.
- Flag `OnceLock`/`LazyLock` getters that read files or env vars, and service binaries that rebuild
  their config from many CLI flags: the CLI takes only a config path, and the serde config holds
  every sub-config
  ([y-scope/spider#346](https://github.com/y-scope/spider/pull/346#pullrequestreview-4546792735)).
- If an env key is optional by default but the operator listed it explicitly, log a warning when it
  is missing
  ([y-scope/spider#389](https://github.com/y-scope/spider/pull/389#discussion_r3573945411)).

See also: TEST-5 (testing env-dependent code without mutating the environment).

**Sources.**

- [spider `spider-execution-manager/src/config.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/config.rs#L38-L73): `runtime_config` turns any credential error into a warning and `None`
- [spider `spider-core/src/types/resource_group.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/types/resource_group.rs#L36-L60): `from_env` reports every `VarError` as `MissingEnvVar`
- [spider `spider-storage/src/config.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/config.rs#L82-L140): `DatabaseCredentials` resolves config, else env, via `try_from = "Option<RawCredentials>"`
- [spider `spider-execution-manager/src/client/scheduler.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/client/scheduler.rs#L31-L64): `next_task` without a resource group takes tasks from any group
- [y-scope/spider#341](https://github.com/y-scope/spider/pull/341#pullrequestreview-4493746031): reviewer: `create_runtime` takes the GC config, grouped into `RuntimeConfig`
- [y-scope/spider#346](https://github.com/y-scope/spider/pull/346#pullrequestreview-4546792735): reviewer: a serde `RuntimeConfig` instead of rebuilding config from CLI flags
- [y-scope/spider#379](https://github.com/y-scope/spider/pull/379): test driver's lazy singleton reads `SPIDER_CONCURRENCY`, defaulting to 8
- [y-scope/spider#389](https://github.com/y-scope/spider/pull/389#discussion_r3573945411): warn when an explicitly listed env key is unset
- [y-scope/spider#397](https://github.com/y-scope/spider/pull/397#pullrequestreview-4698875645): serde resolves optional config credentials, else env vars
- [y-scope/clp#2532](https://github.com/y-scope/clp/pull/2532#discussion_r4106135253): use Spider's own credential env-var names, as with AWS
- [y-scope/clp#2549](https://github.com/y-scope/clp/pull/2549#discussion_r4170140547): load credentials with `from_env()?` and propagate the error

## BND-6: Make every default an intended value, owned in one place

**Rule.** Use field-level `#[serde(default)]` only when `Default::default()` is the value you
actually want; otherwise use `default = "fn"` returning a validated type, or make the field
required. For a section whose fields all have defaults, put `#[serde(default)]` on the struct and
write one `impl Default`. When a downstream component owns the default, make the field `Option<T>`
and pass `None` through instead of copying its literal.

**Why.** `#[serde(default)] max_connections: usize` yields 0 when the key is missing: a pool that
hands out no connections, with no error. Without a struct-level default, `{"buffer_config":
{"timeout_sec": 100}}` is rejected with "missing field", because a nested object that is present
must list every field
([y-scope/clp#2150](https://github.com/y-scope/clp/pull/2150#discussion_r3015802782)). A copied
default drifts: Celery and clp-s each hard-coded a result limit of 1000, so changing one silently
made them disagree
([y-scope/clp#2503](https://github.com/y-scope/clp/pull/2503#discussion_r3900175343)).

```rust,ignore
// Bad
const DEFAULT_MAX_NUM_RESULTS: u32 = 1000; // copied from clp-s

#[derive(Deserialize)]
pub struct PoolConfig {
    #[serde(default)]
    pub max_connections: usize,
}

let max_num_results = config.max_num_results.unwrap_or(DEFAULT_MAX_NUM_RESULTS);
command.arg("--max-num-results").arg(max_num_results.to_string());
```

```rust,ignore
// Good
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PoolConfig {
    #[serde(default = "default_max_connections")]
    pub max_connections: NonZeroU32,
}

const fn default_max_connections() -> NonZeroU32 {
    NonZeroU32::new(64).expect("default max connections is non-zero")
}

if let Some(max_num_results) = config.max_num_results {
    command.arg("--max-num-results").arg(max_num_results.get().to_string());
}
```

**Review.**
- Flag `#[serde(default)]` on counts, capacities, or intervals where zero is invalid (TYPE-7), and
  `const DEFAULT_*` values that duplicate another component's default.
- Flag a nested config whose fields all have defaults but which has no struct-level
  `#[serde(default)]`.
- When a type mirrors an external schema, make a field `Option` only if the source allows it to be
  absent or null; a required collection is an empty `Vec`, not `None`
  ([y-scope/clp#2087](https://github.com/y-scope/clp/pull/2087#discussion_r2965812887)).

See also: coding-style.md § Mirroring Python Types (defaults kept in sync), MOD-2 (a changed default
is a breaking change).

**Sources.**

- [y-scope/clp#2150](https://github.com/y-scope/clp/pull/2150#discussion_r3015802782): reviewer: a partial `buffer_config` is rejected without struct-level default
- [y-scope/clp#2503](https://github.com/y-scope/clp/pull/2503#discussion_r3900175343): reviewer: let clp-s own the result-limit default instead of copying 1000
- [y-scope/clp#2087](https://github.com/y-scope/clp/pull/2087#discussion_r2965812887): reviewer: the Python field isn't nullable, so don't make it optional
- [y-scope/clp#1729](https://github.com/y-scope/clp/pull/1729#discussion_r2594209669): reviewer asks for struct-level `#[serde(default)]` on `ArchiveOutput`
- [spider `spider-execution-manager/src/config.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/config.rs#L88-L122): `max_log_line_bytes` defaults through a fn returning `NonZeroUsize`
- [spider `spider-storage/src/config.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/config.rs#L69-L80): defaulted `pool` section with struct-level `#[serde(default)]` and `Default`
- [RustTraining rust-patterns-book § Common serde Attributes](https://microsoft.github.io/RustTraining/rust-patterns-book/ch11-serialization-zero-copy-and-binary-data.html#common-serde-attributes): `default`, `default = "fn"` and `deny_unknown_fields`

## BND-7: Bound and tolerate untrusted byte streams

**Rule.** Before allocating from a length a peer sent, convert it with `usize::try_from` and compare
it with a configured maximum; when encoding, convert `len()` to the wire type with `try_from`. Cap
each item in a stream from a peer or child process (`LinesCodec::new_with_max_length`), and drop an
oversized item with a `warn` and continue at the next boundary. Decode opaque text payloads lossily,
borrowing when they are valid; identifiers and tokens must still fail a strict parse when invalid.

**Why.** `read_u32().await? as usize` followed by `vec![0u8; len]` lets any peer, or a single
flipped bit, make the process allocate 4 GiB. On the write side, `len() as u32` wraps and the frame
falls out of sync with its length prefix. One runaway line from a child process grows memory without
bound, and a reader that stops at the first oversize error loses all output after it. `FramedRead`
yields one `None` right after a decode error and then resumes, so that `None` must not be treated as
end of stream ([tokio-rs/tokio#3976](https://github.com/tokio-rs/tokio/issues/3976),
[y-scope/spider#418](https://github.com/y-scope/spider/pull/418)). Real log data contains invalid
UTF-8: strict decoding turned one bad line into a failed query, and `String::from_utf8_lossy` alone
was 2-4x slower on valid ASCII than trying `str::from_utf8` first
([y-scope/clp#2649](https://github.com/y-scope/clp/pull/2649#discussion_r4449178317)).

```rust,ignore
// Bad
let len = stream.read_u32().await? as usize;
let mut payload = vec![0u8; len];
stream.read_exact(&mut payload).await?;
let message = std::str::from_utf8(&payload).map_err(|_| ProtocolError::InvalidUtf8)?;
```

```rust,ignore
// Good
let len = usize::try_from(stream.read_u32().await?).map_err(|_| FrameError::TooLarge)?;
if len > self.max_frame_size {
    return Err(FrameError::TooLarge);
}
let mut payload = vec![0u8; len];
stream.read_exact(&mut payload).await?;
let message: Cow<'_, str> =
    std::str::from_utf8(&payload).map_or_else(|_| String::from_utf8_lossy(&payload), Cow::Borrowed);
```

**Review.**
- Flag `as usize` or `as u32` on lengths that cross the wire, allocations sized by a peer without a
  maximum, and unbounded `BufReader::lines()` or `LinesCodec::new()` over peer or child-process
  output.
- Flag strict UTF-8 decoding of opaque payload text that fails a whole stream, and an ID or token
  whose lossily decoded form is accepted without a strict parse (a replacement character must make
  it fail).
- Spawn child processes with `Command::new(bin).args(..)`, never `sh -c` with an interpolated
  string; set `kill_on_drop(true)`, and attach or log the captured stderr when the process fails.

See also: SRV-3 (caps on what a peer can size) and DEF-4 (checked slicing of decoded buffers).

**Sources.**

- [y-scope/spider#418](https://github.com/y-scope/spider/pull/418): capped `LinesCodec`, oversized lines dropped, `FramedRead`'s post-error `None` handled
- [spider `spider-execution-manager/src/process_pool.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/process_pool.rs#L436-L489): `forward_executor_logs` drops an oversized line with a `warn` and resumes
- [y-scope/clp#2649](https://github.com/y-scope/clp/pull/2649#discussion_r4438307065): reviewer: non-UTF-8 clp-s output fails strict decoding; decode lossily
- [y-scope/clp#2649](https://github.com/y-scope/clp/pull/2649#discussion_r4449178317): reviewer: try `str::from_utf8` first; lossy alone is 2-4x slower
- [clp `clp-rust-libs/query-result-listener/src/protocol.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/query-result-listener/src/protocol.rs#L284-L318): `read_str` caps the length, borrows valid UTF-8, else decodes lossily
- [clp `clp-tdl-package/src/task/query/search.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-tdl-package/src/task/query/search.rs#L534-L601): `run_clp_s_search` uses `Command::new(..).args(..)` and logs stderr on failure
- [tokio-rs/tokio#3976](https://github.com/tokio-rs/tokio/issues/3976): `Framed` keeps reading after a decode error instead of terminating

## BND-8: Keep secrets typed, unserialized, out of logs, and compared in constant time

**Rule.** Hold passwords and tokens as `secrecy::SecretString` or `SecretSlice<u8>`, and call
`expose_secret()` only where the value is used. Mark credential fields `#[serde(skip_serializing)]`
on any type that derives `Serialize`. Compare a supplied credential with the stored one using
`subtle::ConstantTimeEq`. Keep the wrapper on every internal API that carries the secret, down to
the call that sends or compares it. Don't log an access-granting value (a session token, a presigned
URL) on the success path.

**Why.** A plain `String` password leaks through `#[derive(Debug)]` into logs and panic messages,
and through re-serializing the config; `SecretString`'s `Debug` prints `[REDACTED]`. `==` on byte
strings may stop at the first differing byte, which leaks timing information. A valid session token
logged on every accepted connection lets anyone who can read the logs join that session
([y-scope/clp#2689](https://github.com/y-scope/clp/pull/2689)). A rejected, unknown token grants
nothing, so it may be logged. A wrapper protects only as far as it reaches: Spider's
`ExternalResourceGroupCredentials` keeps its password in a `SecretSlice`, so `Debug` redacts it, but
`Client::verify_resource_group` takes the password as a bare `Vec<u8>`. From that call on, a single
`?password` in a log line prints it.

```rust,ignore
// Bad
#[derive(Debug, Deserialize, Serialize)]
pub struct Credentials {
    pub username: String,
    pub password: String,
}

if stored_password == credentials.password { /* ... */ }
```

```rust,ignore
// Good
#[derive(Clone, Debug, Deserialize)]
#[serde(try_from = "Option<RawCredentials>")]
pub struct Credentials {
    pub username: String,
    pub password: SecretString,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct DatabaseConfig {
    pub host: String,
    #[serde(skip_serializing)]
    pub credentials: Credentials,
}

if !bool::from(stored_password.ct_eq(credentials.password.expose_secret().as_bytes())) {
    return Err(DbError::InvalidPassword(id));
}
```

**Review.**
- Flag `String` or `Vec<u8>` fields named `password`, `secret`, or `token` on types that derive
  `Debug` or `Serialize`, and `==` on credentials.
- Flag a secret that crosses a function boundary as a `Vec<u8>` or `String`, even between internal
  layers.
- Flag `tracing` fields that carry tokens or credentials on accept or success paths; log the peer
  address or task index instead.
- Flag `expose_secret()` results stored in a variable or struct that outlives the call that needs
  the value.

**Exceptions.** A wrapper has to prevent a real misuse.
[y-scope/clp#1704](https://github.com/y-scope/clp/pull/1704#discussion_r2590945683) dropped
`SecretString` from the AWS secret-key path, where the keys already arrive through environment
variables and the wrapper only added conversions. When a reviewer asks what a wrapper prevents, the
answer must be concrete.

**Sources.**

- [spider `spider-storage/src/config.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/config.rs#L32-L88): `credentials` is `skip_serializing`, its password a `SecretString`
- [spider `spider-storage/src/db/mariadb/resource_group.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/db/mariadb/resource_group.rs#L100-L123): `verify` compares the stored password with `ct_eq`
- [spider `spider-core/src/types/resource_group.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/types/resource_group.rs#L12-L20): the resource group password held as `SecretSlice<u8>`
- [y-scope/spider#397](https://github.com/y-scope/spider/pull/397): database credentials from env vars instead of plaintext config
- [y-scope/spider#469](https://github.com/y-scope/spider/pull/469#issuecomment-5527563360): maintainer agrees to make the password a `secrecy` secret
- [y-scope/spider#493](https://github.com/y-scope/spider/pull/493#discussion_r4100744256): reviewer's rewrite checks the stored password with `ct_eq`
- [y-scope/clp#2689](https://github.com/y-scope/clp/pull/2689): listener logs omit valid session tokens; only unknown tokens are named
- [spider `spider-client/src/client.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-client/src/client.rs#L217-L240): `verify_resource_group` takes the password as a bare `Vec<u8>`
- [y-scope/spider#292](https://github.com/y-scope/spider/pull/292#discussion_r3041915941): the password check uses `subtle::ConstantTimeEq`
- [y-scope/clp#1704](https://github.com/y-scope/clp/pull/1704#discussion_r2590945683): reviewer: `SecretString` only adds hassle on the AWS key path

## BND-9: Treat wire status codes as a contract, and keep client-facing errors coarse

**Rule.** Give each status code one meaning across the whole system, decode statuses into the
client's domain error in a single `status_to_error` function, and change the server mapping and the
client decoder in the same PR. Reserve `UNAVAILABLE` for "retry later, the request itself was fine"
(a lost connection, a server shutting down), never for an application error. Answer "not found" and
"wrong credential" for a protected resource with the same `UNAUTHENTICATED`, and answer internal
failures with a fixed `INTERNAL` message while logging the detail on the server.

**Why.** Storage used to return `UNAVAILABLE` for a stale session and for a fatal cache error, so
the execution manager couldn't tell "reconnect" from "your request is wrong". When
[y-scope/spider#358](https://github.com/y-scope/spider/pull/358) moved stale sessions to
`NOT_FOUND`, the client's catch-all `_ => Server(..)` arm would have silently absorbed the new code
and broken stale-session recovery had the decoder not changed in the same PR. Separate not-found and
bad-password replies let a caller enumerate resource groups, and internal error strings expose SQL,
schema, or cache state.

```rust,ignore
// Bad
StorageServerError::StaleSession(_) => Status::unavailable("stale session"),
StorageServerError::Db(DbError::ResourceGroupNotFound(id)) => {
    Status::not_found(format!("resource group {id} not found"))
}
other => Status::internal(format!("{other:?}")),
```

```rust,ignore
// Good
match error {
    error @ StorageServerError::Db(
        DbError::ResourceGroupNotFound(_) | DbError::InvalidPassword(_),
    ) => {
        tracing::warn!(error = % error, "Invalid resource group.");
        Status::unauthenticated("invalid resource group")
    }
    StorageServerError::StaleSession(_) => Status::not_found("stale storage session"),
    StorageServerError::Stopping => Status::unavailable("storage service is shutting down"),
    error @ (StorageServerError::Cache(_) | StorageServerError::Db(_)) => {
        tracing::warn!(error = % error, "Unexpected internal error.");
        Status::internal("storage service internal error")
    }
}

fn status_to_error(status: &Status) -> StorageResponseError {
    match status.code() {
        Code::NotFound => StorageResponseError::StaleSession(status.message().to_owned()),
        Code::InvalidArgument => StorageResponseError::InvalidInput(status.message().to_owned()),
        Code::Unavailable => StorageResponseError::Transport(status.message().to_owned()),
        _ => StorageResponseError::Server(status.message().to_owned()),
    }
}
```

The server side names every remaining variant instead of ending in a catch-all (ERR-6). The client
decoder may end in `_`, because `tonic::Code` is a foreign enum, as long as the fallback is the
conservative `Server` error.

**Review.**
- Flag RPC methods that inspect `status.code()` themselves, and any server-side change to a status
  code without the matching change to the client decoder. Ask for one decoder test per mapped code
  (TEST-3).
- Flag `Status::unavailable` for anything but retryable unavailability, and
  `Status::internal(e.to_string())` or `{e:?}` sent to clients.
- Flag error responses or client-visible messages that reveal whether a protected resource exists.

See also: ERR-6 (translating errors in one exhaustive place).

**Sources.**

- [y-scope/spider#353](https://github.com/y-scope/spider/pull/353): `UNAUTHENTICATED` for unknown group or bad password; opaque `INTERNAL` otherwise
- [y-scope/spider#354](https://github.com/y-scope/spider/pull/354): adds the client's `status_to_error`; stale sessions were still `UNAVAILABLE`
- [y-scope/spider#358](https://github.com/y-scope/spider/pull/358): reserves `UNAVAILABLE` for transport errors and updates the client decoder
- [y-scope/spider#359](https://github.com/y-scope/spider/pull/359#discussion_r3488354927): reviewer: the client handler ignores `UNAVAILABLE`'s reserved meaning
- [y-scope/spider#364](https://github.com/y-scope/spider/pull/364#discussion_r3525523065): reviewer: per-service handlers, everything else through one default handler
- [y-scope/spider#369](https://github.com/y-scope/spider/pull/369#discussion_r3525908337): reviewer: the client-side status handling belongs in the same PR
- [y-scope/spider#464](https://github.com/y-scope/spider/pull/464): one `UNAUTHENTICATED` for a wrong resource group ID or password
- [spider `spider-storage/src/grpc.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/grpc.rs#L162-L230): task-instance error handler: `NOT_FOUND` for stale sessions, rest to the default
- [spider `spider-execution-manager/src/client/grpc/storage.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/client/grpc/storage.rs#L142-L161): `status_to_error` decodes each code, falling back to `Server`
- [spider `spider-execution-manager/src/client/grpc/liveness.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/client/grpc/liveness.rs#L96-L113): liveness `status_to_error`; its fallback is `Transport`, not `Server`

## BND-10: Read DB rows through typed projections and re-validate them as persisted data

**Rule.** Fetch each multi-column query into a `#[derive(sqlx::FromRow)]` projection struct whose
named fields have domain types, and bind and decode status enums through `sqlx::Type`. Convert the
row with a consuming `into_*(self) -> Result<Domain, DbError>` that runs the same validating
constructors used for client input, mapping their failure to `DbError::CorruptedDbState`. Do type
conversions and formatting in Rust, not in SQL.

**Why.** Positional tuple rows put column order in two places and break silently when someone
reorders the `SELECT`. Persisted data can be corrupted or written by an older version, so skipping
validation on the read path lets broken invariants into the cache. The right error category depends
on where the data came from, and only the call site knows that: a blanket `From<JobSubmissionError>
for ServerError::BadRequest` would report a corrupted row as a client mistake, so
[y-scope/spider#351](https://github.com/y-scope/spider/pull/351#discussion_r3470399072) maps it to
`CorruptedDbState` on recovery and to `BadRequest` on submission. Formatting in SQL (`DATE_FORMAT`,
`ROUND`, `FROM_UNIXTIME(? / 1000.0)`) splits the type contract across two languages and makes
clients re-parse values, and in
[y-scope/clp#2197](https://github.com/y-scope/clp/pull/2197#discussion_r3069536389) a
vendor-specific aggregate (`ANY_VALUE`) failed on MariaDB.

```rust,ignore
// Bad
let rows = sqlx::query_as::<_, (JobId, i32, String, Vec<u8>)>(QUERY).fetch_all(&pool).await?;
for (id, state, graph, inputs) in rows { /* which column is which? state is a raw i32 */ }
```

```rust,ignore
// Good
#[derive(sqlx::FromRow)]
struct RecoverableJobRowProjection {
    id: JobId,
    state: JobState,
    serialized_task_graph: String,
    serialized_job_inputs: Vec<u8>,
}

impl RecoverableJobRowProjection {
    fn into_recoverable_job(self) -> Result<RecoverableJob, DbError> {
        let graph = TaskGraph::from_json(&self.serialized_task_graph).map_err(DbError::corrupted)?;
        let inputs = rmp_serde::from_slice(&self.serialized_job_inputs).map_err(DbError::corrupted)?;
        let submission = ValidatedJobSubmission::create(graph, inputs).map_err(DbError::corrupted)?;
        Ok(RecoverableJob { id: self.id, state: self.state, submission })
    }
}
```

Here `DbError::corrupted` wraps any error's message in `DbError::CorruptedDbState`.

**Review.**
- Flag tuple `query_as` with three or more columns, `row.try_get("col")`, `.bind(status as i32)`,
  and SQL-side formatting or rounding.
- Flag a blanket `From` that turns a validation error into a client-facing error when the same
  validator also runs on DB reads; map the error at each call site (ERR-8).
- A numeric code shared with another system (a C++ enum value stored in a column) is a named
  constant with the column's width (`i8` for `TINYINT`), whose docstring names the definition it
  must stay in sync with.

See also: coding-style.md § SQL and Database Patterns, coding-style.md § Avoid hardcoded state
values, TYPE-5 (one row type per query shape).

**Sources.**

- [y-scope/spider#339](https://github.com/y-scope/spider/pull/339#pullrequestreview-4471850284): reviewer adds `RecoverableJobRowProjection` to make the query readable
- [y-scope/spider#351](https://github.com/y-scope/spider/pull/351#discussion_r3470399072): reviewer: map `JobSubmissionError` to `CorruptedDbState` on recovery
- [y-scope/spider#351](https://github.com/y-scope/spider/pull/351#discussion_r3470408829): reviewer: forward the same error as `BadRequest` on submission
- [y-scope/spider#353](https://github.com/y-scope/spider/pull/353): a database-minted duplicate job ID is internal, not a client-facing error
- [y-scope/spider#285](https://github.com/y-scope/spider/pull/285#discussion_r2972593594): reviewer: no hard-coded `'Ready'`; derive the state enum's SQL mapping
- [spider `spider-storage/src/db/mariadb/job.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/db/mariadb/job.rs#L296-L342): `RecoverableJobRowProjection` re-runs `ValidatedJobSubmission::create` as `CorruptedDbState`
- [spider `spider-storage/src/db/mariadb/scheduler.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/db/mariadb/scheduler.rs#L60-L90): `SchedulerRowProjection` re-validates the stored host as a `Host`
- [y-scope/clp#2197](https://github.com/y-scope/clp/pull/2197#discussion_r3068016843): reviewer: derive `sqlx::FromRow` instead of mapping with `try_get`
- [y-scope/clp#2197](https://github.com/y-scope/clp/pull/2197#discussion_r3069560459): reviewer: drop SQL `ROUND` and `FROM_UNIXTIME`; bind typed values
- [y-scope/clp#2420](https://github.com/y-scope/clp/pull/2420#discussion_r3654294879): reviewer: add a struct for the row projection
- [y-scope/clp#2513](https://github.com/y-scope/clp/pull/2513#discussion_r3963842747): reviewer: bind job status through `sqlx::Type`, not an enum-to-int cast
- [y-scope/clp#2058](https://github.com/y-scope/clp/pull/2058#discussion_r2877153900): reviewer: `i8` for a `TINYINT` column, as a named constant

# Modules, crates and API surface

A crate's visibility markers, re-exports and `Cargo.toml` are its API. They decide what other code
can depend on, and so what you can no longer change freely. Every item that is wider than it needs
to be is a promise someone else can rely on, and every dependency edge that points the wrong way
turns the next refactor into a change across several crates. The rules below keep the public surface
small and deliberate, put each piece of code in the one crate that owns it, and make contract
changes visible before they break a consumer in another repository or another language.

## MOD-1: Give every item the narrowest visibility its intended callers need

**Rule.** Start every item private. Widen it to `pub(super)` or `pub(crate)` only as far as a real
caller needs, and make it `pub` only when it belongs to the crate's external API. In a package
delivered as a binary, even one with a `lib.rs` that its `src/bin/` targets use, only what those
targets call is `pub`.

**Why.** Every `pub` item is a contract. Other crates can depend on it, and narrowing it later is a
breaking change. A `pub` item in `api-server`, which is not delivered as a library, promises an API
to consumers that don't exist, and readers can no longer tell the real entry points from the
helpers. Rust privacy is per module, not per type. Developers coming from C++ often make a field
`pub` to imitate `friend`, which lets any crate break the type's invariants. Putting the two types
in the same module gives the same access and exports nothing.

```rust,ignore
// Bad: `timeline/bucket.rs`
pub struct Bucket {
    pub count: u64,
}

impl Bucket {
    pub fn try_from_aggregation_document(document: &Document) -> Result<Self, Error> { /* ... */ }
}
```

```rust,ignore
// Good
pub struct Bucket {
    count: u64,
}

impl Bucket {
    pub const fn count(&self) -> u64 {
        self.count
    }

    pub(super) fn try_from_aggregation_document(document: &Document) -> Result<Self, Error> { /* ... */ }
}
```

**Review.**
- For each new `pub` item, ask who outside the crate calls it. If nobody does, or the package is a
  binary whose `src/bin/` targets don't call it, ask for `pub(crate)` or narrower.
- Flag a `pub` field that exists only so a sibling type can write it. The fix is to move the two
  types into one module, or to add a narrow method.
- Flag internal DTOs, parsing helpers, encodings and test structs that are `pub`.

See also: OBJ-1 (private fields protect invariants).

**Sources.**

- [y-scope/clp#2578](https://github.com/y-scope/clp/pull/2578#discussion_r4503774877): reviewer narrows `Bucket::try_from_aggregation_document` to `pub(super)`
- [y-scope/clp#2690](https://github.com/y-scope/clp/pull/2690#discussion_r4530585669): `SseEncoding` should be crate-public, since `api-server` isn't delivered as a library
- [y-scope/clp#2564](https://github.com/y-scope/clp/pull/2564#discussion_r4253602162): reviewer flags a `pub` struct that is only for internal use
- [RustTraining c-cpp-book § `friend` and Access Control → Module Visibility](https://microsoft.github.io/RustTraining/c-cpp-book/ch18-cpp-rust-semantic-deep-dives.html#friend-and-access-control--module-visibility): same-module access replaces `friend`

## MOD-2: Treat every contract change as breaking, and make the breakage loud rather than tolerated

**Rule.** Mark a PR breaking (`!`, with a migration note) when it changes any of these: the public
items of a crate consumed from another repository; a serialized format (DB schema or JSON/msgpack
column, task input, wire protocol, FFI entry points); or a user-visible config, including an added
or removed key, a renamed variant or a changed default. Before merging, list every producer and
consumer of the format, including non-Rust ones, and either update them or file tracked issues.
Readers of a format that has changed reject the old shape. They don't quietly accept it.

**Why.** The Rust compiler can't see a Python or WebUI producer. In
[y-scope/clp#2652](https://github.com/y-scope/clp/pull/2652#pullrequestreview-5729998540), the typed
`QueryJobConfig` with `deny_unknown_fields` broke the MCP server, which still wrote the old flat
config, so its searches would fail on new deployments. The failure was loud, so it was found in
review and tracked ([y-scope/clp#2656](https://github.com/y-scope/clp/issues/2656)). A tolerant
reader would have run an empty query in silence. Users who never set a field still depend on its
default. Raising a buffer threshold 16x can run memory-constrained systems out of memory with no
change to their config. A `pub` item that no other repository consumes is not a contract, so
changing it doesn't need `!`.

```rust,ignore
// Bad: every field optional, unknown fields ignored
#[derive(Deserialize)]
pub struct QueryJobConfig {
    pub query_string: Option<String>,
    pub begin_timestamp: Option<i64>,
    pub end_timestamp: Option<i64>,
    pub max_num_results: Option<u32>,
}
```

```rust,ignore
// Good: a writer still on another shape fails to deserialize
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct QueryJobConfig {
    #[serde(default = "QueryJobConfig::default_datasets")]
    pub datasets: Vec<DatasetName>,
    pub query: SearchQuery,
    pub output: QueryOutput,
}
```

**Review.**
- For any change to a serde type stored in a database or sent over the wire, ask for the list of
  writers and readers across languages. A Rust build that compiles is not evidence of compatibility.
- Treat a changed `#[serde(default = ...)]` value, a renamed `#[serde(rename)]` or a new required
  field as breaking. Check the title for `!` and the description for an `[!Important]` migration
  note, and check that the chart and image versions are bumped: the publish workflow skips a Helm
  chart whose version didn't change, while CI still reports success.
- Flag `#[non_exhaustive]` on enums that only our own crates consume. It makes adding a variant
  non-breaking by switching off exhaustiveness checking in every other crate, which removes the
  compile error that would have forced each consumer to handle the new state.

**Exceptions.** The RustTraining books recommend `#[non_exhaustive]` for public enums. That advice
fits a crate published for third parties that mirrors a vocabulary outside our control and expected
to grow, such as an external API's status codes.

See also: pr-review.md § PR Title Convention, Common Review Checks #10, BND-2 (strict schemas) and
BND-6 (defaults).

**Sources.**

- [y-scope/clp#2652](https://github.com/y-scope/clp/pull/2652#pullrequestreview-5729998540): reviewer finds the MCP server still writes the old flat config
- [y-scope/clp#2656](https://github.com/y-scope/clp/issues/2656): tracks MCP server searches failing on the new `QueryJobConfig`
- [y-scope/clp#2564](https://github.com/y-scope/clp/pull/2564#discussion_r4253602162): `ArchiveMetadata` is internal, so replacing its field isn't breaking
- [y-scope/clp#2620](https://github.com/y-scope/clp/pull/2620#discussion_r4403220812): reviewer asks to mark a partitioning behaviour change as breaking
- [y-scope/clp#1965](https://github.com/y-scope/clp/pull/1965#discussion_r2788682533): a 16x default threshold may crash memory-constrained deployments
- [y-scope/clp#1965](https://github.com/y-scope/clp/pull/1965#pullrequestreview-3781975663): maintainers confirm the changed default is breaking and add `!`
- [y-scope/clp#1962](https://github.com/y-scope/clp/pull/1962): renames the `ec2` auth variant to `default`, marked breaking
- [y-scope/spider#464](https://github.com/y-scope/spider/pull/464#discussion_r3897792061): reviewer asks to mark the storage and protocol changes breaking
- [y-scope/spider#418](https://github.com/y-scope/spider/pull/418): Helm chart version bump required, or publishing silently skips it
- [y-scope/spider#409](https://github.com/y-scope/spider/pull/409): a new FFI entry point, marked breaking with a migration note
- [RustTraining type-driven-correctness-book § `#[non_exhaustive]` for Evolving Enums](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch11-fourteen-tricks-from-the-trenches.html#trick-3--non_exhaustive-for-evolving-enums): the `#[non_exhaustive]` advice the Exceptions narrow
- [RustTraining rust-patterns-book § Public API Design Checklist](https://microsoft.github.io/RustTraining/rust-patterns-book/ch15-crate-architecture-and-api-design.html#public-api-design-checklist): recommends `#[non_exhaustive]` on public enums (see Exceptions)

## MOD-3: Declare each dependency once, pin cross-repo ones to a commit, and bump every reference together

**Rule.** Declare every external crate and every git dependency once, in the root
`[workspace.dependencies]`. Members use `{ workspace = true }` and only add features. Pin a git
dependency on a sibling repository to a `rev`, never a branch. When you bump it, update every
artifact built from that repository (Cargo, Dockerfiles, Compose and Helm image tags) in the same
PR. Prefer a mature, widely used crate over a newer one that exposes `unsafe` interfaces or says it
isn't production-ready.

**Why.** Versions pinned per crate drift apart. The clp workspace once had `tokio` at both 1.49.0
and 1.52.3, which meant duplicate builds and a separate edit per crate for every bump. Tracking
`main` lets an upstream merge break us with no change on our side. A partial bump fails silently. In
[y-scope/clp#2532](https://github.com/y-scope/clp/pull/2532#issuecomment-5908243126), one Dockerfile
kept an older Spider worker image that ignored the resource-group env vars, so dedicated workers
registered as general and nothing reported an error. A dependency with an `unsafe` API hands its
memory-safety obligations to our code. A deprecated but widely used crate is still safer than a
maintained alternative with a thousandth of the users.

```toml
# Bad: `components/foo/Cargo.toml`
spider-client = { git = "https://github.com/y-scope/spider.git", branch = "main" }
tokio = { version = "1.49.0", features = ["rt"] }
```

```toml
# Good: root `Cargo.toml`
[workspace.dependencies]
spider-client = { git = "https://github.com/y-scope/spider.git", rev = "278d06f81fe0fd0ff62292ee8c6f4cd63a529bfc" }
tokio = "1.52.3"

# `components/foo/Cargo.toml`
tokio = { workspace = true, features = ["rt"] }
```

**Review.**
- Flag a `version =` or `git =` in a member manifest.
- On a cross-repo bump, grep the repository for the old revision and image tag. Every hit must
  change in the PR, and the PR is a candidate for `!` (MOD-2).
- Flag a dependency that isn't the obvious mature crate when the PR description gives no reason for
  choosing it.

See also: coding-style.md § Dependencies (exact patch versions, sorted, no unused entries).

**Sources.**

- [y-scope/clp#2471](https://github.com/y-scope/clp/pull/2471): moves every crate version into `[workspace.dependencies]`
- [y-scope/clp#2532](https://github.com/y-scope/clp/pull/2532#pullrequestreview-5360553746): reviewer asks to pin Spider to a commit instead of `main`
- [y-scope/clp#2532](https://github.com/y-scope/clp/pull/2532#issuecomment-5908243126): one Dockerfile's Spider worker image was left unpinned
- [y-scope/clp#2549](https://github.com/y-scope/clp/pull/2549#discussion_r4170144866): the Spider bump changes the DB schema, so mark it breaking
- [y-scope/clp#2375](https://github.com/y-scope/clp/pull/2375#discussion_r3814730160): prefer `zstd` over `libzstd-rs-sys`, which has `unsafe` APIs and isn't production-ready
- [y-scope/clp#2312](https://github.com/y-scope/clp/pull/2312#issuecomment-4650233848): a deprecated but widely used crate beats a little-used alternative
- [y-scope/spider#285](https://github.com/y-scope/spider/pull/285#discussion_r2970704684): reviewer asks to lock dependencies to exact patch versions
- [y-scope/spider#289](https://github.com/y-scope/spider/pull/289): locks `serde` to 1.0.228

## MOD-4: Place code by dependency direction, and share it once a second consumer needs it

**Rule.** Keep the crate graph layered. The internal utils crate depends on no other workspace
crate. The core domain crate depends only on utils and its derive crate, and stays
protocol-agnostic. The protocol crate holds only generated code and the `From`/`TryFrom` impls
between wire and domain types. A client trait lives in the crate that consumes it, next to its
implementation. A helper moves down into a shared crate when a second crate uses it. Until then it
stays with its only consumer and that consumer's tests.

**Why.** Depending on `spider-storage` to reuse one struct pulls in its whole DB stack and can
create a dependency cycle. A domain crate that depends on protobuf types forces every protocol
change on consumers that never speak gRPC, and it mixes domain invariants with wire details such as
`Unspecified` or optional sub-messages. The conversions satisfy the orphan rule when they live in
the protocol crate, because the generated types are local there, so no wrapper types are needed. A
helper moved into a shared crate too early, like `scan_prefix` in
[y-scope/clp#2224](https://github.com/y-scope/clp/pull/2224#discussion_r3144459192), also loses the
test infrastructure (localstack) that its only consumer already had.

```toml
# Bad: `spider-scheduler/Cargo.toml`
[dependencies]
spider-storage = { workspace = true } # only for `RegisteredScheduler`
```

```toml
# Good: `RegisteredScheduler` lives in `spider-core`
[dependencies]
spider-core = { workspace = true }
spider-proto-rust = { workspace = true }
```

**Review.**
- For each new `[dependencies]` edge between workspace crates, ask what is used across it. If it is
  one type, ask for that type to move down.
- Flag `prost`/`tonic` imports in a domain crate, and wire conversions defined outside the protocol
  crate (BND-4).
- Flag a component-specific trait placed in the protocol or core crate. The fix is
  `consumer/src/xxx_client/{mod.rs (trait), grpc.rs (impl)}`.

**Exceptions.** A planned PR series that adds the second consumer soon may move the code early. Say
so in the PR description.

See also: coding-style.md § Reusable code belongs in `clp-rust-utils`. That section says where
shared code goes, and this rule says when code counts as shared.

**Sources.**

- [y-scope/spider#333](https://github.com/y-scope/spider/pull/333#pullrequestreview-4422940472): a component's client trait stays in its consumer crate, not the proto crate
- [y-scope/spider#340](https://github.com/y-scope/spider/pull/340#pullrequestreview-4489303309): restructures the client as `storage_client/{mod.rs, grpc.rs}`
- [y-scope/spider#347](https://github.com/y-scope/spider/pull/347#pullrequestreview-4519930341): moves `RegisteredScheduler` into `spider-core` rather than depending on `spider-storage`
- [y-scope/spider#355](https://github.com/y-scope/spider/pull/355): `spider-utils` depends on no Spider crate; `spider-core` builds on it
- [y-scope/spider#362](https://github.com/y-scope/spider/pull/362): config loader moves into `spider-utils` once a second service needs it
- [y-scope/clp#2224](https://github.com/y-scope/clp/pull/2224#discussion_r3144459192): keep `scan_prefix` in `log-ingestor`, its only consumer, with localstack tests
- [y-scope/clp#2655](https://github.com/y-scope/clp/pull/2655): a crate is shared if other crates depend on it and nothing deploys it
- [spider `spider-proto-rust/src/lib.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-proto-rust/src/lib.rs#L3-L51): generated code plus wire/domain conversion modules only
- [spider `spider-utils/Cargo.toml`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-utils/Cargo.toml#L10-L21): `[dependencies]` lists no workspace crate

## MOD-5: Make `mod.rs` a table of contents: declarations and named re-exports only

**Rule.** A multi-file module's `mod.rs` (or parent file) only declares submodules and re-exports
items by name: `pub use` for the API and `pub(crate) use` for crate-internal entry points. A
submodule that only organises files stays private. Use `pub mod` only for a namespace that is itself
part of the API. Never write `pub use child::*`.

**Why.** A glob re-export publishes every `pub` item ever added to the child, so a new helper joins
the crate's API without showing up in any diff. Public file-organising submodules let siblings and
other crates reach into each other's internals. Before
[y-scope/clp#2713](https://github.com/y-scope/clp/pull/2713), `connection` and `cursor` sat beside
`session` at the crate root, so `session` and `connection` depended on each other's internals
through `pub(crate)` items. Named re-exports document the contract in one place, and they let the
files behind the module be rearranged without touching any caller.

```rust,ignore
// Bad
pub mod connection;
pub mod cursor;
pub mod registry;

pub use registry::*;
```

```rust,ignore
// Good: `session/mod.rs`
mod cancellation_guard;
mod connection;
mod cursor;
mod open_session;
mod registry;

pub(crate) use connection::serve;
pub use open_session::OpenSession;
pub(crate) use registry::SessionRegistry;
```

**Review.**
- Flag `pub use ...::*`, and `pub mod` on a submodule that only exists to organise files.
- When a large file is split into a module directory, check that nothing new became visible outside
  the parent. Items that tests in sibling files use get `pub(super)`, not `pub(crate)`.
- Ask for the split to land as a move-only PR, separate from any behaviour change. Verify it with
  `git diff --color-moved` and an unchanged test list.

See also: coding-style.md § Module Organization.

**Sources.**

- [y-scope/clp#2713](https://github.com/y-scope/clp/pull/2713): turns `session` into a module that owns `connection` and `cursor`
- [y-scope/spider#382](https://github.com/y-scope/spider/pull/382): converts multi-file modules to the `mod.rs` layout
- [y-scope/spider#542](https://github.com/y-scope/spider/pull/542): move-only split of `db/mariadb.rs`, checked with `git diff --color-moved`
- [y-scope/spider#555](https://github.com/y-scope/spider/pull/555): `mod.rs` holds only submodule declarations and named re-exports
- [clp `clp-rust-libs/query-result-listener/src/session/mod.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/query-result-listener/src/session/mod.rs#L3-L19): private submodules with named `pub` and `pub(crate)` re-exports

## MOD-6: Give each shared type one owning crate and one import path

**Rule.** Define a shared type in exactly one crate, and have every consumer import it from there. A
crate that other crates depend on doesn't `pub use` another workspace crate's type unless its own
public signatures need it (MOD-7). For a domain-specific name, rename the type at the import (`use
spider_core::types::id::JobId as SpiderJobId;`). A crate-internal re-export under that name from the
module that owns the concept is fine.

**Why.** If a type can be imported from several paths, consumers drift onto whichever path they
found first. Moving the type then breaks all of them, and it is no longer clear which crate owns its
invariants. In
[y-scope/spider#469](https://github.com/y-scope/spider/pull/469#discussion_r3985370201), the review
removed `spider-storage`'s re-export of `ExternalResourceGroupCredentials` once the type lived in
`spider-core`. Otherwise callers would have kept depending on the storage crate just to name a
credentials type.

```rust,ignore
// Bad: `spider-storage/src/db/mod.rs`
pub use spider_core::types::resource_group::ExternalResourceGroupCredentials;
```

```rust,ignore
// Good: consumers import it from the owner
use spider_core::types::resource_group::ExternalResourceGroupCredentials;
```

**Review.**
- Flag `pub use` of another workspace crate's type in a library's public API when none of the
  library's public signatures mention it.
- When a type moves, check that the old path is deleted rather than kept as a forwarding re-export.
  If another repository imported the old path, the PR is breaking (MOD-2).

See also: coding-style.md § Type Aliases for External Types, which applies the same one-owner
principle to third-party types.

**Sources.**

- [y-scope/spider#469](https://github.com/y-scope/spider/pull/469#discussion_r3985370201): reviewer removes `spider-storage`'s re-export of the moved credentials type
- [y-scope/clp#2087](https://github.com/y-scope/clp/pull/2087#discussion_r2965730998): move `JobId` to its owning module and re-export it as `IngestionJobId`
- [clp `query-coordinator/src/coordination.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/query-coordinator/src/coordination.rs#L37-L39): imports `JobId as SpiderJobId` and credentials from `spider_core`

## MOD-7: Give user-facing crates a small facade, and keep transport and generated types private

**Rule.** A crate meant for callers outside the workspace exposes a small facade (for example
`SpiderClient` and its builder) whose methods take and return domain types. It re-exports at the
crate root every type from an internal helper crate that a public signature mentions. Transport
clients, connection pools and generated-proto wrappers live in a private module.

**Why.** If the inner gRPC clients are public, users come to depend on transport details, and then
changing the connection pool or the proto layout needs a breaking release. If a public signature
mentions a type from an internal crate (`RetryConfig` from `spider-utils`) or a deep generated path
(`job_orchestration_service_client::JobOrchestrationServiceClient`) and that type isn't re-exported,
every caller has to add the internal crate as a dependency or spell out codegen paths, and any
codegen change breaks them.

```rust,ignore
// Bad: `spider-client/src/lib.rs`
pub mod client;
pub mod job;
pub mod resource_group;
```

```rust,ignore
// Good
mod client;
mod error;
mod grpc;

pub use client::SpiderClient;
pub use client::SpiderClientBuilder;
pub use error::ClientError;
pub use spider_utils::grpc::retry::RetryConfig;
```

**Review.**
- Read the crate root as a user would. Can every public signature be written using only the names it
  exports plus the domain crate users already depend on?
- Flag public items, docs or signatures that expose connection pools, channels, or generated gRPC
  clients and messages.

**Sources.**

- [y-scope/spider#363](https://github.com/y-scope/spider/pull/363#discussion_r3492747900): users shouldn't need to know the underlying client types
- [y-scope/spider#363](https://github.com/y-scope/spider/pull/363#discussion_r3492717206): group the gRPC clients in a crate-private `grpc` module
- [y-scope/spider#382](https://github.com/y-scope/spider/pull/382): hides deep tonic-generated paths behind tidy re-exports
- [y-scope/spider#396](https://github.com/y-scope/spider/pull/396): re-exports `SpiderClientBuilder` and `RetryConfig` from the crate root
- [spider `spider-client/src/lib.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-client/src/lib.rs#L10-L16): the crate-root facade (the Good example adapts it to MOD-5)
- [spider `spider-proto-rust/src/lib.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-proto-rust/src/lib.rs#L26-L51): flat re-exports of deep generated client and server paths

## MOD-8: Keep test-only code out of the production surface and dependency graph

**Rule.** Put test helpers in `#[cfg(test)]` modules. Gate a helper behind a `test-utils` Cargo
feature (`#[cfg(any(test, feature = "test-utils"))]`) only when another crate's tests use it, add
the feature in the same PR as that use, and enable it only from consumers' `[dev-dependencies]`.
Declare the helper's dependencies as `dep:` optional deps of the feature and again under
`[dev-dependencies]`, because `cfg(test)` does not turn the feature on. A `pub` item whose docstring
says "for tests" is not a gate.

**Why.** `#[cfg(test)]` does not cross crate boundaries, so helpers that other crates need tend to
become plain `pub`. `spider-core`'s `Id::random()` is public, so production code can create IDs that
collide with storage-assigned ones. It also makes `rand` a normal dependency of every crate built on
`spider-core`, although only tests call it. The opposite mistake is a speculative `test-utils`
feature that nothing uses. It adds public API and a build configuration that nobody runs.

```rust,ignore
// Bad: `spider-core/src/types/id.rs`, `rand` under `[dependencies]`
/// Creates a random ID for tests.
pub fn random() -> Self {
    Self::from(rand::random())
}
```

```rust,ignore
// Good: `[features] test-utils = ["dep:rand"]`, and `rand` also under `[dev-dependencies]`
#[cfg(any(test, feature = "test-utils"))]
pub fn random() -> Self {
    Self::from(rand::random())
}
```

**Review.**
- Flag `pub` items documented as test-only, and test-only crates (`rand`, mocks, fixtures) listed
  under `[dependencies]`.
- Flag a new `test-utils` or `test-hooks` feature that no other crate's tests use in the same PR.
  The fix is `#[cfg(test)]`.
- Check that the feature is enabled only under `[dev-dependencies]`, never under `[dependencies]`.

See also: coding-style.md § What deserves a unit test (no test-only seams), TEST-7 (enabling the
feature for a crate's own integration tests, and keeping mocks within the real contract).

**Sources.**

- [spider `spider-core/src/types/id.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/types/id.rs#L42-L48): `Id::random()` is `pub` and only documented as for tests (the Bad example)
- [spider `spider-core/Cargo.toml`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/Cargo.toml#L12): `rand` is a normal dependency of `spider-core`
- [y-scope/clp#2649](https://github.com/y-scope/clp/pull/2649#discussion_r4438381331): reviewer questions an unused `test-utils` feature; `#[cfg(test)]` suffices
- [y-scope/clp#2690](https://github.com/y-scope/clp/pull/2690#discussion_r4530585669): integration tests made `SseEncoding` `pub`; move them into `src/sse.rs`
- [clp `clp-rust-libs/query-result-listener/Cargo.toml`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/query-result-listener/Cargo.toml#L10-L29): `test-utils` feature, enabled for its own tests from `[dev-dependencies]`
- [clp `api-server/Cargo.toml`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/api-server/Cargo.toml#L46-L49): enables `test-utils` only under `[dev-dependencies]`

## MOD-9: Declare the intended visibility when staged code lands, and silence dead code with `expect`

**Rule.** When a library item or subsystem lands before its consumer, give its items the visibility
the final design calls for, not "private until used". Silence the interim dead-code warning on the
module declaration with `#[expect(dead_code, reason = "...")]`, never `#[allow(dead_code)]`. Use
`#[cfg_attr(not(test), expect(...))]` when the module's own tests use every item.

**Why.** If everything is private, reviewers can't tell which methods are the API and which are
helpers. If everything is `pub`, siblings start coupling to internals. An `allow` stays in the code
silently after it is no longer needed. An `expect` raises an "unfulfilled lint expectation" warning
as soon as the consumer lands, the lint task (`clippy --all-targets -- -D warnings`) rejects that
warning, and the `reason` tells the author which line to delete. A plain `expect` on a module whose
tests use every item is unfulfilled when the tests are built, so it raises the warning it was meant
to silence.

```rust,ignore
// Bad
#[allow(dead_code)]
pub mod job_registry;
```

```rust,ignore
// Good
#[cfg_attr(
    not(test),
    expect(dead_code, reason = "the core that consumes the registry has not landed yet")
)]
mod job_registry;
```

**Review.**
- Flag a new subsystem whose items are all private "because nothing calls them yet". Ask for their
  final visibility plus an `expect`.
- Flag `#[allow(dead_code)]`, and an `expect` with no `reason`.
- Check that the PR that wires up the consumer also deletes the `expect`.

**Exceptions.** This is the one sanctioned way to suppress a lint while code is being staged. Any
other `allow` or `expect`, and any clippy lint in particular, still follows coding-style.md §
Linting: fix the code, or ask first.

**Sources.**

- [y-scope/clp#2676](https://github.com/y-scope/clp/pull/2676#discussion_r4488093523): reviewer asks for final visibility instead of all-private, silencing `dead_code`
- [y-scope/clp#2690](https://github.com/y-scope/clp/pull/2690): the `sse` module expects `dead_code` outside tests until the endpoint lands
- [y-scope/spider#444](https://github.com/y-scope/spider/pull/444): items are `pub(super)` for the coming core, with `expect(dead_code, reason)`
- [y-scope/spider#449](https://github.com/y-scope/spider/pull/449): uses `cfg_attr(not(test), expect(...))` since its tests use every item
- [y-scope/spider#465](https://github.com/y-scope/spider/pull/465): the shared reader lands `pub(super)` before its second consumer

## MOD-10: Keep Cargo features additive and declare optional dependencies with `dep:`

**Rule.** A feature only adds capability. Enabling it never removes or changes behaviour that other
code relies on. Declare optional dependencies as `feature = ["dep:crate"]`, keep `default` minimal,
and make sure the crate builds both with no features and with all features.

**Why.** Cargo unifies features across the whole dependency graph. Once any one crate enables a
feature that changes behaviour, every crate gets the change, and a crate that never asked for it
breaks. A bare optional dependency also creates an implicit feature named after the dependency. That
leaks the dependency's name into the public feature set and makes renaming it a breaking change. Our
lint task builds only `--all-features`, so code behind `#[cfg(not(feature = "..."))]` and the
no-feature build go unchecked unless someone asks for them.

```toml
# Bad
[features]
derive = ["spider-tdl-derive"]
legacy-encoding = [] # switches the wire format when enabled
```

```toml
# Good: `spider-tdl/Cargo.toml`
[features]
default = []
derive = ["dep:spider-tdl-derive"]
```

**Review.**
- Flag `#[cfg(not(feature = "x"))]` code that is an alternative implementation rather than an absent
  capability.
- Flag optional dependencies declared without `dep:`, and features added to `default` without a
  reason.
- For a crate with two or more features, ask for `--no-default-features` and `--all-features` builds
  (or `cargo hack check --each-feature`) in CI or in the PR's testing notes.

**Sources.**

- [spider `spider-tdl/Cargo.toml`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-tdl/Cargo.toml#L6-L8): `default = []` and `derive = ["dep:spider-tdl-derive"]`
- [spider `taskfiles/lint.yaml`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/taskfiles/lint.yaml#L206-L215): clippy runs only with `--all-features`
- [RustTraining rust-patterns-book § Feature Flags and Conditional Compilation](https://microsoft.github.io/RustTraining/rust-patterns-book/ch15-crate-architecture-and-api-design.html#feature-flags-and-conditional-compilation): use `dep:` and keep `default` minimal
- [RustTraining engineering-book § Verifying Feature Combinations with `cargo-hack`](https://microsoft.github.io/RustTraining/engineering-book/ch09-no-std-and-feature-verification.html#verifying-feature-combinations-with-cargo-hack): build-check every feature combination

# Testing and observability for correctness

A test is worth having only if it fails when the behavior it covers breaks, and it must give the
same answer on every run, whether it runs alone or with the rest of the suite. Logs and traces do
the same job in production: they are the only evidence of which job failed and why. This section
covers how to make error paths, decisions, invariants, concurrency and async waits checkable and
deterministic, and how to make runtime events attributable. It builds on the testing rules in
coding-style.md (§ What deserves a unit test, § Assertions, § Coding-agent driven test case writing)
and does not restate them.

## TEST-1: Assert the exact outcome, not a proxy for it

**Rule.** On a failure path, assert the specific error variant and its payload, not `is_err()`. For
a rejected call, also assert that it changed no state. When a test reads a stream to its terminal
event, also assert that the next poll yields `None`.

**Why.** `is_err()` also passes when the code fails for the wrong reason. A framing error can hide
the missing bounds check the test was written for. A stale-state rejection can be misclassified as
an internal error that shuts down the service, which is what happened in
[y-scope/spider#515](https://github.com/y-scope/spider/issues/515). A rejected call that consumed a
queued item is a data-loss bug, and checking the variant alone does not catch it. A test that stops
reading at `Ended` will not notice a stream that keeps yielding events or never closes. Consumers
waiting for the end of that stream hang.

```rust,ignore
// Bad
#[tokio::test]
async fn get_job_outputs_rejects_unfinished_job() -> anyhow::Result<()> {
    let env = TestEnv::new().await?;
    let job_id = env.register_job().await?;
    assert!(env.service.get_job_outputs(job_id).await.is_err());
    Ok(())
}
```

```rust,ignore
// Good
#[tokio::test]
async fn get_job_outputs_rejects_unfinished_job() -> anyhow::Result<()> {
    let env = TestEnv::new().await?;
    let job_id = env.register_job().await?;

    let result = env.service.get_job_outputs(job_id).await;

    assert!(
        matches!(
            result,
            Err(StorageServerError::Cache(CacheError::StaleState(
                StaleStateError::JobNotSucceeded(JobState::Ready)
            )))
        ),
        "unexpected result: {result:?}"
    );
    assert_eq!(env.job_state(job_id).await?, JobState::Ready);
    Ok(())
}
```

**Review.**
- Flag `assert!(x.is_err())` and substring checks on `to_string()` in tests of error paths. If the
  error type is already `PartialEq`, the fix is `assert_eq!(result, Err(..))`. Otherwise use
  `matches!` with a `{result:?}` message, or `expect_err("...")` followed by destructuring the
  fields. Do not derive `PartialEq` on an error type just for tests.
- For a rejected mutation, ask for an assertion that the state survived, for example that the queued
  assignment can still be dequeued.
- After a terminal stream event, ask for `assert!(next_event(&mut events).await.is_none(), "the
  event stream should end after its last event")`.

**Exceptions.** A bare `is_err()` is fine only when every error is equally acceptable to the caller
and the test name says so.

See also: coding-style.md § Assertions, ERR-3 (if a test needs `to_string()`, a variant may be
missing).

**Sources.**

- [y-scope/spider#515](https://github.com/y-scope/spider/issues/515): a stale-state rejection was treated as internal and shut down storage
- [y-scope/spider#525](https://github.com/y-scope/spider/pull/525): the fix; its tests now expect the stale-state error
- [y-scope/spider#471](https://github.com/y-scope/spider/pull/471): a rejected dequeue in `dispatch_queue.rs` must leave the queued assignment in place
- [spider `spider-proto-rust/src/assignment.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-proto-rust/src/assignment.rs#L135-L164): conversion-error tests `matches!` the exact `Error` variant
- [spider `spider-core/src/types/io/mod.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/types/io/mod.rs#L582-L636): `expect_err`, then destructure and check the `WireError` fields
- [y-scope/clp#2705](https://github.com/y-scope/clp/pull/2705#pullrequestreview-5898835167): reviewer asks to assert the event stream ends after `End`

## TEST-2: Bound every wait in a test, and guard loops that must make progress

**Rule.** In a test, wrap every await on a synchronization point in `tokio::time::timeout` with a
named constant. That includes a pause hook being reached, a tracker draining, a `JoinHandle`, a
`recv`, and a call that should block. Use `try_recv()` for an event that should already have
happened by the time the awaited call returned. In a test loop that decodes until the input runs
out, assert that each iteration made progress.

**Why.** Tests of cancellation, shutdown and races wait for events that a bug may never produce.
Without a bound, the failure shows up as a CI job killed at its global limit, with no hint of which
wait hung. A decode loop whose decoder returns `Some` without consuming input never ends, and it
fills memory while it runs. In agent-driven test runs, this crashed the development VM twice
([y-scope/clp#2649](https://github.com/y-scope/clp/pull/2649#discussion_r4449297472)).

```rust,ignore
// Bad
service.cancel_job(job_id).await?;
assert_eq!(receiver.recv().await, Some(job_id));
pause.reached(1).await;
while let Some(frame) = Frame::decode(&mut buffer)? {
    frames.push(frame);
}
```

```rust,ignore
// Good
service.cancel_job(job_id).await?;
assert_eq!(receiver.try_recv(), Ok(job_id));
tokio::time::timeout(HOOK_TIMEOUT, pause.reached(1)).await?;
while let Some(frame) = Frame::decode(&mut buffer)? {
    frames.push(frame);
    assert!(frames.len() <= bytes.len(), "decoding should consume bytes");
}
```

**Review.**
- Search the test diff for a bare `.await` on `recv`, `reached`, `wait`, `join_next` or a
  `JoinHandle`. Ask for `timeout(NAMED_CONST, ..)` or `try_recv`.
- In a test of deadline logic, set the outer timeout well above the deadline under test (for example
  `DEADLINE * 10`). It then catches a hang without racing the behavior being tested.

See also: coding-style.md § Prefer real-time testing for complex async code.

**Sources.**

- [y-scope/spider#541](https://github.com/y-scope/spider/pull/541#discussion_r4384836843): reviewer asks for a timeout on every `pause.reached(1)`
- [y-scope/spider#555](https://github.com/y-scope/spider/pull/555): splits out `state/service/hooked_tests.rs`, whose hook waits take `HOOK_TIMEOUT`
- [y-scope/spider#341](https://github.com/y-scope/spider/pull/341#pullrequestreview-4493746031): reviewer replaces a `recv` that could block forever with `try_recv`
- [y-scope/spider#527](https://github.com/y-scope/spider/pull/527): deadline tests bound `wait_for_shutdown` at `TEST_DEADLINE * 10`
- [y-scope/spider#526](https://github.com/y-scope/spider/pull/526): test that sends never block runs under a `timeout`
- [y-scope/clp#2649](https://github.com/y-scope/clp/pull/2649#discussion_r4449297472): reviewer adds a progress assertion after a decode loop OOMed the VM

## TEST-3: Test each decision exhaustively, in the module that defines it

**Rule.** Test a mapping or classification function (status to error, state to action) where it is
defined, with a table that has one row for every input variant. Do not test it only through an outer
layer whose output merges variants, through a mock that re-implements its `match`, or through unit
tests of a wrapper that only forwards to it.

**Why.** In [y-scope/clp#2617](https://github.com/y-scope/clp/pull/2617#discussion_r4390410031), the
`Cancellable` and `CancellationRequested` cases both became HTTP 200. If `Pending` had mapped to the
wrong variant, cancel would have done nothing, and every HTTP-level test would still have passed. A
mock that copies the production `match` only tests the copy. A gRPC wrapper, or a service method
that only forwards to its DB connector, has no logic of its own. A mock-based unit test of it only
checks that the mock behaves like a mock.

```rust,ignore
// Bad
#[tokio::test]
async fn cancel_pending_query_returns_ok() -> anyhow::Result<()> {
    let app = app_with_job_status(QueryJobStatus::Pending);
    let response = app.oneshot(cancel_request(JOB_ID)?).await?;
    assert_eq!(response.status(), StatusCode::OK);
    Ok(())
}
```

```rust,ignore
// Good
#[test]
fn from_status_maps_every_status() {
    use Cancellability::{CancellationRequested, Cancellable, NotCancellable};
    for (status, expected) in [
        (QueryJobStatus::Pending, Cancellable),
        (QueryJobStatus::Running, Cancellable),
        (QueryJobStatus::CancelRequested, CancellationRequested),
        (QueryJobStatus::Cancelling, CancellationRequested),
        (QueryJobStatus::Cancelled, CancellationRequested),
        (QueryJobStatus::Succeeded, NotCancellable),
        (QueryJobStatus::Failed, NotCancellable),
        (QueryJobStatus::Killed, NotCancellable),
    ] {
        assert_eq!(Cancellability::from_status(status), expected, "status: {status:?}");
    }
}
```

**Review.**
- When a mapping's observable output merges several variants into one (HTTP codes, booleans), ask
  for a table test at the definition with a row per input. When the PR adds a variant to the input
  enum, check that the table gains a row. Deriving `PartialEq`/`Eq` on a plain value enum so it can
  be compared is fine.
- Test an HTTP or wire contract (status code, content type, which field the error names) once, at
  the router, with one invalid value per field, in a loop that puts the input in each assertion
  message. The value ranges themselves belong to the newtype's own tests.
- Ask for removal of mock-based tests of pure forwarding layers and protocol wrappers. Test the real
  connector in integration tests, and test mapping functions such as `status_to_error` once per
  status code (BND-9).

See also: coding-style.md § What deserves a unit test ("Test a behavior once, where it's defined");
pr-review.md § Flag tests that don't test the code's own logic.

**Sources.**

- [y-scope/clp#2617](https://github.com/y-scope/clp/pull/2617#discussion_r4390410031): reviewer asks for a per-status table test of `Cancellability` in `job_config/search.rs`
- [y-scope/clp#2581](https://github.com/y-scope/clp/pull/2581#discussion_r4516943742): one invalid value per field pins the router's HTTP contract
- [y-scope/spider#364](https://github.com/y-scope/spider/pull/364#discussion_r3517509984): reviewer rejects unit tests of the gRPC wrappers
- [y-scope/spider#358](https://github.com/y-scope/spider/pull/358): `status_to_error` gets one test per status code it maps
- [y-scope/spider#347](https://github.com/y-scope/spider/pull/347#pullrequestreview-4519930341): mock-DB tests of a forwarding service removed as testing only the mock

## TEST-4: Make concurrency tests contend, and make them reproducible

**Rule.** Give a race test real contention: a `multi_thread` runtime, enough concurrent callers to
overlap, a `Barrier` so they start together, several iterations with fresh keys, and a connection
pool large enough that it does not serialize the callers. Then assert that the outcomes agree. Draw
random sizes and interleavings from a fixed seed, and control when a dependency completes with gated
mocks (for example a semaphore), not with sleeps.

**Why.** Two sequential calls, or calls on a single-threaded runtime, never reach the duplicate-key,
deadlock or compare-and-swap retry branch, so the test passes while the race is still there.
Ordering by `sleep`, and randomness without a seed, make the test flaky and a failure impossible to
reproduce. Recording each item's expected owner at enqueue time, and checking it after the run,
catches lost and duplicated work.

```rust,ignore
// Bad
let (first, second) = tokio::join!(store.add_or_verify(group.clone()), store.add_or_verify(group));
assert_eq!(first?, second?);
```

```rust,ignore
// Good
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn concurrent_add_or_verify_converges_to_one_id() -> anyhow::Result<()> {
    const NUM_CONCURRENT_CALLS: usize = 16;
    const NUM_ITERATIONS: usize = 10;
    let store = TestStore::connect(u32::try_from(NUM_CONCURRENT_CALLS)?).await?;
    for _ in 0..NUM_ITERATIONS {
        let group = ResourceGroup::with_unique_name();
        let barrier = Arc::new(Barrier::new(NUM_CONCURRENT_CALLS));
        let mut tasks = JoinSet::new();
        for _ in 0..NUM_CONCURRENT_CALLS {
            let (store, group, barrier) = (store.clone(), group.clone(), Arc::clone(&barrier));
            tasks.spawn(async move {
                barrier.wait().await;
                store.add_or_verify(group).await
            });
        }
        let ids = tasks.join_all().await.into_iter().collect::<Result<Vec<_>, _>>()?;
        assert_eq!(ids, vec![ids[0]; NUM_CONCURRENT_CALLS]);
    }
    Ok(())
}
```

**Review.**
- Flag a race test built on `tokio::join!` of two calls, on the default current-thread runtime, or
  on a `sleep` to "let the other task finish".
- A stress test takes its seed as a parameter and includes it in assertion messages. Fault branches
  that are otherwise unreachable, such as a closed dispatch queue failing the tick, are driven
  through `#[cfg(test)]` hooks on the real type (see TEST-7).

**Sources.**

- [y-scope/spider#493](https://github.com/y-scope/spider/pull/493#discussion_r4089491840): reviewer asks for more concurrency in `tests/mariadb_test.rs` so adds actually race
- [spider `spider-scheduler/src/dispatch_queue.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/dispatch_queue.rs#L272-L388): `run_pair_consistency_stress`: seeded batch sizes, owner tagged at enqueue
- [spider `spider-scheduler/src/core_impl/inbound_queue_reader.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/core_impl/inbound_queue_reader.rs#L487-L497): semaphore-gated mock poll (`gate_ready_lane`, `admit_ready_poll`)
- [spider `spider-core/src/session.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/session.rs#L91-L105): `concurrent_advance_converges_to_max` on a `multi_thread` runtime
- [y-scope/spider#395](https://github.com/y-scope/spider/pull/395): property test checks every rescheduled task is dispatched exactly twice

## TEST-5: Keep tests independent of process-global and shared state

**Rule.** Do not mutate process-global state, such as environment variables or the current
directory, in tests. Pass the environment to a subprocess explicitly (`Command::envs`), and test the
code's own decision (which pairs it builds) from constructed inputs. Create filesystem state with
`tempfile`. Against a shared database, assert on the IDs the test created, never on global row
counts. Declare serialization on the test itself (`#[serial_test::serial]`,
`#[serial_test::file_serial]`), and mark tests that need infrastructure with
`#[ignore = "requires MariaDB"]`.

**Why.** Tests run concurrently on threads of one process. `std::env::set_var` races with every
other reader, and edition 2024 makes it `unsafe` for that reason. The usual
`// SAFETY: no other test reads this` is checked by nothing, and it stops being true as soon as
someone adds a test that reads the variable. A row count in a shared DB breaks as soon as another
test leaves rows behind. A nextest rule keyed on a `test_serial` name prefix cannot be seen when
reading the test, and it silently stops applying after a rename.

```rust,ignore
// Bad
#[test]
fn compress_forwards_credentials() {
    // SAFETY: no other test reads these vars.
    unsafe { std::env::set_var("AWS_ACCESS_KEY_ID", "key") };
    // ... run the code that reads the parent's environment
}
```

```rust,ignore
// Good
let child = Command::new(bin)
    .envs(auth.credential_env())
    .spawn()
    .context("failed to spawn clp-s")?;

#[test]
fn credential_env_contains_the_access_key_pair() {
    let auth = AuthConfig::credentials("key", "secret");
    assert_eq!(
        auth.credential_env(),
        [("AWS_ACCESS_KEY_ID", "key".to_owned()), ("AWS_SECRET_ACCESS_KEY", "secret".to_owned())]
    );
}
```

**Review.**
- Flag `set_var`/`remove_var`/`set_current_dir` in tests, fixed paths under `std::env::temp_dir()`,
  `len()` assertions on shared tables, and serialization rules in `.config/nextest.toml`.
- If there is no clean way to avoid the env mutation, drop the test rather than rely on an
  unenforced `SAFETY` comment.

**Exceptions.** When the behavior under test is the env read itself at a process boundary, such as
spider-storage reading DB credentials (BND-5), every test that touches the variable is `#[serial]`,
and a guard restores the variable before the first assertion so that a failed assertion cannot leak
it.

**Sources.**

- [y-scope/clp#2438](https://github.com/y-scope/clp/pull/2438#discussion_r3692334370): "I prefer not to add this test case since it mutates the env var"
- [clp `clp-tdl-package/src/task/compression/compress.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-tdl-package/src/task/compression/compress.rs#L708-L787): `run_clp_s` hands credentials to the child via `Command::envs`
- [y-scope/spider#397](https://github.com/y-scope/spider/pull/397): `src/config.rs` reads DB credentials from env, with env-mutating tests
- [y-scope/spider#299](https://github.com/y-scope/spider/pull/299#discussion_r3048927055): reviewer rejects a nextest rule keyed on a `test_serial` prefix
- [y-scope/spider#314](https://github.com/y-scope/spider/pull/314#discussion_r3162452837): a size check on a shared table breaks on rows left by other tests
- [y-scope/spider#339](https://github.com/y-scope/spider/pull/339#pullrequestreview-4471850284): reviewer adds `ignore` for MariaDB tests and `#[serial_test::file_serial]`
- [RustTraining rust-patterns-book § Test Fixtures and Setup](https://microsoft.github.io/RustTraining/rust-patterns-book/ch14-testing-and-benchmarking-patterns.html#test-fixtures-and-setup): per-test fixtures and a temp directory cleaned up on drop

## TEST-6: Take the current time, output streams and awaited futures as inputs of the decision logic

**Rule.** When a decision depends on the current time, an output stream or a future it waits on,
make it an input of the one production function: `gc_started_at: SystemTime`, a writer generic over
`AsyncWrite`, or the `JoinHandle` to await. Obtain the real value at the call site, for example
`SystemTime::now()` at the top of the loop or `tokio::io::stdout()` in `main`.

**Why.** A function that calls `SystemTime::now()` itself can be tested for a timeout only by
sleeping past a real deadline, so the test is slow and flaky. An actor hard-wired to `stdout()` can
be tested only on its happy path, yet its important behavior is the failure path: a broken pipe
cancels the runtime, which then drains before exit. When the time or the stream is an input, a test
can pass a deadline plus one millisecond, a writer that returns `BrokenPipe`, or
`std::future::pending()`, and reach each branch deterministically through the real entry point.
Reading the time once per cycle also means every entry in the cycle is judged against the same
instant. This is not the test-only seam that coding-style.md forbids. There is still one function,
the parameter is a real input of the decision rather than injected internal state, and production
supplies it.

```rust,ignore
// Bad
async fn run_gc_cycle(&mut self) -> Result<(), InternalError> {
    let now = SystemTime::now();
    // ... expire entries older than `now - soft_timeout`
}
```

```rust,ignore
// Good
async fn run_gc_cycle_at(&mut self, gc_started_at: SystemTime) -> Result<(), InternalError> {
    // ... expire entries older than `gc_started_at - soft_timeout`
}

// Run loop:
self.run_gc_cycle_at(SystemTime::now()).await?;

// Test:
pool.run_gc_cycle_at(registered_at + SOFT_TIMEOUT + Duration::from_millis(1)).await?;
```

**Review.**
- Flag `Instant::now()`/`SystemTime::now()`, `tokio::io::stdout()`, or a spawned task's handle
  buried inside decision logic whose timeout or failure branches are untested. The fix is to make
  the value a parameter of that one function.
- Prefer a plain value (`now`) over a `Clock` trait. Use a trait only when one call has to read the
  time repeatedly.
- Reject a `foo`/`foo_with_clock` pair, or a parameter that exists only to inject internal state.
  That is the seam coding-style.md forbids.

See also: coding-style.md § What deserves a unit test ("Don't add test-only seams to production
code").

**Sources.**

- [spider `spider-storage/src/task_instance_pool.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/task_instance_pool.rs#L390-L448): `run_gc_cycle_at(gc_started_at: SystemTime)`; the run loop passes `SystemTime::now()`
- [spider `spider-storage/src/state/job_cache_gc.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/state/job_cache_gc.rs#L212-L231): `run_gc_cycle_at(now: Instant)` judges expiry against the given instant
- [y-scope/spider#418](https://github.com/y-scope/spider/pull/418): log actor is generic over `AsyncWrite`, so tests inject `BrokenWriter`
- [y-scope/spider#527](https://github.com/y-scope/spider/pull/527): `wait_for_shutdown` takes the server's handle, so tests pass `pending()`
- [RustTraining rust-patterns-book § Mocking Strategies without Frameworks](https://microsoft.github.io/RustTraining/rust-patterns-book/ch14-testing-and-benchmarking-patterns.html#mocking-strategies-without-frameworks): passing the clock in so a test can fix the time

## TEST-7: Keep test doubles within the real contract, and gate test-only code out of production

**Rule.** Gate helpers, fixtures and doubles that exist only for tests as MOD-8 describes:
`#[cfg(test)]`, or `#[cfg(any(test, feature = "test-utils"))]` with optional dependencies when
integration tests or other crates need them. A mock implementation of a trait returns only the
errors that the trait method's `# Errors` section documents, and it uses `expect` when its own
bookkeeping is inconsistent.

**Why.** An ungated helper such as spider's `pub fn random()` on `Id` lets production code mint a
`JobId` that storage never assigned, and it drags `rand` into every downstream binary (MOD-8).
Gating turns that misuse into a compile error. A mock that returns an undocumented error, such as
`ResourceGroupNotFound` from `add_or_verify`, teaches callers and tests to handle a case the real
implementation never produces. It can also hide a missing branch for a case the real implementation
does produce.

```toml
# Bad: the crate's own integration tests need the feature
[[test]]
name = "integration"
required-features = ["test-utils"]
```

```toml
# Good: a dev-dependency on the crate itself turns the feature on for its tests
[features]
test-utils = ["dep:rand"]

[dev-dependencies]
spider-core = { path = ".", features = ["test-utils"] }
```

**Review.**
- Enable the feature for the crate's own integration tests with a dev-dependency on the crate
  itself, as above, not with `[[test]] required-features`, because a plain `cargo test -p <crate>`
  silently skips a target whose required features are off. Other crates enable it in their
  `[dev-dependencies]`. Verify with `cargo tree -e normal,build,features -i <crate>` that normal
  builds do not pull in `test-utils`.
- In a mock, flag `.ok_or(DomainError::..)?` on lookups in the mock's own maps. The fix is
  `.expect("indexed resource group must exist in the mock")`.
- Fixture helpers that take `&TestEnv` belong in `impl TestEnv` (coding-style.md § API design).
  Tests that use only the public API go in `tests/`, where the compiler ensures they use nothing
  private. A binary crate's tests stay in `src`.

**Exceptions.** Fault-injection hooks that must sit on production code paths stay behind a feature,
such as spider-storage's `test-hooks`. Without the feature, the hooks type is zero-sized and its
fault type has no values (`enum InjectedFault {}`, see TLC-5), so every `?` on a hook compiles away.
Hooks live on each runtime instance, not in globals. A test target that cannot run at all without
such a feature may use `required-features`. Gating code behind a feature does not make a forbidden
seam acceptable (coding-style.md § What deserves a unit test).

See also: coding-style.md § Panic in test helpers when the failure means the test is wrong.

**Sources.**

- [spider `spider-core/src/types/id.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/types/id.rs#L42-L48): ungated `pub fn random()`, documented as test-only
- [spider `spider-core/Cargo.toml`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/Cargo.toml#L12): `rand` is a normal dependency, so every binary pulls it in
- [clp `clp-rust-libs/query-result-listener/Cargo.toml`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/query-result-listener/Cargo.toml#L10-L29): `test-utils` feature enabled by a dev-dependency on the crate itself
- [y-scope/clp#2696](https://github.com/y-scope/clp/pull/2696): picks the self dev-dependency over `[[test]] required-features`, and says why
- [y-scope/clp#2664](https://github.com/y-scope/clp/pull/2664#discussion_r4474431710): reviewer asks to make the test-only encodings test config only
- [y-scope/clp#2690](https://github.com/y-scope/clp/pull/2690#discussion_r4530585669): a binary crate's tests belong in `src/sse.rs`, not `tests/`
- [y-scope/clp#2689](https://github.com/y-scope/clp/pull/2689#issuecomment-6745445395): public-API-only `FakeClpS` tests belong in `tests/`
- [y-scope/spider#541](https://github.com/y-scope/spider/pull/541): `test-hooks` feature; without it the hooks (`test_hooks/disarmed.rs`) are no-ops
- [y-scope/spider#493](https://github.com/y-scope/spider/pull/493#discussion_r4089475586): mock in `state/test_utils.rs` returns an error outside the trait contract
- [y-scope/spider#551](https://github.com/y-scope/spider/pull/551#discussion_r4437929238): reviewer asks to make a fixture helper a method of `TreeEnv`
- [y-scope/spider#557](https://github.com/y-scope/spider/pull/557#discussion_r4488738816): reviewer asks to make fixture helpers methods of `TestEnv`

## TEST-8: Assert invariants over every output of hand-written algorithms and decoders

**Rule.** For hand-written algorithms such as partitioning, scheduling or merging, assert the
invariants the code promises on every output: conservation, ordering, and the loop postcondition.
One hand-computed result is not enough. For hand-written decoders of external bytes, also test
inputs that arrive in pieces.

**Why.** An exact-output assertion covers only the one case someone worked out by hand, and it keeps
passing when the invariant breaks for any other input. An invariant assertion checks every case the
fixture produces, and generated inputs can drive it later. Off-by-one errors in partial-read
handling show up only at specific byte boundaries, so a test that hands the decoder the whole
message at once never reaches them.

```rust,ignore
// Bad
assert_eq!(partition(&objects, TARGET_ARCHIVE_SIZE).len(), 3);
```

```rust,ignore
// Good
let partitions = partition(&objects, TARGET_ARCHIVE_SIZE);
let mut unassigned: BTreeSet<&str> = objects.iter().map(|object| object.path.as_str()).collect();
for partition in &partitions {
    for object in &partition.objects {
        assert!(unassigned.remove(object.path.as_str()), "assigned twice or unknown: {}", object.path);
    }
    let (_, rest) = partition.objects.split_last().expect("partitions should be non-empty");
    let size_before_last: u64 = rest.iter().map(|object| object.size).sum();
    assert!(size_before_last < TARGET_ARCHIVE_SIZE, "partition: {partition:?}");
}
assert_eq!(unassigned, BTreeSet::new());
```

**Review.**
- For an incremental decoder, ask for a test that feeds the encoded message one byte at a time. It
  asserts `None` until the last byte, then the decoded value, and that any trailing bytes stay in
  the buffer. Repeat it for each length-header width (for example `[8, 32, 256, 65_536]`).
- For a hand-written codec or parser of untrusted input, a `proptest` that arbitrary bytes never
  panic and that `decode(encode(x)) == x` is cheap insurance, and proptest shrinks a failure to a
  minimal input. Compare decoded values, not hex dumps of the encoding, so that field order does not
  become part of the contract.
- Once the invariants are written, apply a deliberate regression (drop the last partial partition,
  assign an object twice) and confirm an assertion catches it (coding-style.md § Coding-agent driven
  test case writing).

**Exceptions.** Do not property-test or round-trip-test `#[derive(Serialize, Deserialize)]` types or
serde attributes. That is derived behavior (coding-style.md § What deserves a unit test).

See also: DEF-4 (checked decoding).

**Sources.**

- [y-scope/clp#2403](https://github.com/y-scope/clp/pull/2403#pullrequestreview-4739365794): reviewer adds exactly-once and loop-postcondition invariants to `partition.rs`, mutation-verified
- [y-scope/clp#2649](https://github.com/y-scope/clp/pull/2649#discussion_r4438333071): reviewer asks for a byte-at-a-time decoding test in `protocol.rs`
- [y-scope/clp#2375](https://github.com/y-scope/clp/pull/2375#discussion_r3815340863): compare decoded objects, not hex, so field order isn't contract
- [RustTraining rust-patterns-book § Property-Based Testing (proptest)](https://microsoft.github.io/RustTraining/rust-patterns-book/ch14-testing-and-benchmarking-patterns.html#property-based-testing-proptest): properties asserted over generated inputs
- [RustTraining engineering-book § Complementary Testing Tools](https://microsoft.github.io/RustTraining/engineering-book/ch04-code-coverage-seeing-what-tests-miss.html#complementary-testing-tools): a proptest that parsing arbitrary input never panics

## TEST-9: Log structured fields with the full error, and attach spans to spawned work with `.instrument`

**Rule.** Log identifiers, counts and errors as structured fields (`job_id = % job_id`,
`error = % e`), never interpolated into the message, and log the error itself rather than only its
kind. Attach a span to spawned or request-scoped async work with `.instrument(span)` or
`#[tracing::instrument(skip_all, fields(..))]`. Never hold a `span.enter()` guard across an
`.await`.

**Why.** Log pipelines can filter and aggregate fields. They cannot do that with values buried in
message text. A log line with only the error's kind drops the context needed to diagnose it. A
spawned task does not inherit its caller's span. The guard from `span.enter()` is `Send`, so
`tokio::spawn` accepts a future that holds it across `.await`, and clippy has no lint for it. While
the task is suspended, the span stays entered on that worker thread, so unrelated events logged
there are attributed to this job. (`.entered()` returns a guard that is not `Send`, so
`tokio::spawn` rejects it. It still compiles in a current-thread or `spawn_local` context.)
`#[instrument]` without `skip` records every argument with `Debug`, which can put a large buffer or
a credential into every event.

```rust,ignore
// Bad
tracing::warn!("Failed to dispatch job {} to scheduler {}: {}", job_id, scheduler_id, e);

async fn compress_job(job_id: JobId, job: Job) -> anyhow::Result<()> {
    let span = tracing::info_span!("compress", job_id = % job_id);
    let _guard = span.enter();
    compress(job).await
}
```

```rust,ignore
// Good
use tracing::Instrument;

tracing::warn!(
    job_id = % job_id,
    scheduler_id = % scheduler_id,
    error = % e,
    "Failed to dispatch the job."
);

let span = tracing::info_span!("compress", job_id = % job_id);
tokio::spawn(compress(job).instrument(span));
```

**Review.**
- Flag `format!`-style interpolation in `tracing` macros, `.enter()`/`.entered()` guards in `async`
  bodies, and `#[instrument]` without `skip`/`skip_all` on functions that take buffers, configs or
  secrets (BND-8).
- Use the same field name for the same identifier across a component, such as `job_id` and
  `scheduler_id`, so that one query finds every event for it.

**Exceptions.** A short synchronous function needs no span; a field on the event is enough. Spans
are not used in spider or clp yet, so add them to new long-lived spawned tasks rather than
retrofitting existing code all at once.

See also: coding-style.md § Log field formatting, § Error messages, ERR-5 (where to log).

**Sources.**

- [spider `spider-scheduler/src/runtime.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/runtime.rs#L148-L152): `tracing::error!` with `scheduler_id` and `error` as fields
- [spider `spider-storage/src/cache/tree/planner.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/cache/tree/planner.rs#L454-L459): `tracing::warn!` with `job_id` and sizes as fields
- [clp `clp-tdl-package/src/task/compression/mod.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-tdl-package/src/task/compression/mod.rs#L82-L84): commit failure logged with the job ID and full error as fields
- [y-scope/clp#2607](https://github.com/y-scope/clp/pull/2607): logs the full error for every 500 instead of an error kind
- [RustTraining async-book § tracing + `#[instrument]`: Structured Logging for Async](https://microsoft.github.io/RustTraining/async-book/ch12-common-pitfalls.html#tracing--instrument-structured-logging-for-async): `#[instrument(skip(..), fields(..))]` spans stay open across `.await`
- [RustTraining c-cpp-book § The `tracing` crate — structured logging with spans](https://microsoft.github.io/RustTraining/c-cpp-book/ch17-4-logging-and-tracing-ecosystem.html#the-tracing-crate--structured-logging-with-spans): key-value fields instead of string interpolation

## TEST-10: Pin type-level guarantees with compile-fail tests

**Rule.** When correctness depends on some code *not* compiling, keep it that way with a
compile-fail test. Examples: a typestate method that does not exist in some state (TLC-9), a
single-use token that is not `Clone` (TLC-4), a macro that rejects a bad signature or duplicate
names. Use `trybuild` with checked-in `.stderr` files for macros or several cases. A `compile_fail`
doctest is enough for one case on a library type.

**Why.** These guarantees can disappear without any test failing. A later `#[derive(Clone)]`, a
field made `pub`, or a method moved into a generic `impl<S>` block still compiles and passes every
runtime test. Spider's `#[task]` and `register_tdl_package!` guarantees are tested only on the
accepting side. The duplicate-name check is tested only as a runtime panic of its helper, so a
refactor that drops the generated `const _` assertion would keep every test green. A `compile_fail`
doctest passes when the snippet fails for any reason, including a typo. Its `compile_fail,E0599`
error code is checked only by a nightly rustdoc, so a stable `cargo test` ignores it. `trybuild`
compares the full compiler output with the `.stderr` file on any toolchain.

```rust,ignore
// Bad
#[test]
#[should_panic(expected = "duplicate task name")]
fn assert_unique_task_names_panics_on_duplicate() {
    assert_unique_task_names(&["compress", "compress"]);
}
```

```rust,ignore
// Good
#[test]
fn task_macros_reject_invalid_definitions() {
    let cases = trybuild::TestCases::new();
    cases.compile_fail("tests/ui/first_param_not_task_context.rs");
    cases.compile_fail("tests/ui/duplicate_task_names.rs");
}
```

**Review.**
- When a PR introduces a typestate, a single-use token, a sealed trait or a validating macro, ask
  what stops someone from bypassing it, and ask for one minimal compile-fail case per guarantee.
- For a `compile_fail` doctest, confirm once that it fails for the stated reason: make the guarded
  property hold (for example, add the `#[derive(Clone)]`) and check that the doctest then fails.
- A new `trybuild` dev-dependency follows the usual pinning rules (coding-style.md § Dependencies).
  Its `.stderr` files change with the compiler version, so regenerate them with `TRYBUILD=overwrite`
  on the toolchain CI uses, and review the diff.

**Exceptions.** Do not write compile-fail tests for guarantees the language gives every type, such
as use-after-move. Test only guarantees that the code's own design creates. This does not conflict
with coding-style.md § Coding-agent driven test case writing ("Do not test what the type system ...
makes unreachable"). That rule is about runtime tests of impossible arms; this one checks that the
type system keeps those arms impossible.

**Sources.**

- [spider `spider-tdl/tests/test_task_macro.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-tdl/tests/test_task_macro.rs): `#[task]` tests cover only definitions that compile
- [spider `spider-tdl/src/register.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-tdl/src/register.rs#L91-L95): `register_tdl_package!` emits the `const _` name-uniqueness assertion
- [spider `spider-tdl/src/register.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-tdl/src/register.rs#L254-L268): duplicate names tested only as a runtime panic of the helper
- [RustTraining type-driven-correctness-book § Compile-Fail Tests with `trybuild`](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch14-testing-type-level-guarantees.html#compile-fail-tests-with-trybuild): `trybuild` cases with checked-in `.stderr` expectations

# Review checklist

Walk this list against the diff, alongside the Common Review Checks in `pr-review.md`. Each line
names the pattern to flag; the rule it cites explains why and what fix to ask for. Cite the rule ID
in the review comment. A line that doesn't match the diff can be skipped, but don't stop at the
first section: most bugs these rules prevent sit in code that looks unrelated to the PR's topic.

## Checklist: Type safety

- **TYPE-1**: A raw value travels past the boundary with a `validate(&self) -> Result<()>`, an
  "assumes consistent" docstring, an `unreachable!("rejected by validation")`, or a check or clamp
  repeated downstream, instead of being parsed once into a `Validated*`/`TryFrom`/`FromStr` type
  that the APIs take.
- **TYPE-2**: A type with a fallible constructor can be built without the check: `pub` fields, a
  plain `derive(Deserialize)` (needs `serde(try_from)`), an infallible `From<raw>`, an
  `impl Into<Validated>` parameter, an unchecked `Default`, `DerefMut`, or a proto/sqlx conversion
  that uses a struct literal.
- **TYPE-3**: Two same-typed values with different meanings share a signature, tuple or struct, or a
  new `pub type XxxId = u64/String` appears, or a peer system's ID is stored as a raw `u64`; use a
  newtype or `Id<TypeMarker>` and the peer's own type.
- **TYPE-4**: Absence is encoded as a sentinel (`0`, `-1`, `""`, `MAX`, a defaulted ID,
  `Option<bool>`), or a parse/read error is hidden with
  `unwrap_or(0)`/`unwrap_or_default()`/`.ok()`; use `Option<T>` (or `Option<NonZero*>`) and `?`.
- **TYPE-5**: Mutually exclusive modes are modeled as several `Option`s, co-varying `bool`s,
  reserved index constants or a state-encoding nullable column, or values that must come from the
  same creation are passed as a tuple or as separate `Option`s; use one enum or a bundled type.
- **TYPE-6**: A closed set of values is a `String`/integer compared with literals, has a
  hand-written string-to-int table, or is parsed with a catch-all `_ =>` default; parse it into an
  enum at the boundary, reject unknown values with an error that names them, and match exhaustively.
- **TYPE-7**: A must-be-positive capacity, interval, divisor or limit is a plain integer (or
  documents "must be positive"), or a range check can never fire for the type; use `NonZero*` or a
  width/sign that fits every consumer (DB, BSON, C++).
- **TYPE-8**: A narrowing, sign-changing, platform-width or float-to-int `as` cast, or `as` where
  `From` exists; use `From`/`try_from` with a value-carrying error, or `expect` only when this code
  guarantees the value fits.
- **TYPE-9**: A function returns `bool`/`Result<bool>` whose `true`/`false` are two states, or a
  positional `bool` is stored in a tuple/queue/message, or a full-status parameter is followed by
  `assert!(is_terminal())` with 3+ or data-carrying terminal states; use a named outcome enum (named
  `bool` parameters stay).
- **TYPE-10**: A `Vec<u8>` whose encoding lives only in a comment, `from_utf8_lossy` on non-text
  bytes, or a hand-built encoded buffer; use an encoding newtype built by the encoder and read
  through `decode()`.

## Checklist: Type-level constraints, traits and generics

- **TLC-1**: Two or more raw `u64`/UUID ID parameters, or a new `pub type XxxId = u64`, where a
  phantom-marker `Id<Marker>` alias belongs.
- **TLC-1**: An ID marker missing a trait the `Id` wrapper derives (silently not `Copy`/`Hash`), or
  bounds on the wrapper's struct definition.
- **TLC-2**: A component bounded on the aggregate trait or the concrete backend when it uses one
  role trait.
- **TLC-2**: A method that turns a restricted capability (reader, role handle) into a broader one
  (`Reader::writer()`).
- **TLC-3**: `unreachable!`/`let .. else { panic! }` on an enum variant the code statically knows;
  ask for an associated type plus `From` at the boundary.
- **TLC-3**: An API returning `serde_json::Value`/`Vec<u8>`/an erased enum that every caller decodes
  itself.
- **TLC-4**: A permit/proof type with `Clone`/`Copy`/`Default`/`Deserialize`, `pub` fields or a
  public constructor.
- **TLC-4**: A spend-once operation on a shared `&self` handle, an async spend that updates its
  accounting before a cancellable `.await`, or a `bool` parameter asserting a security or readiness
  fact.
- **TLC-5**: A trait generic parameter that each type implements only once (should be an associated
  type).
- **TLC-5**: A placeholder error type on an infallible impl, or `#[cfg]` repeated at every
  optional-hook call site, instead of `Infallible`/an empty enum.
- **TLC-6**: A struct field or `&self` factory for a stateless strategy; ask for a type-only trait
  and an empty enum.
- **TLC-7**: A by-value `self` method on a trait used as `dyn` (needs `self: Box<Self>`, or
  `where Self: Sized` if it's only for concrete types).
- **TLC-8**: The same inherent method copied across crates where one extension trait with a blanket
  impl belongs.
- **TLC-8**: A blanket impl over a broad bound (`Debug`, `Display`, `Serialize`) for behavior some
  types must override.
- **TLC-8**: A mock made `Clone` only to satisfy `Trait + Clone` where a forwarding `Arc<T: ?Sized>`
  impl belongs (OWN-6).
- **TLC-9**: A runtime state guard repeated in three or more methods of a compile-time-ordered
  protocol.
- **TLC-9**: A typestate wrapper with `Option` fields plus `expect`, or a transition taking
  `&mut self`; and no typestate asked for two-phase or runtime-loaded state.

## Checklist: Defensive programming

- **DEF-1**: A `?` on a request-dependent check after the first mutation, or a config value reaching
  a panicking constructor (`mpsc::channel(0)`, `Semaphore::new`) after a durable write.
- **DEF-1**: An unavoidable partial mutation (DB then cache) with no armed drop guard that fails the
  service if dropped.
- **DEF-2**: `contains_key`/`get` then `insert` on a concurrent map, `load` then `store` on an
  atomic, or a read and a write under separate lock guards, instead of `entry()`, one CAS or one
  guard.
- **DEF-3**: Unchecked `+`/`-`/`*`/`<<`/`fetch_sub` on input-derived values or meaningful counters
  (lossy `as` casts are TYPE-8).
- **DEF-3**: `Instant + Duration` with a caller-controlled duration, or a test gated on
  `debug_assertions`/`should_panic(expected = "overflow")`.
- **DEF-4**: `[]` indexing, range slicing or `as usize` on an input-derived offset/length, or a
  manual `pos + len > len` check before a slice.
- **DEF-4**: `with_capacity`/`reserve`/`vec![_; n]` sized by an input-declared count without capping
  to remaining bytes.
- **DEF-5**: An `unsafe` block without a `// SAFETY:` invariant, or a `# Safety` section on a safe
  `fn`.
- **DEF-5**: An `extern "C"` export (including macro-generated) without `catch_unwind`, or an owned
  FFI buffer without `Drop`.

## Checklist: Server design

- **SRV-1**: A cursor, epoch or session ID written with a raw `set`/`store` or assigned from an
  `Option` fetch, or epoch-stamped work checked only once.
- **SRV-2**: `unwrap_or(<literal>)`, `unwrap_or_default()` or `_ => <valid variant>` when parsing
  external data, or a request option silently ignored or downgraded.
- **SRV-2**: User payload quoted/wrapped to make it parse, or a request string joined into a path
  without `Component::Normal`/containment checks.
- **SRV-3**: A request- or config-sized duration, count, allocation, decompression or drain with no
  `MAX_` cap at the boundary, or a limit enforced on only some output paths.
- **SRV-3**: A raised limit whose dependent limits are not rechecked and pinned with
  `const _: () = assert!(..)`, or a `clamp` whose computed lower bound can exceed the upper.
- **SRV-4**: `expect`/`assert!`/`unreachable!` on a condition input, a peer, the clock, randomness
  or a race can break.
- **SRV-4**: `expect`/`panic!` in a spawned service loop on shared state another component
  maintains, instead of cancelling the root token or returning an `Internal` error.
- **SRV-4**: A comment stating an assumption about a constant or limit relation that should be a
  const assert.
- **SRV-5**: A retry loop without a classifier, budget, capped backoff and jitter, or an error arm
  that `continue`s without sleeping.
- **SRV-5**: A non-idempotent create/register/enqueue under retry without an idempotency key or
  deterministic ID, or random output names for retriable tasks.
- **SRV-5**: A permanent error retried on every poll tick, or `let _ = op().await` used to make a
  replay idempotent instead of matching the one already-done variant.

## Checklist: Error handling

- **ERR-1**: A new error variant placed in a category (internal/stale-state/stopping) whose recovery
  doesn't match; a client-reachable condition is in the internal/fatal tier; fatality decided per
  handler instead of in `is_fatal()`.
- **ERR-2**: A catch-all `_`/`Err(_)` arm mapped to a specific domain error, or
  `.ok()`/`unwrap_or_default()`/`filter_map(.. .ok())`/string-matching on data the program needs,
  instead of matching the expected variant and propagating the rest.
- **ERR-3**: A `String`/`Other(String)` payload, a tuple variant with same-typed payloads, a field
  repeating caller input, or variants no caller tells apart; tests matching on `to_string()`.
- **ERR-4**: A cause dropped via `e.to_string()`/`map_err(|_| ..)`, an error enum made generic over
  a foreign error instead of boxing it, or a wrapping variant whose `Display` omits its cause.
- **ERR-5**: An error both logged and returned (logged more than once up the stack), a helper that
  logs and returns `Option`, a task entry/`main` that exits through `?` without identifying fields,
  or `eprintln!` for errors.
- **ERR-6**: Wire-edge translation with a catch-all arm to INTERNAL/500, internal error text in a
  5xx body, or fatal/`cancel()` arms duplicated across endpoint handlers.
- **ERR-7**: A routine outcome (task failed, timeout, absent row) returned as `Err`, an `Option`
  used where empty is a failure, or a mutation reporting success when zero rows matched.
- **ERR-8**: `#[from]` on a source type that `?` produces at call sites with different meanings, two
  variants wrapping the same source, or a foreign-enum `From` with a `_` arm on an exhaustive enum.
- **ERR-9**: A best-effort operation returning a `Result` every caller ignores, a bare
  `let _ = fallible()` without `inspect_err` + log, or a batch/recovery loop with no visible
  fail-fast vs per-item policy.
- **ERR-10**: A fallible trait method with an infallible signature (implementers `expect`), or an
  associated `Error` missing the `std::error::Error + Send + Sync + 'static` bound.

## Checklist: Designing types and their methods

- **OBJ-1**: An invariant-carrying type has `pub` constrained fields, or derives `Deserialize`
  without `serde(try_from)` through its validating constructor; an after-the-fact `validate_*` pass
  instead of a mutation API that cannot express bad states.
- **OBJ-2**: A value needs `init()`/`initialize()`/`restore_*` after construction, or a recovery
  factory (`recover_*`, `from_row`) hard-codes a field the creation path sets.
- **OBJ-3**: Mandatory cleanup is a call callers must remember instead of a guard's `Drop`; a guard
  lacks `#[must_use]` or is bound to `_`; `Drop` blocks, swallows errors, or is the only path for
  awaited/fallible cleanup (no consuming `close(self)`).
- **OBJ-4**: An `Option` field or second constructor for a dependency production always provides;
  runtime handles inside a `Deserialize` config; a per-job value in a shared context; a constructor
  taking the output of the object's own work.
- **OBJ-5**: Shared state cloned as several `Arc`s, or `Arc<Mutex<_>>`/raw atomics/multi-meaning
  `CancellationToken` handed to other modules; locking at call sites; a lock beside the data it
  guards; interior mutability on unshared types.
- **OBJ-6**: A type alias or `pub` fields over a shared map/channel; "call X before Y" or "must not
  be called concurrently" docs on a `Clone` + `&self` type; handles sharing one all-owning `Inner`.
- **OBJ-7**: A builder with a public `flush`/`finalize` beside a consuming getter, a `From` impl
  that runs a processing step, a `build()` erroring on a missing required field, or an `add` that
  mutates before validating; a positional constructor accumulating optional args.
- **OBJ-8**: A method prefix contradicts its body (`expect_` returns `Err`,
  `get_`/`compute_`/`check_` mutates, `cancel` only requests, `into_` borrows, a bulk op without a
  plural selective name).
- **OBJ-9**: An inherent `parse_str`, a free `a_to_b` converter, or a homegrown single-method
  conversion trait instead of `FromStr`/`From`/`TryFrom`; field mapping inlined at a call site.
- **OBJ-10**: A derive with no caller in the diff, or whose meaning is wrong for the type (`Clone`
  on a token/guard/single writer, `Ord` on an enum without stated order, `Default` with an invalid
  empty value, derived `Debug` on bulky payloads); a manual impl that only duplicates a derive.

## Checklist: Ownership, borrowing and performance

- **OWN-1**: A by-value parameter of an `async fn` or trait method that is only read (clippy skips
  these): ask for `&T`. A borrowed parameter that is `.to_vec()`/`.clone()`/`.to_owned()`'d and then
  stored or sent: ask for ownership. `impl Into<..>` used on non-public helpers.
- **OWN-2**: `-> &Vec<T>`, `-> &String`, `-> &Option<T>` returns, `&Option<T>` params on `pub` fns,
  or a getter returning `.clone()` of a non-`Copy` field: use `&[T]` / `&str` / `Option<&T>` via
  `as_slice`/`as_str`/`as_ref`/`as_deref`.
- **OWN-3**: A loop-carried `Option`/buffer consumed once but cloned, re-copied (`Copy` type) or
  guarded by a "sent" `bool`, or `clone()` followed by `clear()`: use `Option::take` / `mem::take` /
  `mem::replace`.
- **OWN-4**: A retry/poll closure whose future borrows `self` or captures instead of being an owning
  `async move`, or a helper bounded by `AsyncFn*` where callers need `Send` futures: use
  `FnMut() -> FutureType` with `FutureType: Send`. Callback bounds stronger than how they are called
  (`Fn`/`Send + 'static` on once-called, never-spawned closures).
- **OWN-5**: A per-record trait method taking an owned struct/`String` it only reads, or
  per-instance constants passed on every call; a `-> String` transform that usually returns its
  input unchanged: use `&str` params, constructor args, `Cow`.
- **OWN-6**: `Arc<TypeParam>` in a public generic signature or field, or `Arc::new` around an
  already-cheap `Clone` handle: take a by-value `Clone` bound and add a forwarding impl for
  `Arc<T>`.
- **OWN-7**: A new `.clone()` of a non-`Copy`, non-handle value added to get past a borrow error or
  creating a second copy of mutable state: borrow fields directly, destructure, scope the borrow, or
  split the struct.
- **OWN-8**: A `spawn`/`JoinSet` loop used only for I/O concurrency that clones every borrowed
  input, or unbounded fan-out: use `try_join!`/`buffer_unordered(n)` (`buffered` for order) on the
  current task.
- **OWN-9**: `Rc`/`Arc` fields linking a node to its own type or to a type that links back, or
  unchecked indexing with externally supplied indices: use an owning `Vec` arena with named index
  types and `get(index)`.
- **OWN-10**: Flag-and-break loops or push loops that only filter/map/propagate errors (use
  `any`/`find`/`collect::<Result<..>>`), and conversely folds or long chains carrying several
  outputs, side effects or awaits (use a `for` loop).

## Checklist: Async and concurrency

- **ASYNC-1**: A `select!`/`timeout`/handler future pops, takes or moves owned state in a branch
  expression, or awaits between a dequeue and recording the item's new owner; non-cancel-safe ops
  (`read_line`, `read_exact`, `write_all`, a must-survive `send`) raced.
- **ASYNC-2**: A request handler performs two or more state-changing awaits inline instead of via a
  tracked `spawn_body`-style task or one guarded idempotent write.
- **ASYNC-3**: A `tokio::spawn` handle discarded or dropped by `?`/`try_join!`, `timeout(d, handle)`
  by value, or a spawned `Result` whose `Err` nobody observes (no log + fatal shutdown at the spawn
  site).
- **ASYNC-4**: Shutdown not routed through one root token (missing SIGTERM or fatal-error trigger),
  per-phase timers instead of one deadline, `let _ =` on joined results, `JoinError` labelled as
  panic only, or exit code 0 after a fatal/failed/timed-out shutdown.
- **ASYNC-5**: A std/`DashMap` guard held across `.await`, or any guard held across an await on an
  actor reply, a bounded send or a client-chosen timeout; read-then-write without a re-check under
  the write guard.
- **ASYNC-6**: An unbounded channel without a comment naming its bound, `let _ = tx.send(..)` in a
  producer, the original `Sender` not dropped, a loop ending on out-of-band status, or a permit
  acquired inside the spawned task or via `try_acquire` polling.
- **ASYNC-7**: A blocking call (`std::fs`, `thread::sleep`, sync client, long CPU loop) inside async
  code, or an await on an RPC/DB/never-closing channel without a configured deadline mapped to a
  `Timeout(Duration)` variant.
- **ASYNC-8**: A `select!` where an end/cancel branch must beat ready work but `biased;` is missing,
  misordered or uncommented; or `biased;` with an always-ready branch starving later ones.
- **ASYNC-9**: Multi-field shared state written by several handlers and a background loop under
  `Arc<Mutex<_>>`; an actor handle that ignores send failure or treats a dropped reply as success;
  an actor that exits without draining and answering pending requests; an interval without
  `MissedTickBehavior`.
- **ASYNC-10**: An `async fn` whose call-time side effect (send, reservation) only runs when polled,
  instead of a sync fn returning `impl Future + Send + use<>`; a public client crate's async methods
  lacking per-method compile-time `Send` assertions; `#[async_trait(?Send)]` on a spawned trait.

## Checklist: Serialization, config and external boundaries

- **BND-1**: External data deserialized into `Value`/raw primitives and checked later (`json["a"]`
  chains, handler-side `if x <= 0`, `validate(&self)` after `from_str`) instead of validating types
  via `#[serde(try_from = "Unchecked...")]`.
- **BND-1**: `deny_unknown_fields` or other container attributes placed on a `try_from` type
  (ignored) instead of on its `Unchecked*` struct.
- **BND-2**: `#[derive(Deserialize)]` on an owned config/job-config/request schema (including nested
  sections and enum-variant structs) lacks `#[serde(deny_unknown_fields)]`.
- **BND-2**: `#[serde(untagged)]`, an externally tagged config enum, or a `HashMap`/`flatten`
  catch-all for a closed key set; a schema change or newly added `deny_unknown_fields` not marked
  breaking.
- **BND-3**: A DB transition decided from an unlocked `SELECT`, an `UPDATE` `WHERE` missing the
  expected state or writer fence, or `rows_affected()` ignored.
- **BND-3**: A storage method split across transactions without a measured reason and a
  partial-failure docstring; `ON UPDATE CURRENT_TIMESTAMP` on meaningful columns; vendor-only SQL
  like `INSERT ... RETURNING` in multi-backend crates.
- **BND-4**: `unwrap_or_default`/`expect`/`as` on proto fields, a raw proto field read outside the
  unpack layer, or `Unspecified`/a missing sub-message not mapped to a named error.
- **BND-4**: An `Unpacked` tuple with 3+ values or two same-typed values; an outbound `Option`
  flattened with `unwrap_or_default`; an unpack layer rejecting fields on behalf of one backend.
- **BND-5**: An env var read with `.ok()`/`unwrap_or`/`map_err(|_| ..)` so `NotUnicode`, a parse
  failure, or a partially set group is silently treated as absent.
- **BND-5**: Config patched from env after loading, I/O in `OnceLock`/`LazyLock` getters, or service
  config rebuilt from many CLI flags instead of a config path.
- **BND-6**: `#[serde(default)]` on a count/capacity/interval where zero is invalid, or a nested
  all-default section without a struct-level `#[serde(default)]`.
- **BND-6**: A `const DEFAULT_*` duplicating another component's default instead of passing `None`
  through; `Option` on a mirrored field the source requires.
- **BND-7**: A peer-supplied length cast with `as` or used to allocate without a configured maximum;
  `len() as u32` when encoding.
- **BND-7**: Unbounded `lines()`/`LinesCodec::new()` over peer or child output, a `FramedRead`
  `None` after a decode error treated as EOF, strict UTF-8 on opaque text, or IDs accepted from
  lossy decoding without a strict parse.
- **BND-7**: A child process spawned via `sh -c` with an interpolated string, without
  `kill_on_drop(true)`, or with stderr discarded on failure.
- **BND-8**: A password/secret/token held as `String`/`Vec<u8>` on a `Debug`/`Serialize` type or
  passed across an API as `String`/`Vec<u8>`, a credential compared with `==`, or a credential field
  serialized.
- **BND-8**: A session token, presigned URL or credential logged on an accept/success path.
- **BND-9**: Status codes decoded outside a single `status_to_error`, a server status change without
  the matching client decoder change, or no per-code decoder test.
- **BND-9**: `Status::unavailable` for an application error, internal error detail sent to clients,
  or responses that distinguish not-found from wrong-credential.
- **BND-10**: A tuple `query_as` with 3+ columns, `row.try_get("col")`, `.bind(status as i32)`, or
  SQL-side formatting/rounding/vendor functions.
- **BND-10**: A DB row converted without re-running validating constructors, or a validation error
  mapped by a blanket `From` into a client error instead of `CorruptedDbState` at the read site.

## Checklist: Modules, crates and API surface

- **MOD-1**: A new `pub` item with no caller outside the crate, or in a binary package not called by
  its `src/bin/` targets; ask for `pub(crate)`/`pub(super)`, or a private field plus a getter.
- **MOD-2**: A serde/DB/wire/FFI/config contract changed (default, rename, new required field,
  removed key) without `!`, a migration note, a list of cross-language writers/readers, or a
  chart/image bump, or with a tolerant reader that silently accepts the old shape;
  `#[non_exhaustive]` on an enum only our crates consume.
- **MOD-3**: `version =`/`git =` in a member manifest, a git dep on `branch`, a cross-repo bump that
  leaves an old rev/image tag behind, or an immature/unsafe-API crate chosen without a reason.
- **MOD-4**: A new workspace dependency edge used for one type, `prost`/`tonic` in the domain crate,
  wire conversions outside the protocol crate, a component-specific trait in core/proto, or a helper
  moved to a shared crate before it has a second consumer.
- **MOD-5**: `pub use child::*`, `pub mod` on a file-organising submodule, a module split that
  widens visibility (sibling test files need `pub(super)`), or a split mixed with behaviour changes.
- **MOD-6**: A library `pub use` of another workspace crate's type that none of its public
  signatures mention, or a forwarding re-export kept at a moved type's old path.
- **MOD-7**: A user-facing crate exposes pools, channels or generated gRPC clients, or a public
  signature names an internal-crate type that the crate root doesn't re-export.
- **MOD-8**: A `pub` item documented as test-only, a test-only crate under `[dependencies]`, a
  `test-utils` feature with no cross-crate test consumer in the PR or enabled outside
  `[dev-dependencies]`, or a feature-gated helper whose deps are missing from `[dev-dependencies]`.
- **MOD-9**: `#[allow(dead_code)]` or an `expect` without `reason`, a plain `expect` on a module its
  tests fully use (needs `cfg_attr(not(test), ...)`), a staged subsystem left all-private, or a
  consumer PR that leaves the `expect` in place.
- **MOD-10**: A feature that switches behaviour instead of adding capability, an optional dep
  without `dep:`, an unexplained `default` addition, or a multi-feature crate with no
  no-default/all-features build evidence.

## Checklist: Testing and observability for correctness

- **TEST-1**: An error-path test uses `is_err()` or a `to_string()` substring instead of the exact
  variant and payload; a rejected mutation not checked for unchanged state; a stream test that
  doesn't assert `None` after the terminal event.
- **TEST-2**: A bare `.await` on `recv`/`reached`/`wait`/`join_next`/`JoinHandle` in a test without
  `tokio::time::timeout(NAMED_CONST, ..)` (or `try_recv` for an already-happened event); a
  decode-until-empty test loop without a progress assertion.
- **TEST-3**: A mapping/classification function tested only through a variant-merging outer layer
  (HTTP code, `bool`), a mock that copies its `match`, or a forwarding wrapper, instead of a table
  with one row per input at its definition.
- **TEST-4**: A race test using `tokio::join!` of two calls, the current-thread runtime,
  `sleep`-based ordering, an undersized pool, or unseeded randomness instead of a `multi_thread`
  runtime with a `Barrier`, many callers, iterations and a seed parameter.
- **TEST-5**: A test that mutates env/cwd (`set_var`, `remove_var`, `set_current_dir`) behind an
  unenforced `SAFETY` comment, uses fixed temp paths, asserts global row counts, or hides
  serialization in `.config/nextest.toml` instead of `#[serial]` on the test.
- **TEST-6**: `Instant::now()`/`SystemTime::now()`, `stdout()` or a task handle buried in decision
  logic with untested timeout/failure branches; or a `foo`/`foo_with_clock` duplicate instead of one
  function taking the value as a parameter.
- **TEST-7**: A test-only helper/fixture/constructor (e.g. `Id::random`) that is plain `pub` instead
  of gated per MOD-8; the feature enabled via `required-features` instead of a self dev-dependency;
  a mock returning errors outside the trait's `# Errors`, or using `.ok_or(..)?` on its own maps
  instead of `expect`.
- **TEST-8**: A hand-written algorithm tested by one hand-computed output instead of invariants
  (conservation, ordering, loop postcondition) over every output; an incremental decoder never fed
  byte by byte.
- **TEST-9**: Values interpolated into a `tracing` message instead of fields; only the error kind
  logged; spawned async work without `.instrument(span)`; a `span.enter()`/`.entered()` guard in an
  `async` body; `#[instrument]` without `skip`/`skip_all` on functions taking
  buffers/configs/secrets.
- **TEST-10**: A new typestate, single-use token, sealed trait or validating macro with no
  compile-fail test (`trybuild` with `.stderr`, or a `compile_fail` doctest verified to fail for the
  stated reason).
