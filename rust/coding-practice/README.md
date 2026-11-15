# Rust coding practice

This guide describes good practice for writing Rust in our projects: Spider and the Rust components
of CLP. It is the companion of `coding-style.md`, which covers how code should look, and
`pr-review.md`, which covers how a review is run. This guide covers what the code should do: how to
use types, traits, errors, ownership, async and crate boundaries so that whole classes of bugs can't
be written, and the rest fail loudly instead of silently.

The rules are drawn from three sources: the Spider codebase and its review history (y-scope/spider),
the Rust PRs and review comments in y-scope/clp, and Microsoft's RustTraining books. Each rule cites
the PRs, files and chapters it came from.

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
- **Let the compiler enforce contracts.** Exhaustive matches, move-only tokens, narrow trait bounds,
  compile-time `Send` assertions and const asserts turn "remember to" into a build error. (DEF-1,
  TLC-2, TLC-4, TLC-5)
- **Fail loudly and attributably.** Never invent a plausible value for bad input. Return a typed
  error that keeps its cause, handle and log it once, and take the service down when shared state is
  corrupt. (DEF-4, DEF-6, ERR-4, ERR-5)
- **Keep state changes atomic and cancel-safe.** Check before the first mutation, make
  check-then-act one step, and assume that any future can be dropped at any `.await`. (DEF-2, DEF-3,
  ASYNC-1, ASYNC-2)
- **Bound everything an outsider can size.** Cap the durations, allocations, queues and payloads a
  peer or config controls, and put a deadline on every external wait. (DEF-5, ASYNC-6, ASYNC-7,
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
   - TYPE-10: Type opaque bytes by their encoding, and secrets by their sensitivity
2. [Type-level constraints, traits and generics](#type-level-constraints-traits-and-generics) (TLC-1
   to TLC-10)
   - TLC-1: Give each kind of ID its own type through a phantom marker
   - TLC-2: Bound each component by the narrowest capability it uses
   - TLC-3: Keep a statically known type as an associated type
   - TLC-4: Make a permit or proof a move-only token that only its owning module can mint
   - TLC-5: Assert `Send`/`Sync` guarantees at compile time, next to the type
   - TLC-6: Use associated types for types each implementor fixes, and `Infallible` for impls that
     can't fail
   - TLC-7: Make a stateless strategy a type-only trait
   - TLC-8: When `dyn` is justified, make the trait dyn-compatible from the start
   - TLC-9: Use blanket impls only for behavior that is the same for every type
   - TLC-10: Use typestate only for statically ordered protocols
3. [Defensive programming](#defensive-programming) (DEF-1 to DEF-10)
   - DEF-1: Match every variant of the enums you own; no catch-all arm
   - DEF-2: Run every check that can fail before the first mutation
   - DEF-3: Make check-then-act atomic, and let progress state only move forward
   - DEF-4: Turn unknown, missing or unsupported input into an error, never a plausible value
   - DEF-5: Cap every resource that a peer or a config value can size
   - DEF-6: Return errors for what the environment can cause, and fail the whole service for broken
     invariants
   - DEF-7: Retry only transient failures, with backoff, and only idempotent operations
   - DEF-8: Choose an overflow behaviour for every arithmetic on unbounded values
   - DEF-9: Decode external input with checked slicing, never indexing
   - DEF-10: Confine `unsafe` behind a safe API, and state its contract in the right place
4. [Error handling](#error-handling) (ERR-1 to ERR-10)
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
5. [Designing types and their methods](#designing-types-and-their-methods) (OBJ-1 to OBJ-10)
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
6. [Ownership, borrowing and performance](#ownership-borrowing-and-performance) (OWN-1 to OWN-10)
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
7. [Async and concurrency](#async-and-concurrency) (ASYNC-1 to ASYNC-10)
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
8. [Serialization, config and external boundaries](#serialization-config-and-external-boundaries)
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
9. [Modules, crates and API surface](#modules-crates-and-api-surface) (MOD-1 to MOD-10)
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
10. [Testing and observability for correctness](#testing-and-observability-for-correctness) (TEST-1
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
11. [Review checklist](#review-checklist)

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
  the checked type `Validated*` (y-scope/clp#2197).

**Sources.** See also coding-style.md § Type-Level Validation, and BND-1 for running the parse
inside serde. spider components/spider-storage/src/job_submission.rs, spider
components/spider-storage/src/state/service.rs, spider
components/spider-tdl-derive/src/task_macro.rs, y-scope/spider#283, y-scope/spider#351,
y-scope/clp#1989, y-scope/clp#2197, RustTraining
type-driven-correctness-book/src/ch07-validated-boundaries-parse-dont-validate.md, RustTraining
rust-patterns-book/src/ch15-crate-architecture-and-api-design.md

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

**Sources.** See also coding-style.md § Type-Level Validation, OBJ-1 (designing the type so
mutations can't break it) and BND-1 (the serde side). spider
components/spider-core/src/task/task_graph.rs, spider components/spider-proto-rust/src/io.rs, spider
components/spider-tdl/src/task_context.rs, spider components/spider-tdl/src/task.rs, spider
components/spider-core/src/types/io/task_graph_input.rs, y-scope/spider#492, y-scope/spider#562,
y-scope/spider#565, y-scope/clp#1769, y-scope/clp#2595, y-scope/clp#2652, clp
components/clp-rust-libs/clp-rust-utils/src/types.rs, RustTraining
type-driven-correctness-book/src/ch07-validated-boundaries-parse-dont-validate.md, RustTraining
rust-patterns-book/src/ch03-the-newtype-and-type-state-patterns.md

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
  For example, y-scope/clp#2681 replaced `task_index: u64` with `spider_core::task::TaskIndex`.

**Exceptions.** Config fields keep the house form of a `u64` with a unit suffix in the name, which
is what carries the meaning there (coding-style.md § Prefer `u64` seconds over `Duration` for time
config). `pub type` aliases for *external* types remain the house style (coding-style.md § Type
Aliases for External Types). This rule covers domain identifiers and quantities.

**Sources.** spider components/spider-core/src/types/id.rs, spider
components/spider-proto-rust/src/unpack/storage.rs, spider
components/spider-execution-manager/src/client/storage.rs, clp
components/clp-rust-libs/clp-rust-utils/src/types.rs, y-scope/clp#2420, y-scope/clp#2503,
y-scope/clp#2504, y-scope/clp#2531, y-scope/clp#2676, y-scope/clp#2681, y-scope/spider#337,
RustTraining type-driven-correctness-book/src/ch06-dimensional-analysis-making-the-compiler.md,
RustTraining rust-patterns-book/src/ch03-the-newtype-and-type-state-patterns.md

## TYPE-4: Represent absence with `Option`, never with a sentinel

**Rule.** Write "not set", "unlimited" or "not present" as `Option<T>`. When the present value has
its own constraint, use `Option<NonZero*>` or `Option<Validated>`. Do not use `0`, `-1`, `""`,
`u32::MAX`, an empty container, a defaulted ID or an `Option<bool>` third state for this. When an
external format uses a sentinel, convert it to `None` at the first parse step. Keep "absent"
separate from "malformed", and substitute a display placeholder only at the presentation edge.

**Why.** A sentinel looks exactly like a real value, so every consumer has to remember the magic
check, and the one that forgets works on made-up data. In y-scope/clp#2567, `max_num_results` used 0
to mean "unlimited" while another layer had already replaced 0 with a default, so callers who left
the field out were silently capped. With `Option<NonZeroU32>`, `None` means unlimited and 0 is
rejected. Calling `.unwrap_or(0)` or `.ok()` on a parse result is just as bad: a corrupt field turns
into "not present", and the original error is lost.

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
representation, usually an empty `Vec` rather than `Option<Vec<_>>` (y-scope/spider#293). In
storage, a self-reference can be a deliberate choice over NULL for index or write-cost reasons
(y-scope/spider#531), but write the reason down.

**Sources.** See also DEF-4 (unknown input is an error) and ERR-2 (don't hide errors with `.ok()`).
y-scope/clp#1728, y-scope/clp#1776, y-scope/clp#2180, y-scope/clp#2251, y-scope/clp#2503,
y-scope/clp#2513, y-scope/clp#2567, y-scope/clp#2597, spider
components/spider-scheduler/src/core_impl/inbound_queue_reader.rs, spider
components/spider-core/src/types/id.rs, RustTraining
type-driven-correctness-book/src/ch11-fourteen-tricks-from-the-trenches.md, RustTraining
python-book/src/ch16-best-practices.md

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
exhaustive `match` shows every site that needs updating when a mode is added. In y-scope/clp#2705,
returning `(Session, ResultStream)` let a caller pair one session's stream with a different session.
An `OpenSession` that only the registry can construct made that pairing impossible.

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
  type per query shape, or an enum over them (y-scope/clp#2435).
- Flag functions that take or return a tuple of values that must come from the same creation, and
  lossy projections of a config enum such as `Option<(&str, &str)>`. Pass the enum or the bundle
  instead, and put the variant-specific logic on it as a method.

**Exceptions.** Keep separate `Option` fields when every combination is valid and its meaning is
documented, for example an aggregation that runs regardless of `max_num_results`.

**Sources.** See also coding-style.md § API design (named fields over positional tuples) and § Enum
vs Trait Objects. y-scope/clp#1962, y-scope/clp#2435, y-scope/clp#2561, y-scope/clp#2613,
y-scope/clp#2652, y-scope/clp#2705, y-scope/spider#464, spider
components/spider-core/src/types/id.rs, spider
components/spider-storage/src/db/mariadb/tree_transition.rs, spider
components/spider-core/src/types/resource_group.rs, RustTraining
python-book/src/ch06-enums-and-pattern-matching.md

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
lets bare integers into business logic; y-scope/clp#2197 removed exactly that.

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
- Flag `_ =>` arms in a parser, and in any `match` over a domain enum that decides behavior (DEF-1).
  When every variant is listed, the compiler points at the match when a variant is added.
- Flag a `HashMap<KeyEnum, V>` read through `map[&key]` when the key set is fixed. Use a struct with
  one field per key and `#[serde(deny_unknown_fields)]`, so a missing or misspelled key fails at
  parse time instead of panicking at the lookup (y-scope/clp#1828).

**Sources.** See also coding-style.md § Avoid hardcoded state values, DEF-1 (exhaustive matching)
and DEF-4 (unknown input is an error). y-scope/clp#1828, y-scope/clp#2197, RustTraining
type-driven-correctness-book/src/ch01-the-philosophy-why-types-beat-tests.md, RustTraining
type-driven-correctness-book/src/ch11-fourteen-tricks-from-the-trenches.md, RustTraining
type-driven-correctness-book/src/ch17-redfish-applied-walkthrough.md

## TYPE-7: Choose the numeric type whose range is the invariant

**Rule.** Declare capacities, pool sizes, intervals, divisors, rates and limits that must be
positive as `NonZeroUsize`, `NonZeroU64` or `NonZeroU16` in the struct that holds them, so
deserialization rejects 0. Call `.get()` where the value is used. Keep a plain integer only where 0
has a documented meaning. Choose the width and signedness from the real range and from every
consumer (wire, DB, C++ core, BSON), and add a validated newtype when those consumers disagree.

**Why.** A zero capacity panics in `mpsc::channel` or leaves every `Semaphore::acquire` waiting
forever. A zero divisor panics in `div_ceil`, a zero heartbeat period panics in
`tokio::time::interval` (y-scope/spider#362), and a zero tick interval busy-spins the scheduler
loop. All of these fail far away from the config file that caused them. In y-scope/spider#367,
switching to `NonZero*` deleted the hand-written `validate()` methods, their `InvalidConfig`
variants and the `Result` on the constructors. A type that merely looks tight can also backfire. In
y-scope/clp#2561, a `NonZeroU32` millisecond bucket size overflows on a WebUI timeline longer than
about 3 years, while clp-s and MongoDB both expect `i64`. That is why the field is now `PositiveI64`
(deserialized `try_from = "NonZeroU64"`).

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

**Sources.** See also coding-style.md § Use `u64` for sizes that may exceed 32-bit, DEF-5 (upper
caps) and BND-6 (defaults that must not be zero). spider components/spider-scheduler/src/config.rs,
spider components/spider-scheduler/src/execution_manager_registry.rs, spider
components/spider-scheduler/src/runtime.rs, y-scope/spider#334, y-scope/spider#362,
y-scope/spider#367, y-scope/spider#396, y-scope/clp#2150, y-scope/clp#2561, y-scope/clp#2668, clp
components/clp-rust-libs/clp-rust-utils/src/types.rs, RustTraining
rust-patterns-book/src/ch15-crate-architecture-and-api-design.md

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
this component's bug, so it returns an error (y-scope/clp#2017).

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
widening inside a `const` item, where `From` isn't callable (DEF-8).

**Sources.** See also pr-review.md § Panic vs error returns, DEF-8 (overflow in arithmetic), BND-4
(proto fields) and BND-7 (wire lengths). spider components/spider-proto-rust/src/unpack/storage.rs,
spider components/spider-proto-rust/src/id.rs, spider components/spider-core/src/types/io/mod.rs,
y-scope/spider#492, y-scope/clp#1989, y-scope/clp#2017, y-scope/clp#2180, y-scope/clp#2224,
RustTraining c-cpp-book/src/ch18-cpp-rust-semantic-deep-dives.md, RustTraining
csharp-book/src/ch03-built-in-types-and-variables.md

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

**Sources.** y-scope/clp#2053, y-scope/clp#2513, y-scope/clp#2589, y-scope/clp#2617,
y-scope/clp#2662, spider
components/spider-scheduler/src/core_impl/resource_group_round_robin/scheduling_state.rs, clp
components/log-ingestor/src/ingestion_job_manager.rs, clp
components/query-coordinator/src/job_handle.rs, clp
components/query-coordinator/src/query_job_submitter/mod.rs, RustTraining
type-driven-correctness-book/src/ch07-validated-boundaries-parse-dont-validate.md

## TYPE-10: Type opaque bytes by their encoding, and secrets by their sensitivity

**Rule.** When a `Vec<u8>` must hold one specific encoding (a msgpack `ExecutorError`, framed task
inputs, zstd-compressed JSON), wrap it in a newtype named after that encoding. Only the encoder
should be able to construct it, and it should offer a `decode()`. Keep passwords and tokens in a
secret wrapper such as `secrecy::SecretSlice<u8>` across every API that carries them, and compare
them with `subtle::ConstantTimeEq` rather than `==`. BND-8 covers how secrets are deserialized,
logged and compared at the boundary.

**Why.** In Spider's execution manager, a bare `Vec<u8>` documented as "the msgpack-encoded error"
was rendered with `String::from_utf8_lossy`, so storage recorded garbage for every in-task failure.
`Vec::new()` type-checked as "empty task inputs" but is not a valid zero-frame stream, so every
commit task failed in the executor (y-scope/spider#405). In both cases, a newtype that only
`decode()` and the serializer can touch would have turned the bug into a compile error. On the
secrets side, `ExternalResourceGroupCredentials` keeps its password in a `SecretSlice`, so `Debug`
redacts it. But `verify_resource_group(password: Vec<u8>)` takes the password back out of the
wrapper, and from that point a single `?creds` in a log line prints it.

```rust,ignore
// Bad
pub enum Outcome {
    InTaskFailure { error: Vec<u8> }, // msgpack-encoded `ExecutorError`
}

let message = String::from_utf8_lossy(&error).into_owned();
let raw_inputs: Vec<u8> = Vec::new();
```

```rust,ignore
// Good
pub struct MsgpackExecutorError(Vec<u8>);

impl MsgpackExecutorError {
    pub fn decode(&self) -> Result<ExecutorError, rmp_serde::decode::Error> {
        rmp_serde::from_slice(&self.0)
    }
}

pub enum Outcome {
    InTaskFailure { error: MsgpackExecutorError },
}

let raw_inputs = TaskInputsSerializer::new().release();
```

**Review.**
- Flag `Vec<u8>` fields and parameters, and `Result<Vec<u8>, Vec<u8>>` types, whose meaning lives
  only in a comment. Also flag any hand-built "empty" or literal encoded buffer. Tests should assert
  the exact encoded bytes rather than `is_empty()`.
- Flag a secret that crosses a function boundary as a `Vec<u8>` or `String`, a `#[derive(Debug)]` on
  a struct that holds a raw secret, and `==` between secrets.

**Exceptions.** A wrapper has to prevent a real misuse. y-scope/clp#1704 dropped `SecretString` from
the AWS secret-key path, where it only added conversions. When a reviewer asks what a newtype
actually prevents, the answer must be concrete.

**Sources.** See also coding-style.md § Binary Serialization and BND-8. spider
components/spider-execution-manager/src/process_pool.rs, spider
components/spider-execution-manager/src/runtime.rs, spider components/spider-tdl/src/task.rs, spider
components/spider-core/src/types/resource_group.rs, spider
components/spider-storage/src/db/mariadb/resource_group.rs, spider
components/spider-client/src/client.rs, y-scope/spider#292, y-scope/spider#405, y-scope/clp#1704

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
`TypeMarker` appears only inside `PhantomData`. In y-scope/spider#271 the markers derived only
`Debug, PartialEq, Eq`, so `JobId` was silently neither `Copy` nor `Hash` despite the derive on
`Id`. y-scope/spider#309 had to add the missing derives. Bounds on the definition itself
(`Id<TypeMarker: Debug + PartialEq + Eq>`) gain nothing, and every `impl` block has to repeat them.

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

**Sources.** spider components/spider-core/src/types/id.rs, y-scope/spider#271, y-scope/spider#309,
RustTraining rust-patterns-book/src/ch04-phantomdata-types-that-carry-no-data.md

## TLC-2: Bound each component by the narrowest capability it uses

**Rule.** Split a wide backend interface into role traits, and combine them in a supertrait only for
the composition root. Bound each generic component on just the traits it calls (`StateType:
IngestionJobState + SqsListenerState`). Don't add conveniences that turn one capability into
another, such as a `Reader::writer()`.

**Why.** Narrow bounds document what a component can do: a GC loop can't accidentally delete
resource groups, and the SQS listener can't call the S3 scanner's state methods. In y-scope/clp#2001
the reviewer rejected `IngestionJobState: SqsListenerState + S3ScannerState`, because it forces
every state implementation to provide methods for job types it never runs. Mocks also shrink to the
one trait under test. In y-scope/spider#339 a reviewer removed a write-through-the-reader shortcut:
the reader/writer split exists so that the types show who can mutate shared outputs, and an escape
hatch makes every reader a writer. Coding agents tend to add such shortcuts just to make a change
compile.

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
type directly (y-scope/clp#2001). See also: pr-review.md § Trait surface minimization. That rule
covers which methods a trait has, and this one covers which traits a consumer can see.

**Sources.** y-scope/clp#2001, y-scope/spider#286, y-scope/spider#339, spider
components/spider-storage/src/db/protocol.rs, clp
components/log-ingestor/src/ingestion_job/sqs_listener.rs, clp
components/log-ingestor/src/ingestion_job/state.rs

## TLC-3: Keep a statically known type as an associated type; don't erase it and recover it with `unreachable!`

**Rule.** If each implementor of a trait always produces one concrete type, make that type an
associated type (`type Manifest;`, `type Response;`) so callers keep it. Convert it into a shared
enum only at the boundary that actually needs the enum. In production code, treat `unreachable!` and
`let Enum::Variant(x) = y else { panic!(..) }` as signs that the type was erased too early.

**Why.** In y-scope/clp#2620, `Source::build_task_inputs` returned `Vec<CompressionInputSource>`
even though each source statically knew which manifest it built: `S3Config` only ever built
`S3InputSource`. That forced the S3 path to match its way back out with an `unreachable!`, and left
enum accessors whose only callers were tests. An untyped API such as
`get(path) -> serde_json::Value` fails the same way, because every caller has to guess the schema.
With an associated type, a mismatch is a compile error and the decoding lives in one implementation.

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

**Sources.** y-scope/clp#2620, clp components/compression-coordinator/src/partition.rs, RustTraining
type-driven-correctness-book/src/ch02-typed-command-interfaces-request-determi.md, RustTraining
rust-patterns-book/src/ch02-traits-in-depth.md

## TLC-4: Make a permit or proof a move-only token that only its owning module can mint

**Rule.** When a value grants the right to do something at most once, or proves a precondition
(authenticated, slot reserved, subsystem ready), make it a struct with private fields and a
module-private constructor. Don't derive `Clone`, `Copy`, `Default` or `Deserialize` on it. Put the
spending operation on the token itself, as a synchronous method that takes `self`. Don't express
such a fact as a `bool` parameter, or as a method on a handle that many holders share.

**Why.** An earlier revision of y-scope/spider#449 put the spend on the dispatch-queue reader, so
any holder of any clone of the reader could decrement a hint count it had no claim to. Once that
happens, the counter stays wrong. With a move-only `Hint`, spending twice (E0382) and forging a hint
(E0451) are both compile errors, so reviewers don't have to audit every call site. A
`fn reset(is_admin: bool)` has the same problem in another form, because the caller can just pass
`true`. Each derive and each `pub` field is another way to forge the token. A synchronous spend also
means that cancellation at an `.await` can't leave the counter decremented without the receive
happening.

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

**Exceptions.** A `bool` for a plain binary choice is still right (coding-style.md § Prefer Booleans
Over Small Enum Subsets). Dropping an unspent token is fine and needs no `Drop` impl, unless
abandoning it is itself a bug, in which case add a `Drop` guard (OBJ-3). See also: coding-style.md §
Take ownership when the value mustn't be used afterwards. This rule adds the private constructor,
the forbidden derives, and moving the spend off the shared handle. OBJ-10 covers derives in general,
and TEST-10 covers pinning the guarantee with a compile-fail test.

**Sources.** y-scope/spider#449, spider
components/spider-scheduler/src/core_impl/resource_group_round_robin/dispatch_queue.rs, RustTraining
type-driven-correctness-book/src/ch04-capability-tokens-zero-cost-proof-of-aut.md, RustTraining
type-driven-correctness-book/src/ch13-reference-card.md

## TLC-5: Assert `Send`/`Sync` guarantees at compile time, next to the type

**Rule.** When a public handle or its async methods must be usable from `tokio::spawn`, assert it at
compile time in the defining module. Use a `const _: () = { .. }` block for the type, and a
never-called `#[expect(dead_code)]` function with one assertion per public async method for the
returned futures. In a trait whose futures get spawned, put `Send` in the trait itself.

**Why.** If someone holds an `Rc` or a non-`Send` guard across an `.await`, the future silently
becomes `!Send`. The library still compiles, and the error shows up only in a downstream crate's
`tokio::spawn`, far from the cause. Asserting only the handle type doesn't catch this, because the
handle stays `Send + Sync` while one of its futures stops being `Send`. A native `async fn` in a
trait promises no `Send` either, so one implementation can break every generic caller with "future
cannot be sent between threads safely". rustc's `async_fn_in_trait` lint already warns about this on
`pub` traits, so fix the signature rather than allowing the lint. Traits using `#[async_trait]`
(without `?Send`) already box `Send` futures. Native traits need
`-> impl Future<Output = ..> + Send`, and implementations may still write `async fn`.

```rust
// Bad
pub trait Store {
    async fn get(&self, key: &str) -> Option<String>;
}
```

```rust,ignore
// Good
pub trait Store: Send + Sync {
    fn get(&self, key: &str) -> impl Future<Output = Option<String>> + Send;
}

const _: () = {
    const fn assert_send_sync<CheckedType: Send + Sync>() {}
    assert_send_sync::<SpiderClient>();
};

#[expect(dead_code, reason = "compile-time-only `Send` assertion; never called")]
fn assert_client_futures_send(client: &SpiderClient, job_id: JobId) {
    const fn assert_send<FutureType: Send>(_: &FutureType) {}
    assert_send(&client.start_job(job_id));
    assert_send(&client.cancel_job(job_id));
}
```

**Review.**
- Flag a new public client or handle type without a `Send + Sync` assertion, and a new public async
  method on it that isn't added to the futures assertion.
- Flag a native `async fn` in a trait whose futures are spawned or held across tasks, and any
  `#[allow(async_fn_in_trait)]`.

**Exceptions.** Types that never leave one task or thread don't need the assertion.

**Sources.** See also ASYNC-10 (designing async APIs around laziness and `Send`) and OWN-4 (`Send`
futures from closures). spider components/spider-client/src/client.rs, RustTraining
async-book/src/ch10-async-traits.md

## TLC-6: Use associated types for types each implementor fixes, and `Infallible` for impls that can't fail

**Rule.** Use an associated type when each implementor fixes exactly one related type (`Error`,
`Batch`, `Item`, `Response`). Use a trait generic parameter only when one type legitimately
implements the trait several times (`From<SourceType>`). Give a trait that has several backends with
different failures `type Error: std::error::Error + Send + Sync + 'static`, and set `type Error =
Infallible` in an implementation that can't fail.

**Why.** A generic parameter where an associated type belongs allows conflicting impls, makes
callers annotate the type at the call site (`let message: Message = decoder.decode(raw)?`), and
turns bounds into `StorageType: Storage<ErrorType>, ErrorType: Error`. A single shared error enum
forces every backend's variants onto all backends. A made-up `String` error on an infallible test
double suggests failure paths that don't exist, while `Infallible` keeps `?` working in generic
code. The same trick compiles optional machinery out cleanly. Spider's disarmed test hooks return an
empty `enum InjectedFault {}` whose `From` impl is `match fault {}`, so the call sites are identical
in both builds and need no `#[cfg]`.

```rust,ignore
// Bad
trait Decoder<OutputType> {
    fn decode(&self, raw: &[u8]) -> Result<OutputType, DecodeError>;
}

let message: Message = decoder.decode(raw)?;
```

```rust,ignore
// Good
pub trait ResultEncoder: Send + Sized + 'static {
    type Batch: Send + 'static;
    type Error: std::error::Error + Send + Sync + 'static;

    fn new(archive_id: ArchiveId) -> Result<Self, Self::Error>;
}

impl ResultEncoder for QueryResultEncoder {
    type Batch = Vec<QueryResult>;
    type Error = Infallible;

    fn new(archive_id: ArchiveId) -> Result<Self, Infallible> {
        Ok(Self { archive_id, batch: Vec::new() })
    }
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

**Sources.** See also ERR-10 (when a trait method needs an associated `Error` at all). clp
components/clp-rust-libs/query-result-listener/src/encoding.rs, clp
components/clp-rust-libs/query-result-listener/src/test_utils.rs, spider
components/spider-storage/src/test_hooks/disarmed.rs, RustTraining
rust-patterns-book/src/ch02-traits-in-depth.md, RustTraining
rust-patterns-book/src/ch17-exercises.md

## TLC-7: Make a stateless strategy a type-only trait

**Rule.** If a strategy carries no state, don't make callers construct and store a value of it.
Express it only through associated types, and put construction on the per-instance type as an
associated function (`EncodingType::Encoder::new(archive_id)`). If the strategy type is never
instantiated, make it an empty enum.

**Why.** A field holding a zero-sized strategy suggests that the strategy has state and that two
instances might differ. A factory method taking `&self` invites implementations to hide state there.
In y-scope/clp#2676 the reviewer put it this way: "it's not a variable, it should be just a type
constraint". y-scope/clp#2682 then moved creation into `ResultEncoder::new` and turned `SseEncoding`
and the test encodings into empty enums.

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

**Sources.** y-scope/clp#2676, y-scope/clp#2682, clp
components/clp-rust-libs/query-result-listener/src/encoding.rs, clp components/api-server/src/sse.rs

## TLC-8: When `dyn` is justified, make the trait dyn-compatible from the start

**Rule.** Once a trait object is justified, make the trait dyn-compatible (formerly "object-safe")
from the start. Consuming methods take `self: Box<Self>`. There is no `Sized` supertrait such as
`Clone`: share the object as `Arc<dyn Trait>` instead. There are no generic methods: make the
collaborator type an associated type. When the implementations are rich typed values that must be
stored and dispatched uniformly (user-authored tasks looked up by name), split the design into three
parts: a typed authoring trait, a small erased `Send + Sync` trait, and one generic bridge that
implements the erased trait.

**Why.** A by-value `self` method compiles, but it can't be called through `Box<dyn Trait>` (E0161).
y-scope/spider#368 changed `SchedulerCore::run` to `self: Box<Self>` for this reason. A `Clone`
supertrait makes the trait unusable as `dyn` (E0038), so the type ends up as a generic parameter
through every layer. y-scope/spider#443 replaced `DispatchQueueSink: Send + Sync + Clone` with one
`Arc<dyn DispatchQueueHandle>`. Associated types and consts make spider-tdl's `Task` (`type Params;
type Return; const NAME; fn execute`) unusable as `dyn`, so `TaskHandler` deals in bytes and
`TaskHandlerImpl<TaskType>` holds all the (de)serialization. Its `PhantomData<fn() -> TaskType>`
keeps the bridge `Send + Sync` without requiring that of the task type. Downcasting a `Box<dyn Any>`
instead brings back the silent runtime misses that an enum prevents.

```rust,ignore
// Bad
#[async_trait]
pub trait SchedulerCore: Send + Clone {
    async fn run(self, cancellation_token: CancellationToken) -> Result<(), SchedulerError>;
}
```

```rust,ignore
// Good
#[async_trait]
pub trait SchedulerCore: Send {
    type StorageClient: SchedulerStorageClient;

    async fn run(
        self: Box<Self>,
        storage_client: Self::StorageClient,
        cancellation_token: CancellationToken,
    ) -> Result<(), SchedulerError>;
}

pub trait TaskHandler: Send + Sync {
    fn execute_raw(&self, raw_params: &[u8]) -> Result<Vec<u8>, TaskError>;
}

pub struct TaskHandlerImpl<TaskType: Task> {
    _marker: PhantomData<fn() -> TaskType>,
}

impl<TaskType: Task> TaskHandler for TaskHandlerImpl<TaskType> {
    fn execute_raw(&self, raw_params: &[u8]) -> Result<Vec<u8>, TaskError> {
        let params = rmp_serde::from_slice(raw_params)?;
        Ok(rmp_serde::to_vec(&TaskType::execute(params)?)?)
    }
}
```

**Review.**
- Flag a trait used as `dyn` that has a `Clone`/`Sized` supertrait, a by-value `self` method, a
  generic method, or `-> Self` without `where Self: Sized`.
- Flag `Vec<Box<dyn Any>>` plus `downcast_ref`. Ask for an enum, separate typed collections, or the
  erased-trait bridge.

**Exceptions.** This rule only covers how to build the trait once `dyn` is chosen. Whether to choose
it follows coding-style.md § Enum vs Trait Objects: when the set of types is known at compile time,
use an enum.

**Sources.** y-scope/spider#368, y-scope/spider#443, spider components/spider-scheduler/src/core.rs,
spider components/spider-tdl/src/task.rs, RustTraining
rust-patterns-book/src/ch02-traits-in-depth.md, RustTraining c-cpp-book/src/ch16-case-studies.md

## TLC-9: Use blanket impls only for behavior that is the same for every type: extension traits and smart-pointer forwarding

**Rule.** Write `impl<SomeType: Bound> Trait for SomeType` only when every type that meets the bound
should get the same behavior forever. Two cases qualify. The first is an extension trait whose
default method replaces copies of the same inherent method across crates. The second is a forwarding
impl such as `impl<ClientType: Client + ?Sized> Client for Arc<ClientType>`, shown in OWN-6.
Otherwise, write inherent methods or per-type impls.

**Why.** Copies of `from_yaml_file`, each with its own per-crate `ConfigError`, drifted apart.
y-scope/spider#362 replaced them with one `YamlConfig` trait and a blanket impl over
`DeserializeOwned`. A forwarding `Arc` impl lets generic code keep requiring `Trait + Clone`, and
lets a test hand an `Arc<Mock>` to an actor while keeping a handle to inspect it. The `?Sized` bound
is what makes `Arc<dyn Trait>` work. Blanket impls are hard to undo, though: coherence forbids a
more specific impl for any type the blanket impl already covers (E0119), and adding a blanket impl
to a published trait is a breaking change.

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

**Sources.** y-scope/spider#362, spider components/spider-utils/src/config.rs, spider
components/spider-execution-manager/src/client/liveness.rs, RustTraining
rust-patterns-book/src/ch02-traits-in-depth.md, RustTraining
type-driven-correctness-book/src/ch08-capability-mixins-compile-time-hardware-.md

## TLC-10: Use typestate only for statically ordered protocols, and keep state data inside the state

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
`TaskContext` for all task kinds (y-scope/spider#390), and documented rather than typed an
internal-only invariant (y-scope/spider#408).

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

**Sources.** RustTraining
type-driven-correctness-book/src/ch05-protocol-state-machines-type-state-for-r.md, RustTraining
type-driven-correctness-book/src/ch11-fourteen-tricks-from-the-trenches.md, RustTraining
type-driven-correctness-book/src/ch01-the-philosophy-why-types-beat-tests.md, y-scope/spider#390,
y-scope/spider#408

# Defensive programming

Defensive code assumes three things: input is hostile, peers retry, crash and restart, and the next
person to touch the code will add a variant, raise a constant or reorder a step. The goal is not to
check everything everywhere. Let the compiler catch what it can, check once at the boundary what it
can't, and make any remaining violation loud and attributable rather than quiet and corrupting. This
matters most in long-running services like ours, where a silently wrong value or a stray panic in a
coordinator costs far more than an error returned to one caller.

## DEF-1: Match every variant of the enums you own; no catch-all arm

**Rule.** In a `match` over an enum defined in the workspace, list every variant, grouping them with
`|` where they share a body, and never end with `_ =>`. Use `_` only for open domains (integers,
strings) and foreign `#[non_exhaustive]` enums, and there the fallback must be the conservative
outcome (an error, "not retriable", `INTERNAL`), never success.

**Why.** An exhaustive match turns "someone added a variant" into a compile error at every place
that has to decide what the variant means, and a `_` arm sends it to whatever the default was
instead. Spider keeps hitting this. `StaleStateError::JobAlreadyStarted` fell through a `_` in the
gRPC error mapping and reached clients as `INTERNAL`, which stopped them re-attaching to a running
job after a restart (y-scope/spider#509). The execution manager's task-registration match ends in
`_ =>`, so `StorageResponseError::Transport`, documented as "callers may back off and retry", takes
the fatal bail-out path, and a brief storage blip stops the execution manager. A precondition check
in the job tree ends in `_ => Ok(())`, so it accepts any job state added later. `matches!`
classifications have the same hole, because they keep compiling when a variant is added: adding
`BlockingOnChildren` meant finding `ensure_commit_ready` by hand (y-scope/spider#531).

```rust,ignore
// Bad
match &err {
    StorageResponseError::StaleSession(_) | StorageResponseError::CacheStale(_) => Ok(None),
    _ => Err(RuntimeError::StorageResponse(err)), // retryable `Transport` lands here
}
```

```rust,ignore
// Good
match &err {
    StorageResponseError::StaleSession(_) | StorageResponseError::CacheStale(_) => Ok(None),
    StorageResponseError::Transport(_) => {
        tokio::time::sleep(backoff(retry, MAX_BACKOFF)).await;
        Ok(None)
    }
    StorageResponseError::Server(_) | StorageResponseError::InvalidInput(_) => {
        Err(RuntimeError::StorageResponse(err))
    }
}
```

**Review.**
- Flag `_ =>` (and unused `other =>` bindings) in a match over a workspace enum, and ask for the
  variants to be listed. Look hardest at state-transition tables (`is_valid_transition` should match
  the target state exhaustively), error-to-status-code mappings (ERR-6), and retry-or-fatal
  classifications.
- When a PR adds a variant, grep for `matches!(` and `is_*()` predicates that mention its siblings
  (e.g. `ensure_commit_ready`), since the compiler won't flag them, and check each one. A `matches!`
  that checks a single variant's identity (`is_running`) is fine. One that encodes a classification
  ("is ready to commit") should be an exhaustive `match`.
- Flag `#[non_exhaustive]` on an enum that other crates in the workspace match on: it forces those
  crates to add the `_` arm this rule forbids (see MOD-2). When code consumes a struct field by
  field (a `From` impl, a mapping to a proto), ask for a full destructure with `field: _` for
  ignored fields, so that adding a field also breaks the build.

**Exceptions.** Open domains (integers, strings), and foreign or `#[non_exhaustive]` enums such as
`tonic::Code`, where the wildcard must pick the safe default (ERR-8 covers `From` impls for foreign
enums).

See also: coding-style.md § Enum vs Trait Objects (exhaustiveness is the reason that section
exists), TYPE-6 (parsing closed sets into enums).

**Sources.** y-scope/spider#509, y-scope/spider#480, y-scope/spider#524, y-scope/spider#531, spider
components/spider-execution-manager/src/runtime.rs, spider
components/spider-execution-manager/src/client/storage.rs, spider
components/spider-storage/src/cache/tree/event.rs, spider
components/spider-storage/src/cache/job.rs, spider components/spider-core/src/job.rs, RustTraining
type-driven-correctness-book/src/ch07-validated-boundaries-parse-dont-validate.md, RustTraining
csharp-book/src/ch01-introduction-and-motivation.md

## DEF-2: Run every check that can fail before the first mutation

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

**Sources.** y-scope/spider#554, y-scope/spider#560, y-scope/spider#290, y-scope/clp#2150, spider
components/spider-core/src/task/task_graph.rs, spider components/spider-storage/src/cache/task.rs,
spider components/spider-storage/src/partial_mutation.rs, spider
components/spider-storage/src/task_instance_pool.rs, RustTraining
c-cpp-book/src/ch18-cpp-rust-semantic-deep-dives.md

## DEF-3: Make check-then-act atomic, and let progress state only move forward

**Rule.** A state check and the mutation it guards happen in one atomic step: `entry()` on maps, a
single `compare_exchange`, `fetch_update` or `fetch_max` on atomics, and in the DB either
`SELECT ... FOR UPDATE` in the same transaction or a guarded `UPDATE ... WHERE state = ?` whose
`rows_affected` is checked against the expected count (BND-3 covers the SQL forms). Never write a
persisted status unconditionally, not even to mark something failed. Epochs, session IDs and cursors
only move forward: expose `try_advance`, not `set`, and drop stale-epoch work at every point where
work is consumed.

**Why.** Between a check and a separate write, another task, another process or a restarted
coordinator can change the state. In clp, marking a query job failed "regardless of its current
status" could overwrite a terminal `Cancelled` set by the API server. A `contains_key` followed by a
separate `insert` on the session map would have let one session silently overwrite another. Progress
state that can go backwards is the same bug over time: the S3 scanner overwrote its cursor with
`None` after an empty scan and re-ingested the same object 286 times (y-scope/clp#2333). Spider
stamps every assignment with a session ID that only advances through a CAS, and drops stale
assignments at dequeue, hint redemption, reschedule drain and completion.

```rust,ignore
// Bad
if sessions.contains_key(&token) {
    return Err(SessionError::TokenCollision(token));
}
sessions.insert(token, state);

sqlx::query("UPDATE query_jobs SET status = ? WHERE id = ?")
    .bind(QueryJobStatus::Failed)
    .bind(id)
    .execute(&pool)
    .await?;

self.start_after = scan_prefix(&client, &self.start_after).await?;
```

```rust,ignore
// Good
let Entry::Vacant(entry) = sessions.entry(token) else {
    return Err(SessionError::TokenCollision(token));
};
entry.insert(state);

let mut tx = pool.begin().await?;
let from = lock_and_get_status(&mut tx, id).await?; // `SELECT ... FOR UPDATE`
if !QueryJobStatus::is_valid_transition(from, QueryJobStatus::Failed) {
    return Err(Error::InvalidQueryJobStatusTransition { from, to: QueryJobStatus::Failed });
}
update_status(&mut tx, id, QueryJobStatus::Failed).await?;
tx.commit().await?;

if let Some(last_key) = scan_prefix(&client, &self.start_after).await? {
    self.start_after = Some(last_key);
}
```

**Review.**
- Flag a `contains_key` or `get` followed by `insert` or `remove`, a `load` followed by `store`, and
  a status read under one lock or in one statement followed by a write under another. The fix is
  `entry()`, one CAS, or a locked read in the same transaction. For async locks, see ASYNC-5
  (re-check under the write guard).
- Flag `UPDATE ... SET status = ?` without a from-state guard, and any guarded write whose
  `rows_affected` is ignored. A mismatch is a corruption error such as `CorruptedDbState`, not a
  silent skip. A second "confirmation" `SELECT` that could only disagree if the DB were corrupt adds
  round trips and locks without adding safety.
- Flag `self.cursor = <Option-returning fetch>` and any raw `set` or `store` on an epoch. Work that
  can outlive a reset must carry its epoch and be checked at each consumer, not only once.

**Exceptions.** State owned by a single writer (an actor, a committer) is already atomic where that
writer checks and acts (ASYNC-9). A caller-side check is fine as long as it is advisory and the
single writer re-checks the precondition before committing, as Spider's committer does with
`StateRequirement`.

**Sources.** y-scope/clp#2513, y-scope/clp#2617, y-scope/clp#2689, y-scope/clp#2662,
y-scope/clp#2333, y-scope/clp#2038, y-scope/spider#373, y-scope/spider#328, spider
components/spider-core/src/session.rs, spider components/spider-scheduler/src/service.rs, spider
components/spider-storage/src/cache/job.rs, spider
components/spider-storage/src/db/mariadb/tree_transition.rs

## DEF-4: Turn unknown, missing or unsupported input into an error, never a plausible value

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
with `UnsupportedJobConfig` (y-scope/clp#2565). Wrapping a KQL query in parentheses to avoid one
failure would have turned the syntax error `a) AND (b` into the valid `(a) AND (b)`. Defaulting the
AWS region inside a shared helper sent AWS users to the wrong region. Now the caller, which knows
the context, validates the input and picks the default.

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

**Sources.** y-scope/clp#2565, y-scope/clp#2578, y-scope/clp#2512, y-scope/clp#1776,
y-scope/clp#2623, spider components/spider-task-executor/src/bin/spider_task_executor.rs,
RustTraining type-driven-correctness-book/src/ch07-validated-boundaries-parse-dont-validate.md,
RustTraining type-driven-correctness-book/src/ch17-redfish-applied-walkthrough.md

## DEF-5: Cap every resource that a peer or a config value can size

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
until the limits were made explicit and checked against each other (y-scope/spider#560). In clp, a
max-results limit applied only to the Mongo path left file-backed results unbounded
(y-scope/clp#2180), and a per-file timeout formula pushed tasks of more than 288 files past Spider's
24 h maximum, so job submission failed (y-scope/clp#2668).

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

See also: TYPE-7 (the lower bound: `NonZero*`), DEF-9 and BND-7 (lengths read from bytes), ASYNC-6
(bounded queues).

**Sources.** spider components/spider-scheduler/src/dispatch_queue.rs, spider
components/spider-proto-rust/src/unpack/scheduler.rs, spider
components/spider-core/src/compression.rs, spider components/spider-storage/src/limits.rs,
y-scope/spider#560, y-scope/spider#472, y-scope/spider#395, y-scope/spider#288, y-scope/clp#2180,
y-scope/clp#2661, y-scope/clp#2668, y-scope/clp#2689

## DEF-6: Return errors for what the environment can cause, and fail the whole service for broken invariants

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
  An `expect` on a fact proven earlier in the same function, such as DEF-2's validated index, stays.
- Flag comments that state an assumption about a constant or a limit relation, and ask for a const
  assert inside the function that relies on it. Also flag checks that only accept the current
  backend's behaviour (session ID 0 "never" coming from MariaDB) when the documented contract allows
  it.

**Exceptions.** Synchronous startup and CLI code, where unwinding already takes the process down,
and test helpers (coding-style.md § Panic in test helpers when the failure means the test is wrong).

See also: pr-review.md § Panic vs error returns; coding-style.md § Assert preconditions instead of
tolerating them and § Using `unwrap`; ERR-1 (the fatal error tier) and ASYNC-4 (routing fatal errors
to the shutdown handle).

**Sources.** spider components/spider-scheduler/src/execution_manager_registry.rs, spider
components/spider-scheduler/src/runtime.rs, spider components/spider-scheduler/src/grpc.rs, spider
components/spider-execution-manager/src/liveness.rs, spider
components/spider-scheduler/src/core_impl/resource_group_round_robin/scheduling_state.rs,
y-scope/spider#464, y-scope/spider#462, y-scope/spider#342, y-scope/spider#359, y-scope/spider#549,
y-scope/spider#557, y-scope/clp#2689, y-scope/clp#2661, y-scope/clp#2420, y-scope/clp#2513,
RustTraining type-driven-correctness-book/src/ch15-const-fn-compile-time-correctness-proofs.md

## DEF-7: Retry only transient failures, with backoff, and only idempotent operations

**Rule.** Retry through one helper that takes an `is_retriable` classifier, a finite attempt budget,
and capped exponential backoff with jitter computed without overflow (see DEF-8). Retry only
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
- For each retry loop or `call_with_retry`, check for a classifier (itself an exhaustive match, per
  DEF-1), a budget, a cap and jitter, and check that only the network round-trip sits inside the
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

**Sources.** y-scope/clp#2573, y-scope/clp#2402, y-scope/clp#2589, y-scope/clp#2646,
y-scope/clp#2035, y-scope/spider#396, y-scope/spider#319, spider
components/spider-utils/src/grpc/retry.rs, spider components/spider-client/src/grpc/job.rs, spider
components/spider-execution-manager/src/runtime.rs, RustTraining
async-book/src/ch13-production-patterns.md, RustTraining
rust-patterns-book/src/ch07-closures-and-higher-order-functions.md

## DEF-8: Choose an overflow behaviour for every arithmetic on unbounded values

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
callable (DEF-5's `MAX_TASK_INSTANCE_MESSAGE_SIZE as u64`).

See also: coding-style.md § Use `u64` for sizes that may exceed 32-bit; pr-review.md § Panic vs
error returns (which classes overflow from external IDs as an error).

**Sources.** y-scope/spider#396, y-scope/spider#472, y-scope/spider#395, y-scope/spider#290, spider
components/spider-utils/src/grpc/retry.rs, spider components/spider-storage/src/cache/job.rs, spider
components/spider-scheduler/src/core_impl/resource_group_round_robin/dispatch_queue.rs, spider
components/spider-task-executor/src/bin/spider_task_executor.rs, y-scope/clp#2435, y-scope/clp#2402,
y-scope/clp#2403, RustTraining engineering-book/src/ch07-release-profiles-and-binary-size.md,
RustTraining rust-patterns-book/src/ch14-testing-and-benchmarking-patterns.md, RustTraining
type-driven-correctness-book/src/ch07-validated-boundaries-parse-dont-validate.md

## DEF-9: Decode external input with checked slicing, never indexing

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
check, then a slice) in sibling parsers of the same format. The chunk APIs also hand back
`&[u8; N]`, so there is no impossible `try_into` error left to invent a message for.

```rust,ignore
// Bad
let count = u32::from_le_bytes(data[0..4].try_into().map_err(|_| WireError::InvalidFormat("unreachable"))?);
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

**Sources.** See also BND-7 (bounding byte streams from peers) and TEST-8 (feeding decoders byte by
byte). spider components/spider-utils/src/wire.rs, y-scope/spider#308, spider
components/spider-core/src/types/io/task_graph_input.rs, y-scope/clp#2649, RustTraining
rust-patterns-book/src/ch11-serialization-zero-copy-and-binary-data.md, RustTraining
c-cpp-book/src/ch17-2-avoiding-unchecked-indexing.md

## DEF-10: Confine `unsafe` behind a safe API, and state its contract in the right place

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

**Sources.** spider components/spider-tdl/src/ffi.rs, spider components/spider-tdl/src/register.rs,
spider components/spider-task-executor/src/manager.rs, RustTraining
rust-patterns-book/src/ch12-unsafe-rust-controlled-danger.md, RustTraining
rust-patterns-book/src/ch06-concurrency-vs-parallelism-vs-threads.md, RustTraining
rust-patterns-book/src/ch10-error-handling-patterns.md, RustTraining
type-driven-correctness-book/src/ch11-fourteen-tricks-from-the-trenches.md, RustTraining
engineering-book/src/ch05-miri-valgrind-and-sanitizers-verifying-u.md

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
`match` that lists every variant, so that adding a variant forces a decision about its fatality
(DEF-1).

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

**Sources.** spider components/spider-storage/src/cache/error.rs, spider
components/spider-storage/src/state/error.rs, y-scope/spider#290, y-scope/spider#293,
y-scope/spider#354, y-scope/spider#524, y-scope/spider#525, y-scope/spider#539. See also:
pr-review.md § Panic vs error returns (this rule adds a third tier: a returned error that is fatal
to the service), and DEF-6 (when to return an error and when to panic).

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
  the source of truth before choosing between not-found and wrong-state (spider#535).

**Exceptions.** In a best-effort loop (ERR-9), skipping bad items can be the documented policy. Log
each skipped item with its ID and its error. `.ok()` is fine when "absent" and "invalid" really mean
the same thing; say why in a comment.

**Sources.** spider components/spider-storage/src/state/service.rs, spider
components/spider-storage/src/db/mariadb/mysql_error.rs, y-scope/spider#535, RustTraining
type-driven-correctness-book/src/ch07-validated-boundaries-parse-dont-validate.md, RustTraining
c-cpp-book/src/ch09-error-handling.md, RustTraining
csharp-book/src/ch09-1-crate-level-error-types-and-result-alias.md. See also: pr-review.md § Don't
silently swallow errors (this rule adds the wrong-mapping case and the iterator form),
coding-style.md § `map_err` for error translation (the downcast pattern), TYPE-4 and DEF-4 (absence
and unknown input).

## ERR-3: Add a variant only when a caller reacts differently, and give it typed fields

**Rule.** Each variant names one condition that some caller handles differently from the other
variants. It carries the facts the caller can't reconstruct (the ID, `{ from, to }`,
`{ expected, actual }`) as named, typed fields. Library code must not use `Result<T, String>`,
`type Error = String`, catch-all `Other(String)` variants, or fields that repeat what the caller
passed in.

**Why.** Callers can't recover from errors they can't tell apart. In y-scope/clp#2513, a finaliser
had to tell "lost a race to a terminal state" from "the row is gone", but `SqlxNoRowsAffected` hid
three different situations, so callers swallowed real problems. String payloads force callers and
tests to match on message text, which spider#281 called "a code smell". Too many variants is also a
failure: variants that no caller tells apart only add match arms and tests (spider#449). A variant
named after a guessed cause, such as `IllegalResourceGroupId` for what may be a wrong password,
sends operators down the wrong path (spider#464). Write the message for the condition the variant
represents, not for the first call site, so it stays true when the variant is reused (spider#342).

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
cause, for example "the task graph failed to deserialize" (spider#281). Errors that cross a process
or FFI boundary, such as Spider's serializable `ExecutorError`, may be string-based. A custom
`Deserialize` impl reports through `serde::de::Error::custom`, which carries only a message.

**Sources.** y-scope/clp#2513, y-scope/spider#281, y-scope/spider#283, y-scope/spider#309,
y-scope/spider#342, y-scope/spider#449, y-scope/spider#464, y-scope/spider#480, spider
components/spider-core/src/task/mod.rs, RustTraining
type-driven-correctness-book/src/ch07-validated-boundaries-parse-dont-validate.md. See also:
pr-review.md § `anyhow` vs custom errors, coding-style.md § API design (named fields over positional
tuples).

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
signature, just so the error can be logged in the end. y-scope/clp#2705 boxed the termination error
so that `SessionEvent` stays non-generic. Boxing also keeps `Result` small, which
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

**Sources.** y-scope/clp#2705, clp components/clp-rust-libs/query-result-listener/src/error.rs, clp
components/clp-rust-libs/query-result-listener/src/session.rs, spider
components/spider-scheduler/src/core_impl/inbound_queue_reader.rs, spider
components/spider-client/src/error.rs, spider components/spider-core/src/types/resource_group.rs,
y-scope/spider#283, y-scope/spider#353, RustTraining
type-driven-correctness-book/src/ch11-fourteen-tricks-from-the-trenches.md.

## ERR-5: Handle an error once: return it, or log it where the decision is made

**Rule.** A function either propagates an error (with `?`, adding context) or handles it (logs and
recovers, skips, or cancels), never both. Log in the layer that makes the decision, usually the task
entry point, the spawn or join site, or `main`. Attach the identifying fields (`job_id`, `task_id`)
with `inspect_err`. Log through `tracing`, including in `Drop` impls, and never through `eprintln!`.
A helper returns `Result`; it doesn't log internally and then return `Option`.

**Why.** The Spider scheduler core's error is logged three times: in `run`, in the spawn wrapper,
and in `Runtime::stop`. One failure therefore looks like three incidents. A helper that logs and
then returns `Option` hides which layer made the decision and leaves the caller unable to propagate
the error or add context (y-scope/clp#2435). The outermost boundary is the last place where the job
and task IDs are available. Spider's task runtime records only a status and a message, so a task
that returns an error without logging leaves nothing to debug with (y-scope/clp#2646). `eprintln!`
bypasses the file and collector sinks that tracing sets up (y-scope/clp#2286). In `main`, don't let
both tracing and anyhow's `Termination` print the same error (y-scope/clp#1783).

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
  log point → carry the log point over to the new code (y-scope/clp#2643).

**Exceptions.** A helper may log internally when it has to branch both its logging and its reaction
on the error kind (`create_job_handle` in y-scope/clp#2435). An operation that is best-effort by
design logs its own failure and returns `()` (ERR-9).

**Sources.** spider components/spider-scheduler/src/runtime.rs, spider
components/spider-scheduler/src/core_impl/resource_group_round_robin/implementation.rs,
y-scope/clp#1740, y-scope/clp#1783, y-scope/clp#2286, y-scope/clp#2435, y-scope/clp#2643,
y-scope/clp#2646, y-scope/spider#398. See also: coding-style.md § Log field formatting,
coding-style.md § Error messages, TEST-9 (structured fields and spans).

## ERR-6: Translate errors to wire responses in one exhaustive place, without leaking internals

**Rule.** At a gRPC or HTTP edge, convert domain errors to `Status` codes or responses in one place.
A default handler decides the log level and whether to cancel the service, and it matches every
variant, nested ones included, with no catch-all arm. Each endpoint's handler matches only the
variants that endpoint can produce and forwards the rest to the default handler. Client-caused
variants get specific codes and their `Display` text. Internal variants get a generic body, and the
full error goes to the log.

**Why.** With a catch-all arm, a new variant quietly gets `INTERNAL` and nobody decides whether it
should be a 404, retryable, or fatal (spider scheduler grpc.rs). Fatal arms copied into each handler
drift apart: one refactor made stray errors cancel the storage service in handlers where they should
have been non-fatal (spider#364). Putting an internal error (SQL text, an AWS SDK error, a file
path) in the response body exposes infrastructure details (y-scope/clp#1740). An arm for a variant
that the path can't produce tells readers that it can happen (spider#369: "This can never happen for
user-interfacing API").

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

**Sources.** spider components/spider-scheduler/src/grpc.rs, spider
components/spider-storage/src/grpc.rs, y-scope/spider#364, y-scope/spider#369, y-scope/spider#539,
y-scope/clp#1740, y-scope/clp#2058, clp components/log-ingestor/src/routes.rs. See also: BND-9 (what
each status code means across the system, and the client-side decoder).

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
control flow as a failure and blocks reuse, for example from cleanup tasks (spider#390). The
opposite mistake, an `Option` where the empty case is a failure, lets an empty input through as
success (y-scope/clp#2643). An `UPDATE` that matches no row returns `Ok`, so cancelling a mistyped
job ID returned 200 (y-scope/clp#1964). Sibling functions must agree: `get_status` and
`request_cancellation` on a missing job should behave the same way (y-scope/clp#2617).

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

**Sources.** spider components/spider-execution-manager/src/process_pool.rs, spider
components/spider-scheduler/src/core_impl/resource_group_round_robin/scheduling_state.rs, clp
components/api-server/src/webui_client/metadata.rs, y-scope/spider#390, y-scope/clp#1964,
y-scope/clp#2058, y-scope/clp#2607, y-scope/clp#2617, y-scope/clp#2643. See also: TYPE-9 (named
outcome enums instead of `bool`).

## ERR-8: Use `#[from]` only when the source type has one meaning; write `From` impls by hand when they carry policy

**Rule.** `#[from]` (or any `From` impl) turns every `?` on that source type anywhere in the crate
into that variant, so add it only when that's correct at every call site. When the same source type
can come from several operations, use `map_err` at the call site to build a variant that carries
context. When the conversion classifies the error, write the `From` impl by hand. When converting a
foreign enum, match every variant by name.

**Why.** `ExecutorCreationFailure(#[from] std::io::Error)` labels the next unrelated I/O failure as
a spawn failure. `From<rmp_serde::decode::Error>` mapping to `ErrorPayloadDeserializationFailure`
mislabels every msgpack decode the same way. A blanket `#[from] io::Error` with no path field makes
every `?` report "No such file" without saying which file. A hand-written
`From<DbError> for CacheError` that routes to `Internal` makes the classification "a DB failure
means the cache may be inconsistent" visible in the diff (spider#354). An exhaustive match means a
variant added by a dependency upgrade has to be classified explicitly, instead of silently landing
in the wrong bucket (y-scope/clp#2649).

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
parameterized per operation, because the whole family has one meaning (y-scope/clp#1728). A
`#[non_exhaustive]` foreign enum (`sqlx::Error`, `io::ErrorKind`) forces a `_` arm: name every
variant you know, and send the `_` arm to the most conservative category, usually internal (DEF-1).

**Sources.** spider components/spider-task-executor/src/error.rs, spider
components/spider-execution-manager/src/process_pool.rs, y-scope/spider#354, y-scope/clp#2649,
y-scope/clp#1728, RustTraining rust-patterns-book/src/ch15-crate-architecture-and-api-design.md. See
also: coding-style.md § `map_err` for error translation.

## ERR-9: Make best-effort explicit in the signature

**Rule.** An operation that is best-effort by design returns `()`, logs its own failures with
context, and discards the result explicitly with `let _ = op().await.inspect_err(|e|
tracing::warn!(..));`. This covers cleanup, acknowledgements, telemetry, and sends to an actor whose
failure is reported elsewhere. For batch and recovery loops, choose either fail-fast (`?`, and the
supervisor restarts) or per-item best-effort (log each item with its ID and continue), and make the
choice visible.

**Why.** When callers routinely discard a `Result` with `let _ =`, some callers start propagating it
while others drop it, so the same operation behaves differently depending on who calls it
(spider#365). A `shutdown_and_join` that returns an error that has already been logged forces every
caller to write a log-and-ignore arm, and that arm looks like a swallowed error (y-scope/clp#2035).
On a failure path, cleanup of an external resource, such as cancelling the Spider job that a failed
`start` left behind, must not replace the original error. Discarding the cleanup failure silently,
though, hides why resources leak (y-scope/clp#2573). In a recovery loop, one bad config row
shouldn't stop recovery of every other job, while a lost DB connection should trigger a restart
(y-scope/clp#2053).

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

**Sources.** y-scope/spider#341, y-scope/spider#365, y-scope/clp#1989, y-scope/clp#2035,
y-scope/clp#2053, y-scope/clp#2573, clp components/log-ingestor/src/ingestion_job_manager.rs. See
also: pr-review.md § Don't silently swallow errors (this rule is the case where discarding the error
is the intended design, and says how to discard it), and ASYNC-3 (where a spawned task's failure
goes).

## ERR-10: Give fallible trait methods an associated `Error` type

**Rule.** If any reasonable implementation of a trait method can fail (encoding, I/O, parsing),
declare `type Error: std::error::Error + Send + Sync + 'static;` and return `Result<_,
Self::Error>`. When one trait binds another, tie their error types together (`type Encoder:
ResultEncoder<Error = Self::Error>`). Infallible implementations use `std::convert::Infallible`
(TLC-6).

**Why.** The trait author doesn't know every implementation, and an encoder that writes to a file or
a stricter format can fail. An infallible signature then forces implementers to call `expect`. The
panic kills the spawned connection task without telling the session's consumer, so results are
silently lost and the job can still be reported as succeeded (y-scope/clp#2690, y-scope/clp#2702).
With a typed error, the caller can fail the session and log the error where someone will see it.

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
y-scope/clp#2702 because no implementation can fail.

**Sources.** y-scope/clp#2690, y-scope/clp#2702, clp
components/clp-rust-libs/query-result-listener/src/encoding.rs. See also: pr-review.md § Panic vs
error returns, TLC-6 (associated types and `Infallible`).

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

**Sources.** y-scope/spider#390, y-scope/spider#397, y-scope/spider#280, y-scope/spider#281, spider
components/spider-core/src/types/io/task_graph_input.rs, spider
components/spider-scheduler/src/core_impl/resource_group_round_robin/implementation.rs

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

**Sources.** y-scope/spider#283, y-scope/spider#285, y-scope/spider#339, y-scope/spider#524,
y-scope/clp#1927, y-scope/clp#2661

## OBJ-3: Tie mandatory cleanup to a guard's `Drop`, and give the normal path a consuming method

**Rule.** Anything that must happen on every exit runs from the `Drop` of a guard created right
after the acquire step: deregistration, killing a child process, cancelling tasks, escalating a
half-applied mutation, restoring state after a `with_*` closure. If the cleanup can fail or has to
be awaited, also provide a consuming `close(self)`, `commit(self)` or `disarm(self)` for the normal
path, and keep `Drop` as the synchronous, best-effort fallback that never blocks and logs failures
instead of discarding them.

**Why.** An early `?`, a panic and a dropped future all skip a `close()` that callers have to
remember. Before y-scope/clp#2702, dropping a session only unregistered it, and its open connections
kept streaming. Spider's `PartialMutationGuard` turns "the cache was mutated but the DB write
returned `Err` or was cancelled" from a silent inconsistency into a fatal shutdown, which recovery
then repairs from the DB (DEF-2). `Drop` cannot `.await`, so the only async work it can start is a
spawned task, and that task cannot report back: `tokio::spawn` panics if the value is dropped
outside a runtime, and a `let _ =` inside the task swallows the one error the caller cared about.
That is why awaited, fallible cleanup needs a consuming method the caller can `?`. Note also that
`Drop::drop` runs before the struct's own fields are dropped, so a value that must be dropped after
the guard's action, such as a reply sender that wakes a waiter, belongs inside the guard.

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

**Sources.** y-scope/clp#2689, y-scope/clp#2702, y-scope/clp#2014, y-scope/clp#2286, spider
components/spider-storage/src/partial_mutation.rs, spider
components/spider-storage/src/state/tree_committer/mod.rs, spider
components/spider-execution-manager/src/process_pool.rs, spider
components/spider-execution-manager/src/runtime.rs, RustTraining
async-book/src/ch12-common-pitfalls.md, RustTraining
rust-patterns-book/src/ch07-closures-and-higher-order-functions.md, RustTraining
rust-patterns-book/src/ch15-crate-architecture-and-api-design.md

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

**Sources.** y-scope/spider#341, y-scope/spider#418, y-scope/clp#2513, y-scope/clp#2504,
y-scope/clp#2564

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

**Sources.** y-scope/spider#319, y-scope/spider#365, y-scope/spider#360, y-scope/spider#527,
y-scope/spider#290, y-scope/spider#309, y-scope/clp#1740, spider
components/spider-core/src/session.rs, spider components/spider-utils/src/shutdown.rs, RustTraining
type-driven-correctness-book/src/ch16-send-sync-compile-time-concurrency-proofs.md, RustTraining
c-cpp-book/src/ch17-best-practices.md

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

**Sources.** y-scope/clp#2689, y-scope/spider#449, y-scope/spider#309, y-scope/spider#443, spider
components/spider-scheduler/src/dispatch_queue.rs, spider
components/spider-scheduler/src/core_impl/resource_group_round_robin/dispatch_queue.rs

## OBJ-7: Take required builder arguments up front and finish with a consuming `build(self)`

**Rule.** Pass required values to the builder's own constructor (`Type::builder(required)`), and
make optional settings consuming `#[must_use]` setters. `build(self)` is the only way to get the
target: it runs any mandatory finalization itself and keeps those steps private. A fallible `add`
validates its input before it changes any state (DEF-2).

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
with `build` only on the fully set state) is worth its extra type parameters (TLC-10). For one or
two required fields, constructor arguments are enough.

See also: coding-style.md § Take ownership when the value mustn't be used afterwards.

**Sources.** y-scope/clp#2403, y-scope/clp#2620, y-scope/spider#396, y-scope/spider#374, spider
components/spider-scheduler/src/runtime.rs, spider components/spider-storage/src/state/service.rs,
RustTraining type-driven-correctness-book/src/ch11-fourteen-tricks-from-the-trenches.md,
RustTraining csharp-book/src/ch05-1-constructor-patterns.md

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

**Sources.** y-scope/clp#2649, y-scope/clp#2617, y-scope/clp#2646, y-scope/spider#280,
y-scope/spider#286

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

**Sources.** y-scope/clp#2531, y-scope/clp#2550, y-scope/clp#2581, y-scope/spider#340,
y-scope/spider#342, clp components/clp-rust-libs/clp-rust-utils/src/types.rs

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
  the team's answer in y-scope/spider#272 was "add it in future PRs on demand"), and derives such as
  `strum::EnumIter` whose last user was removed.
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

**Sources.** y-scope/spider#272, y-scope/spider#285, y-scope/spider#290, y-scope/spider#341, spider
components/spider-storage/src/cache/tree/event.rs, RustTraining
type-driven-correctness-book/src/ch03-single-use-types-cryptographic-guarantee.md, RustTraining
c-cpp-book/src/ch17-best-practices.md

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

**Sources.** y-scope/spider#292, y-scope/spider#293, y-scope/spider#310, spider
components/spider-core/src/task/type_descriptor.rs (`struct_from_name`), RustTraining
rust-patterns-book/src/ch15-crate-architecture-and-api-design.md. See also: pr-review.md §
Conversely: don't take ownership when a reference suffices, pr-review.md § Prefer references over
`Arc`/`Vec` when ownership isn't needed.

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

**Sources.** y-scope/clp#2512, spider components/spider-core/src/task/task_graph.rs
(`get_parent_indices`, `get_task_graph_input_indices`), RustTraining
csharp-book/src/ch07-3-smart-pointers-beyond-single-ownership.md. See also: coding-style.md § Use
`&str` for read-only string access.

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

**Sources.** y-scope/spider#430 (fixes y-scope/spider#429), spider
components/spider-execution-manager/src/client/grpc/scheduler.rs, spider
components/spider-scheduler/src/core_impl/resource_group_round_robin/job_registry.rs, spider
components/spider-scheduler/src/core_impl/resource_group_round_robin/scheduling_state.rs.

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
  and that the helper's bound states `Send` on the future when callers spawn it. For a public async
  API that must be spawnable, ask for a compile-time `Send` assertion on its futures, as
  spider-client does (TLC-5); shared counters in such closures, including in tests, must be `Sync`
  (`AtomicUsize`, not `Cell<usize>`).
- Compare each callback bound with how the body calls it: `FnOnce` if called once, `FnMut` if called
  repeatedly in sequence, `Fn` only for shared or concurrent calls, and `Send + 'static` only when
  the closure is spawned or stored. A stronger bound rejects valid closures and forces callers into
  `Arc`.

**Exceptions.** Async callbacks that run in place and whose futures are never spawned may take
`AsyncFnMut` (y-scope/clp#2224; see ASYNC-10).

**Sources.** y-scope/spider#404, spider components/spider-utils/src/grpc/retry.rs, spider
components/spider-client/src/grpc/job.rs, spider components/spider-client/src/client.rs
(`assert_client_futures_send`), RustTraining
rust-patterns-book/src/ch07-closures-and-higher-order-functions.md. See also: DEF-7 (what a retry
helper must classify and bound).

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

**Sources.** y-scope/clp#2664, y-scope/clp#2690, clp
components/clp-rust-libs/query-result-listener/src/encoding.rs (`ResultEncoder`), clp
components/clp-rust-libs/query-result-listener/src/protocol.rs (`read_str`), RustTraining
c-cpp-book/src/ch17-1-avoiding-excessive-clone.md.

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

**Sources.** y-scope/spider#362, spider components/spider-execution-manager/src/client/liveness.rs,
spider components/spider-execution-manager/src/runtime.rs. See also: pr-review.md § Prefer
references over `Arc`/`Vec` when ownership isn't needed, TLC-9 (when a blanket or forwarding impl is
appropriate).

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

**Sources.** RustTraining c-cpp-book/src/ch17-1-avoiding-excessive-clone.md, RustTraining
c-cpp-book/src/ch16-cases-3-5-lifetime-borrowing.md. See also: pr-review.md § Conversely: don't take
ownership when a reference suffices.

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

**Sources.** spider components/spider-client/src/client.rs (`tokio::try_join!`), RustTraining
async-book/src/ch09-when-tokio-isnt-the-right-fit.md, RustTraining
async-book/src/ch16-summary-and-reference-card.md.

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
  outside; direct indexing is acceptable only for indices the arena itself produced (DEF-9). When
  one structure holds two index spaces of the same integer type, ask for newtypes so they cannot be
  swapped.

**Exceptions.** When nodes are mutated concurrently by independent tasks under per-node locks,
one-directional `Arc` links are acceptable, as in spider's runtime task control blocks, which hold
`Arc` handles to their children and only a counter of unfinished parents.

**Sources.** spider components/spider-core/src/task/task_graph.rs, spider
components/spider-storage/src/cache/task.rs (`TaskControlBlock`), RustTraining
c-cpp-book/src/ch16-case-studies.md.

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

**Sources.** y-scope/spider#290, RustTraining
rust-patterns-book/src/ch08-functional-vs-imperative-when-elegance-wins.md.

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

**Sources.** spider components/spider-scheduler/src/service.rs, spider
components/spider-scheduler/src/core_impl/resource_group_round_robin/dispatch_queue.rs,
y-scope/clp#2676, y-scope/clp#2702, clp
components/clp-rust-libs/query-result-listener/src/connection.rs, RustTraining
async-book/src/ch12-common-pitfalls.md

## ASYNC-2: Run multi-step mutations where the caller can't cancel them

**Rule.** A request handler whose body changes shared or durable state across more than one `.await`
must do one of two things. Either each step is a single guarded, idempotent write that recovery can
redo, or the body runs as a task in a `TaskTracker` owned by the service and the handler awaits its
result. Never leave a multi-step mutation inside the handler future itself.

**Why.** tonic (through hyper) drops the handler future when the client resets the stream, closes
the connection, or its `grpc-timeout` expires. In Spider (#522) this could cut a handler off between
the cache update and enqueuing the successor tasks. The job stayed `Running` until the next restart,
and nothing was logged. Running the body as a spawned task makes its lifetime independent of the
request. Spider's helper also holds a tracker token across the shutdown check, so
`TaskTracker::wait()` can't return in the gap between the check and the spawn. It also wraps the
handle in a guard whose `Drop` keeps watching the abandoned body. Without that guard, a dropped
`JoinHandle` would discard a later panic or fatal error (#541).

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
cancellation token is enough. The query-coordinator cancellation monitor (y-scope/clp#2573) is an
example.

**Sources.** y-scope/spider#522, y-scope/spider#541, y-scope/spider#555, spider
components/spider-storage/src/state/service.rs, y-scope/clp#2573

## ASYNC-3: Give every spawned task an owner and a failure destination

**Rule.** Every `tokio::spawn` has an owner that joins it or aborts it. The owner can be a
`JoinHandle` stored in the struct that owns the subsystem, a `JoinSet`, a `TaskTracker`, or an
`AbortOnDropHandle` tied to the value the task serves. Decide at the spawn site where the task's
failure goes. A critical task logs its error and fires the service's shutdown handle. A best-effort
task logs and returns `()` (ERR-9).

**Why.** Dropping a `JoinHandle` does not cancel the task; it detaches it. A detached task keeps
holding connections and locks after its owner is gone, it escapes graceful shutdown, and its panic
or `Err` is never seen. Spider hit this several times. A GC loop and the task-instance pool exited
on error, and nobody noticed until shutdown (#387, #391). A failed `resend_ready_tasks` left jobs
stalled (#374). `tokio::time::timeout(d, handle)` is the same leak in disguise: on timeout it drops
the handle, and the task keeps running.

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
with a comment at the spawn site (y-scope/clp#1736). See also: pr-review.md § Don't silently swallow
errors.

**Sources.** y-scope/spider#374, y-scope/spider#387, y-scope/spider#391, y-scope/spider#309,
y-scope/clp#1736, y-scope/clp#2705, spider components/spider-scheduler/src/runtime.rs, spider
components/spider-execution-manager/src/process_pool.rs, RustTraining
async-book/src/ch08-tokio-deep-dive.md

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
period and were SIGKILLed, losing buffered output (y-scope/spider#416). Spider-storage exited 0
after a fatal error, so `on-failure` restart policies never fired. With no deadline, a single
handler that never returned kept the process alive, and the open socket kept passing health checks
(#527). Separate timers for each shutdown phase can add up past the orchestrator's kill deadline. A
`let _ = timeout(.., join!(..))` that threw away the task results made a crashed pool look like a
clean stop. Also, `JoinError` means "panicked *or* cancelled", so code that labels it as a panic
reports the wrong cause (clp cd8eef5f).

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

**Sources.** y-scope/spider#341, y-scope/spider#346, y-scope/spider#368, y-scope/spider#416,
y-scope/spider#418, y-scope/spider#527, spider components/spider-storage/src/state/runtime.rs,
spider components/spider-storage/src/bin/grpc_server.rs, spider
components/spider-utils/src/shutdown.rs, y-scope/clp commit cd8eef5f

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
`tokio::sync::RwLock<HashMap>` (#321) so that no shard lock is held across an `.await`. Spider's
committer takes `job_execution_state.write()`. A handler that awaited the committer's reply while
still holding the read guard would never get that reply, so `job.rs` drops the guard explicitly
before submitting. A bounded `send` made while holding a cache lock deadlocked the inbound queue
(#523, fixed in #526). Tokio's `RwLock` can't upgrade a read guard to a write guard. If you drop the
read guard and then take the write guard, another task can change the state in between, so check it
again under the write guard (DEF-3).

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
  (y-scope/clp#1704, y-scope/spider#549).
- Flag read-then-write sequences and wrappers that claim to "promote" a lock. The fix is a single
  write guard, or an accessor like `validate_and_write(check)` that checks the state again under the
  write guard.

**Exceptions.** A tokio lock held across an await of purely local work that it is meant to
serialize. Examples are Spider's `Mutex<Option<ExecutorHandle>>` in the process pool (where `None`
means the pool is dead), and the execution-manager registry, which takes the table lock and then the
entry lock and documents what that excludes.

**Sources.** y-scope/spider#293, y-scope/spider#321, y-scope/spider#526, y-scope/spider#549,
y-scope/clp#1704, y-scope/clp#2117, spider components/spider-storage/src/cache/job.rs, spider
components/spider-scheduler/src/execution_manager_registry.rs, spider
components/spider-execution-manager/src/process_pool.rs, RustTraining
async-book/src/ch12-common-pitfalls.md

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
into a busy spin (y-scope/clp#2435). Spider documents each of its unbounded lanes, because the
admission threshold already caps them and a bounded send made under a lock deadlocked (#526). A
consumer that stops when the job's status says "done", instead of when the channel closes, loses a
batch that was claimed but is still waiting for room in the channel (y-scope/clp#2702).

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
  (DEF-5). Put the cap in one owner, and move an item that doesn't fit back to the front of its
  queue.
- Flag semaphore permits acquired inside the spawned task, `try_acquire` polling loops, and
  configured limits that aren't validated against `Semaphore::MAX_PERMITS` (`Semaphore::new` panics
  above it).

**Exceptions.** Inside an actor, `let _ = reply.send(..)` on a `oneshot` is fine, because it only
means the requester went away. Say so in a comment. An unbounded lane is right when a bound already
exists elsewhere and a channel capacity could only reject sends the design depends on (Spider's
inbound queue and per-group dispatch queues).

**Sources.** y-scope/spider#309, y-scope/spider#526, y-scope/spider#557, y-scope/clp#2435,
y-scope/clp#2702, spider
components/spider-scheduler/src/core_impl/resource_group_round_robin/dispatch_queue.rs, spider
components/spider-execution-manager/src/executor_log_collection.rs, RustTraining
rust-patterns-book/src/ch05-channels-and-message-passing.md, RustTraining
async-book/src/ch13-production-patterns.md

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
deadline mandatory there (#449). A separate `Timeout(Duration)` variant lets callers retry or report
a timeout differently from a real failure.

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
  make the buffering deliberate and document its memory bound (y-scope/clp#1728). Never read
  synchronously on the runtime thread to work around it.

**Exceptions.** Short synchronous work, such as parsing a small payload or a short
`std::sync::Mutex` section, is fine inline. A join deadline for an internal task may be a named
constant, such as `CANCELLATION_MONITOR_JOIN_TIMEOUT` (y-scope/clp#2573).

**Sources.** y-scope/spider#449, y-scope/clp#1728, y-scope/clp#2573, spider
components/spider-scheduler/src/core_impl/resource_group_round_robin/dispatch_queue.rs, RustTraining
async-book/src/ch12-common-pitfalls.md, RustTraining async-book/src/ch13-production-patterns.md,
RustTraining async-book/src/ch14-async-is-an-optimization-not-an-architecture.md

## ASYNC-8: Write `biased;` when `select!` priority is part of correctness

**Rule.** Sometimes the result depends on which ready branch wins: a cancellation or failure must
beat ready work, or an end signal must beat an EOF that is already available. In those cases write
`biased;`, list the branches in priority order, and add a one-line comment above the `select!`
explaining why the order matters.

**Why.** `tokio::select!` picks at random among the branches that are ready. Without `biased;`, a
connection of a session that has already failed can still be acknowledged, because its EOF happened
to be polled first (y-scope/clp#2702). These races show up only some of the time: removing `biased`
in #2702 failed the targeted test in only 7 of 12 runs, so a missing keyword gets past CI. `biased;`
has a cost of its own: a branch that is always ready starves every branch after it. So list the
rarely ready, must-win branches (cancellation, session end) first, and don't add `biased;` where
fairness is the goal.

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

**Sources.** y-scope/clp#2702, y-scope/clp#2705, y-scope/spider#341, clp
components/clp-rust-libs/query-result-listener/src/connection.rs, RustTraining
async-book/src/ch12-common-pitfalls.md

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
a failure that didn't cancel sibling tasks (#514, #516, #517). Making the tree committer the only
writer turned these into ordered decisions made in one place (#551). A pool owned by one task needs
no mutex, and its GC can't race registration (#310). The default `MissedTickBehavior::Burst` fires
cycles back-to-back after a stall. After `close()`, `try_recv` can miss a send that is still in
flight, and a request that was drained but never answered leaves its caller waiting forever.

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
token as fire-only (y-scope/spider#418).

**Sources.** y-scope/spider#309, y-scope/spider#310, y-scope/spider#418, y-scope/spider#546,
y-scope/spider#549, y-scope/spider#551, spider components/spider-storage/src/task_instance_pool.rs,
spider components/spider-storage/src/state/tree_committer/mod.rs, spider
components/spider-execution-manager/src/liveness.rs, RustTraining
rust-patterns-book/src/ch05-channels-and-message-passing.md

## ASYNC-10: Design async APIs around laziness and `Send`

**Rule.**
- If a call's side effect must happen when the call is made (enqueuing an event, reserving a slot),
  write a synchronous `fn` that performs it and then returns `impl Future<Output = _> + Send +
  use<>`. Don't write an `async fn` for this.
- Public futures that callers may spawn must be `Send`, asserted at compile time for each method,
  not only for the handle type (TLC-5).

**Why.** An `async fn` does nothing until it is polled. The order in which events reach the actor
then depends on when callers poll, not on when they call, and a future that is dropped before it is
polled never sends anything. With `use<>`, the returned future doesn't borrow `self`, so the caller
can release locks on `self` before awaiting the reply. An async closure's future type can't be
named, so it can't be given a `Send` bound. In Spider it silently became `!Send`, and `SpiderClient`
calls could not be spawned on a multi-threaded runtime (#404). Checking only that the handle is
`Send + Sync` doesn't catch that: a future that holds a non-`Send` value across an `.await` breaks
spawnability while the handle stays `Send + Sync`.

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
- Async callbacks that run in place may take `AsyncFnMut` (y-scope/clp#2224). When the produced
  future must be `Send` (it is spawned, or it backs a public client), use the
  `FnMut() -> FutureType` bound with an owned `async move` future described in OWN-4 (Spider's
  `execute_with_retry`).
- APIs that hand a future or closure to `tokio::spawn` should state `Send + 'static` on their own
  signature, so a violation is reported at the caller. A public client should have one
  `assert_send(&client.method(..))` per method, next to the `Send + Sync` assertion on the handle
  (TLC-5 shows both).
- Flag a call to an `async fn` whose result is never awaited or spawned, and an `async fn` whose
  first statement is a send or reservation that callers expect to happen at call time.

**Sources.** y-scope/spider#404, y-scope/spider#546, y-scope/clp#2224, spider
components/spider-storage/src/cache/tree/control_block.rs, spider
components/spider-utils/src/grpc/retry.rs, spider components/spider-client/src/client.rs,
RustTraining type-driven-correctness-book/src/ch16-send-sync-compile-time-concurrency-proofs.md,
RustTraining async-book/src/ch12-common-pitfalls.md

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
mistake got a different status code and message (raised in review of y-scope/clp#2567, fixed in
y-scope/clp#2581). With `try_from`, the deserialized value is valid by construction, the error names
the offending value and its position, and there is only one validation code path.

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

**Sources.** y-scope/clp#2567, y-scope/clp#2572, y-scope/clp#2581, y-scope/clp#2484, clp
components/clp-rust-libs/clp-rust-utils/src/job_config/search.rs, clp
components/clp-rust-libs/clp-rust-utils/src/types.rs, spider
components/spider-core/src/task/task_graph.rs, y-scope/spider#320, RustTraining
type-driven-correctness-book/src/ch07-validated-boundaries-parse-dont-validate.md, RustTraining
type-driven-correctness-book/src/ch17-redfish-applied-walkthrough.md.

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
and rejects the nested-map form, and Helm values cannot express YAML tags (y-scope/spider#412).

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

**Sources.** spider components/spider-scheduler/src/config.rs, spider
components/spider-scheduler/src/runtime.rs, spider components/spider-storage/src/config.rs, spider
components/spider-storage/src/state/runtime.rs, y-scope/spider#412, y-scope/spider#433,
y-scope/clp#1663, y-scope/clp#1828, y-scope/clp#2452, y-scope/clp#2613, y-scope/clp#2652,
RustTraining rust-patterns-book/src/ch11-serialization-zero-copy-and-binary-data.md.

## BND-3: Guard read-then-write DB transitions in the statement itself

**Rule.** Write a state transition as one `UPDATE ... WHERE id = ? AND <every precondition>` and
check `rows_affected()`. The preconditions are the valid previous states and, where writers can be
superseded, the writer's session or fence. If a transaction must read a value before deciding what
to write, read it with `SELECT ... FOR UPDATE` (or `LOCK IN SHARE MODE` when nothing in the
transaction later writes that row). Each storage method is one transaction, and a failed call leaves
no side effects.

**Why.** In InnoDB and MariaDB, a plain `SELECT` inside a transaction reads a snapshot and takes no
lock. The team once assumed otherwise, and the resulting inconsistent status check needed a
dedicated fix (y-scope/clp#2045). Read, check in Rust, then write is a TOCTOU race, and upgrading a
shared lock to an exclusive one deadlocks under concurrency, which is why spider's transitions bind
both the expected and the target state (y-scope/spider#283). An ownership check done only in memory
let a superseded storage process keep committing transitions after its replacement took over, so
jobs ran twice; the fix fences every write in SQL (issue y-scope/spider#520, fixed in
y-scope/spider#532).

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
- Flag a storage method split into several transactions without a measured reason and a docstring
  stating what a partial failure leaves behind.
- Flag `ON UPDATE CURRENT_TIMESTAMP` on columns with a meaning (`end_at`, `death_confirmed_at`);
  write them explicitly in the transition. Flag vendor-only SQL such as `INSERT ... RETURNING` in
  crates that support both MariaDB and MySQL; use `last_insert_id()`.

**Exceptions.** Large `IN` lists may be batched in bounded transactions; the method's docstring then
says it is not atomic.

See also: coding-style.md § SQL and Database Patterns, DEF-3 (atomic check-then-act in memory and in
the DB).

**Sources.** y-scope/clp#2045, y-scope/clp#2038, y-scope/spider#283, y-scope/spider#292,
y-scope/spider#314, y-scope/spider#450, y-scope/spider#493, y-scope/spider#520, y-scope/spider#532,
y-scope/spider#540, y-scope/spider#557.

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
fields in different orders without a compiler error; y-scope/spider#471 turned such a tuple into
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
  it yet; that backend returns a typed `Unsupported` error itself (y-scope/spider#471).

**Exceptions.** A domain-to-wire conversion that cannot fail on any supported target may use
`expect("...")` stating why.

See also: coding-style.md § API design (named fields over positional tuples), coding-style.md § What
deserves a unit test.

**Sources.** spider components/spider-proto-rust/src/unpack/mod.rs, spider
components/spider-proto-rust/src/unpack/storage.rs, spider
components/spider-proto-rust/src/unpack/scheduler.rs, spider
components/spider-proto-rust/src/job.rs, spider
components/spider-execution-manager/src/client/storage.rs, spider
components/spider-execution-manager/src/client/grpc/storage.rs, y-scope/spider#353,
y-scope/spider#354, y-scope/spider#471.

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
schemas that drift apart (y-scope/clp#2532).

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
  every sub-config (y-scope/spider#346).
- If an env key is optional by default but the operator listed it explicitly, log a warning when it
  is missing (y-scope/spider#389).

**Sources.** spider components/spider-execution-manager/src/config.rs, spider
components/spider-core/src/types/resource_group.rs, spider components/spider-storage/src/config.rs,
spider components/spider-execution-manager/src/client/scheduler.rs, y-scope/spider#341,
y-scope/spider#346, y-scope/spider#379, y-scope/spider#389, y-scope/spider#397, y-scope/clp#2532,
y-scope/clp#2549. See also: TEST-5 (testing env-dependent code without mutating the environment).

## BND-6: Make every default an intended value, owned in one place

**Rule.** Use field-level `#[serde(default)]` only when `Default::default()` is the value you
actually want; otherwise use `default = "fn"` returning a validated type, or make the field
required. For a section whose fields all have defaults, put `#[serde(default)]` on the struct and
write one `impl Default`. When a downstream component owns the default, make the field `Option<T>`
and pass `None` through instead of copying its literal.

**Why.** `#[serde(default)] max_connections: usize` yields 0 when the key is missing: a pool that
hands out no connections, with no error. Without a struct-level default, `{"buffer_config":
{"timeout_sec": 100}}` is rejected with "missing field", because a nested object that is present
must list every field (y-scope/clp#2150). A copied default drifts: Celery and clp-s each hard-coded
a result limit of 1000, so changing one silently made them disagree (y-scope/clp#2503).

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
  absent or null; a required collection is an empty `Vec`, not `None` (y-scope/clp#2087).

See also: coding-style.md § Mirroring Python Types (defaults kept in sync), MOD-2 (a changed default
is a breaking change).

**Sources.** y-scope/clp#2150, y-scope/clp#2503, y-scope/clp#2087, y-scope/clp#1729, spider
components/spider-execution-manager/src/config.rs, spider components/spider-storage/src/config.rs,
RustTraining rust-patterns-book/src/ch11-serialization-zero-copy-and-binary-data.md.

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
end of stream (tokio-rs/tokio#3976, y-scope/spider#418). Real log data contains invalid UTF-8:
strict decoding turned one bad line into a failed query, and `String::from_utf8_lossy` alone was
2-4x slower on valid ASCII than trying `str::from_utf8` first (y-scope/clp#2649).

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

**Sources.** y-scope/spider#418, spider components/spider-execution-manager/src/process_pool.rs,
y-scope/clp#2649, clp components/clp-rust-libs/query-result-listener/src/protocol.rs, clp
components/clp-tdl-package/src/task/query/search.rs, tokio-rs/tokio#3976. See also: DEF-5 (caps on
what a peer can size) and DEF-9 (checked slicing of decoded buffers).

## BND-8: Keep secrets typed, unserialized, out of logs, and compared in constant time

**Rule.** Hold passwords and tokens as `secrecy::SecretString` or `SecretSlice<u8>`, and call
`expose_secret()` only where the value is used. Mark credential fields `#[serde(skip_serializing)]`
on any type that derives `Serialize`. Compare a supplied credential with the stored one using
`subtle::ConstantTimeEq`. Don't log an access-granting value (a session token, a presigned URL) on
the success path.

**Why.** A plain `String` password leaks through `#[derive(Debug)]` into logs and panic messages,
and through re-serializing the config; `SecretString`'s `Debug` prints `[REDACTED]`. `==` on byte
strings may stop at the first differing byte, which leaks timing information. A valid session token
logged on every accepted connection lets anyone who can read the logs join that session
(y-scope/clp#2689). A rejected, unknown token grants nothing, so it may be logged.

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
- Flag `tracing` fields that carry tokens or credentials on accept or success paths; log the peer
  address or task index instead.
- Flag `expose_secret()` results stored in a variable or struct that outlives the call that needs
  the value.

**Sources.** spider components/spider-storage/src/config.rs, spider
components/spider-storage/src/db/mariadb/resource_group.rs, spider
components/spider-core/src/types/resource_group.rs, y-scope/spider#397, y-scope/spider#469,
y-scope/spider#493, y-scope/clp#2689. See also: TYPE-10 (keeping the secret wrapper across internal
APIs).

## BND-9: Treat wire status codes as a contract, and keep client-facing errors coarse

**Rule.** Give each status code one meaning across the whole system, decode statuses into the
client's domain error in a single `status_to_error` function, and change the server mapping and the
client decoder in the same PR. Reserve `UNAVAILABLE` for "retry later, the request itself was fine"
(a lost connection, a server shutting down), never for an application error. Answer "not found" and
"wrong credential" for a protected resource with the same `UNAUTHENTICATED`, and answer internal
failures with a fixed `INTERNAL` message while logging the detail on the server.

**Why.** Storage used to return `UNAVAILABLE` for a stale session and for a fatal cache error, so
the execution manager couldn't tell "reconnect" from "your request is wrong". When
y-scope/spider#358 moved stale sessions to `NOT_FOUND`, the client's catch-all `_ => Server(..)` arm
would have silently absorbed the new code and broken stale-session recovery had the decoder not
changed in the same PR. Separate not-found and bad-password replies let a caller enumerate resource
groups, and internal error strings expose SQL, schema, or cache state.

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
conservative `Server` error (DEF-1).

**Review.**
- Flag RPC methods that inspect `status.code()` themselves, and any server-side change to a status
  code without the matching change to the client decoder. Ask for one decoder test per mapped code
  (TEST-3).
- Flag `Status::unavailable` for anything but retryable unavailability, and
  `Status::internal(e.to_string())` or `{e:?}` sent to clients.
- Flag error responses or client-visible messages that reveal whether a protected resource exists.

**Sources.** y-scope/spider#353, y-scope/spider#354, y-scope/spider#358, y-scope/spider#359,
y-scope/spider#364, y-scope/spider#369, y-scope/spider#464, spider
components/spider-storage/src/grpc.rs, spider
components/spider-execution-manager/src/client/grpc/storage.rs, spider
components/spider-execution-manager/src/client/grpc/liveness.rs. See also: ERR-6 (translating errors
in one exhaustive place).

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
for ServerError::BadRequest` would report a corrupted row as a client mistake, so y-scope/spider#351
maps it to `CorruptedDbState` on recovery and to `BadRequest` on submission. Formatting in SQL
(`DATE_FORMAT`, `ROUND`, `FROM_UNIXTIME(? / 1000.0)`) splits the type contract across two languages
and makes clients re-parse values, and in y-scope/clp#2197 a vendor-specific aggregate (`ANY_VALUE`)
failed on MariaDB.

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

**Sources.** y-scope/spider#339, y-scope/spider#351, y-scope/spider#353, y-scope/spider#285, spider
components/spider-storage/src/db/mariadb/job.rs, spider
components/spider-storage/src/db/mariadb/scheduler.rs, y-scope/clp#2197, y-scope/clp#2420,
y-scope/clp#2513, y-scope/clp#2058.

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

**Sources.** y-scope/clp#2578, y-scope/clp#2690, y-scope/clp#2564, RustTraining
c-cpp-book/src/ch18-cpp-rust-semantic-deep-dives.md. See also: OBJ-1 (private fields protect
invariants).

## MOD-2: Treat every contract change as breaking, and make the breakage loud rather than tolerated

**Rule.** Mark a PR breaking (`!`, with a migration note) when it changes any of these: the public
items of a crate consumed from another repository; a serialized format (DB schema or JSON/msgpack
column, task input, wire protocol, FFI entry points); or a user-visible config, including an added
or removed key, a renamed variant or a changed default. Before merging, list every producer and
consumer of the format, including non-Rust ones, and either update them or file tracked issues.
Readers of a format that has changed reject the old shape. They don't quietly accept it.

**Why.** The Rust compiler can't see a Python or WebUI producer. In y-scope/clp#2652, the typed
`QueryJobConfig` with `deny_unknown_fields` broke the MCP server, which still wrote the old flat
config, so its searches would fail on new deployments. The failure was loud, so it was found in
review and tracked (y-scope/clp#2656). A tolerant reader would have run an empty query in silence.
Users who never set a field still depend on its default. Raising a buffer threshold 16x can run
memory-constrained systems out of memory with no change to their config. A `pub` item that no other
repository consumes is not a contract, so changing it doesn't need `!`.

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
  compile error that would have forced each consumer to handle the new state (DEF-1).

**Exceptions.** The RustTraining books recommend `#[non_exhaustive]` for public enums. That advice
fits a crate published for third parties that mirrors a vocabulary outside our control and expected
to grow, such as an external API's status codes.

**Sources.** y-scope/clp#2652, y-scope/clp#2656, y-scope/clp#2564, y-scope/clp#2620,
y-scope/clp#1965, y-scope/clp#1962, y-scope/spider#464, y-scope/spider#418, y-scope/spider#409,
RustTraining type-driven-correctness-book/src/ch11-fourteen-tricks-from-the-trenches.md,
RustTraining rust-patterns-book/src/ch15-crate-architecture-and-api-design.md. See also:
pr-review.md § PR Title Convention, Common Review Checks #10, BND-2 (strict schemas) and BND-6
(defaults).

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
y-scope/clp#2532, one Dockerfile kept an older Spider worker image that ignored the resource-group
env vars, so dedicated workers registered as general and nothing reported an error. A dependency
with an `unsafe` API hands its memory-safety obligations to our code. A deprecated but widely used
crate is still safer than a maintained alternative with a thousandth of the users.

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

**Sources.** y-scope/clp#2471, y-scope/clp#2532, y-scope/clp#2549, y-scope/clp#2375,
y-scope/clp#2312, y-scope/spider#285, y-scope/spider#289. See also: coding-style.md § Dependencies
(exact patch versions, sorted, no unused entries).

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
helper moved into a shared crate too early, like `scan_prefix` in y-scope/clp#2224, also loses the
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

**Sources.** y-scope/spider#333, y-scope/spider#340, y-scope/spider#347, y-scope/spider#355,
y-scope/spider#362, y-scope/clp#2224, y-scope/clp#2655, spider
components/spider-proto-rust/src/lib.rs, spider components/spider-utils/Cargo.toml. See also:
coding-style.md § Reusable code belongs in `clp-rust-utils`. That section says where shared code
goes, and this rule says when code counts as shared.

## MOD-5: Make `mod.rs` a table of contents: declarations and named re-exports only

**Rule.** A multi-file module's `mod.rs` (or parent file) only declares submodules and re-exports
items by name: `pub use` for the API and `pub(crate) use` for crate-internal entry points. A
submodule that only organises files stays private. Use `pub mod` only for a namespace that is itself
part of the API. Never write `pub use child::*`.

**Why.** A glob re-export publishes every `pub` item ever added to the child, so a new helper joins
the crate's API without showing up in any diff. Public file-organising submodules let siblings and
other crates reach into each other's internals. Before y-scope/clp#2713, `connection` and `cursor`
sat beside `session` at the crate root, so `session` and `connection` depended on each other's
internals through `pub(crate)` items. Named re-exports document the contract in one place, and they
let the files behind the module be rearranged without touching any caller.

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

**Sources.** y-scope/clp#2713, y-scope/spider#382, y-scope/spider#542, y-scope/spider#555, clp
components/clp-rust-libs/query-result-listener/src/session/mod.rs. See also: coding-style.md §
Module Organization.

## MOD-6: Give each shared type one owning crate and one import path

**Rule.** Define a shared type in exactly one crate, and have every consumer import it from there. A
crate that other crates depend on doesn't `pub use` another workspace crate's type unless its own
public signatures need it (MOD-7). For a domain-specific name, rename the type at the import (`use
spider_core::types::id::JobId as SpiderJobId;`). A crate-internal re-export under that name from the
module that owns the concept is fine.

**Why.** If a type can be imported from several paths, consumers drift onto whichever path they
found first. Moving the type then breaks all of them, and it is no longer clear which crate owns its
invariants. In y-scope/spider#469, the review removed `spider-storage`'s re-export of
`ExternalResourceGroupCredentials` once the type lived in `spider-core`. Otherwise callers would
have kept depending on the storage crate just to name a credentials type.

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

**Sources.** y-scope/spider#469, y-scope/clp#2087, clp
components/query-coordinator/src/coordination.rs. See also: coding-style.md § Type Aliases for
External Types, which applies the same one-owner principle to third-party types.

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

**Sources.** y-scope/spider#363, y-scope/spider#382, y-scope/spider#396, spider
components/spider-client/src/lib.rs (adapted to MOD-5), spider
components/spider-proto-rust/src/lib.rs

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

**Sources.** spider components/spider-core/src/types/id.rs, spider
components/spider-core/Cargo.toml, y-scope/clp#2649, y-scope/clp#2690, clp
components/clp-rust-libs/query-result-listener/Cargo.toml, clp components/api-server/Cargo.toml. See
also: coding-style.md § What deserves a unit test (no test-only seams), TEST-7 (enabling the feature
for a crate's own integration tests, and keeping mocks within the real contract).

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

**Sources.** y-scope/clp#2676, y-scope/clp#2690, y-scope/spider#444, y-scope/spider#449,
y-scope/spider#465

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

**Sources.** spider components/spider-tdl/Cargo.toml, spider taskfiles/lint.yaml, RustTraining
rust-patterns-book/src/ch15-crate-architecture-and-api-design.md, RustTraining
engineering-book/src/ch09-no-std-and-feature-verification.md

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
an internal error that shuts down the service, which is what happened in y-scope/spider#515. A
rejected call that consumed a queued item is a data-loss bug, and checking the variant alone does
not catch it. A test that stops reading at `Ended` will not notice a stream that keeps yielding
events or never closes. Consumers waiting for the end of that stream hang.

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

**Sources.** y-scope/spider#515 (fixed in y-scope/spider#525), y-scope/spider#471 (spider-scheduler
dispatch_queue.rs), spider components/spider-proto-rust/src/assignment.rs, spider
components/spider-core/src/types/io/mod.rs, y-scope/clp#2705. See also: coding-style.md §
Assertions, ERR-3 (if a test needs `to_string()`, a variant may be missing).

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
(y-scope/clp#2649).

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

**Sources.** y-scope/spider#541, y-scope/spider#555 (state/service/hooked_tests.rs),
y-scope/spider#341, y-scope/spider#527, y-scope/spider#526, y-scope/clp#2649. See also:
coding-style.md § Prefer real-time testing for complex async code.

## TEST-3: Test each decision exhaustively, in the module that defines it

**Rule.** Test a mapping or classification function (status to error, state to action) where it is
defined, with a table that has one row for every input variant. Do not test it only through an outer
layer whose output merges variants, through a mock that re-implements its `match`, or through unit
tests of a wrapper that only forwards to it.

**Why.** In y-scope/clp#2617, the `Cancellable` and `CancellationRequested` cases both became
HTTP 200. If `Pending` had mapped to the wrong variant, cancel would have done nothing, and every
HTTP-level test would still have passed. A mock that copies the production `match` only tests the
copy. A gRPC wrapper, or a service method that only forwards to its DB connector, has no logic of
its own. A mock-based unit test of it only checks that the mock behaves like a mock.

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

**Sources.** y-scope/clp#2617 (clp-rust-utils job_config/search.rs), y-scope/clp#2581,
y-scope/spider#364, y-scope/spider#358, y-scope/spider#347. See also: coding-style.md § What
deserves a unit test ("Test a behavior once, where it's defined"); pr-review.md § Flag tests that
don't test the code's own logic.

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

**Sources.** y-scope/spider#493 (spider-storage tests/mariadb_test.rs), spider
components/spider-scheduler/src/dispatch_queue.rs:285 (`run_pair_consistency_stress`), spider
components/spider-scheduler/src/core_impl/inbound_queue_reader.rs:488, spider
components/spider-core/src/session.rs:477, y-scope/spider#395.

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

**Sources.** y-scope/clp#2438 (review: "I prefer not to add this test case since it mutates the env
var"), clp components/clp-tdl-package/src/task/compression/compress.rs, y-scope/spider#397
(spider-storage src/config.rs), y-scope/spider#299, y-scope/spider#314, y-scope/spider#339,
RustTraining rust-patterns-book/src/ch14-testing-and-benchmarking-patterns.md.

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

**Sources.** spider components/spider-storage/src/task_instance_pool.rs:390, spider
components/spider-storage/src/state/job_cache_gc.rs:217, y-scope/spider#418
(executor_log_collection.rs `BrokenWriter`), y-scope/spider#527 (`wait_for_shutdown`), RustTraining
rust-patterns-book/src/ch14-testing-and-benchmarking-patterns.md. See also: coding-style.md § What
deserves a unit test ("Don't add test-only seams to production code").

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
fault type has no values (`enum InjectedFault {}`, see TLC-6), so every `?` on a hook compiles away.
Hooks live on each runtime instance, not in globals. A test target that cannot run at all without
such a feature may use `required-features`. Gating code behind a feature does not make a forbidden
seam acceptable (coding-style.md § What deserves a unit test).

**Sources.** spider components/spider-core/src/types/id.rs:42, spider
components/spider-core/Cargo.toml, clp components/clp-rust-libs/query-result-listener/Cargo.toml,
y-scope/clp#2696, y-scope/clp#2664, y-scope/clp#2690, y-scope/clp#2689, y-scope/spider#541
(test_hooks/disarmed.rs), y-scope/spider#493 (state/test_utils.rs), y-scope/spider#551,
y-scope/spider#557. See also: coding-style.md § Panic in test helpers when the failure means the
test is wrong.

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

**Sources.** y-scope/clp#2403 (compression-coordinator partition.rs), y-scope/clp#2649
(query-result-listener protocol.rs), y-scope/clp#2375, RustTraining
rust-patterns-book/src/ch14-testing-and-benchmarking-patterns.md, RustTraining
engineering-book/src/ch04-code-coverage-seeing-what-tests-miss.md. See also: DEF-9 (checked
decoding).

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

**Sources.** spider components/spider-scheduler/src/runtime.rs:148, spider
components/spider-storage/src/cache/tree/planner.rs:111, clp
components/clp-tdl-package/src/task/compression/mod.rs:83, y-scope/clp#2607 (log the full error, not
its kind), RustTraining async-book/src/ch12-common-pitfalls.md, RustTraining
c-cpp-book/src/ch17-4-logging-and-tracing-ecosystem.md. See also: coding-style.md § Log field
formatting, § Error messages, ERR-5 (where to log).

## TEST-10: Pin type-level guarantees with compile-fail tests

**Rule.** When correctness depends on some code *not* compiling, keep it that way with a
compile-fail test. Examples: a typestate method that does not exist in some state (TLC-10), a
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

**Sources.** spider components/spider-tdl/tests/test_task_macro.rs, spider
components/spider-tdl/src/register.rs:91 and :255, RustTraining
type-driven-correctness-book/src/ch14-testing-type-level-guarantees.md.

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
- **TYPE-10**: A `Vec<u8>` whose encoding lives only in a comment, a hand-built encoded buffer, or a
  secret crossing an API as `Vec<u8>`/`String`, held in a `derive(Debug)` struct, or compared with
  `==`; use an encoding newtype with `decode()`, `SecretSlice`, and `ConstantTimeEq`.

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
- **TLC-4**: A spend-once operation on a shared `&self` handle, or a `bool` parameter asserting a
  security or readiness fact.
- **TLC-5**: A public handle or async method that must be spawnable without a compile-time
  `Send`/`Sync` assertion (one per method for the futures).
- **TLC-5**: A native `async fn` in a trait whose futures are spawned, or
  `#[allow(async_fn_in_trait)]`.
- **TLC-6**: A trait generic parameter that each type implements only once (should be an associated
  type).
- **TLC-6**: A placeholder error type on an infallible impl, or `#[cfg]` repeated at every
  optional-hook call site, instead of `Infallible`/an empty enum.
- **TLC-7**: A struct field or `&self` factory for a stateless strategy; ask for a type-only trait
  and an empty enum.
- **TLC-8**: A trait used as `dyn` with a `Clone`/`Sized` supertrait, a by-value `self` method, or a
  generic method.
- **TLC-8**: `Box<dyn Any>` plus `downcast_ref` where an enum or a typed-trait/erased-trait bridge
  belongs.
- **TLC-9**: The same inherent method copied across crates where one extension trait with a blanket
  impl belongs.
- **TLC-9**: A blanket impl over a broad bound (`Debug`, `Display`, `Serialize`) for behavior some
  types must override.
- **TLC-9**: A mock made `Clone` only to satisfy `Trait + Clone` where a forwarding `Arc<T: ?Sized>`
  impl belongs (OWN-6).
- **TLC-10**: A runtime state guard repeated in three or more methods of a compile-time-ordered
  protocol.
- **TLC-10**: A typestate wrapper with `Option` fields plus `expect`, or a transition taking
  `&mut self`; and no typestate asked for two-phase or runtime-loaded state.

## Checklist: Defensive programming

- **DEF-1**: `_ =>` or an unused `other =>` arm in a match over a workspace enum, or a
  `matches!`/`is_*()` classification a new variant should have updated.
- **DEF-1**: `#[non_exhaustive]` on an enum other workspace crates match on, or a field-by-field
  struct conversion without a full destructure.
- **DEF-2**: A `?` on a request-dependent check after the first mutation, or a config value reaching
  a panicking constructor (`mpsc::channel(0)`, `Semaphore::new`) after a durable write.
- **DEF-2**: An unavoidable partial mutation (DB then cache) with no armed drop guard that fails the
  service if dropped.
- **DEF-3**: `contains_key`/`get` then `insert`, `load` then `store`, or a status read and write in
  separate locks/statements instead of `entry()`, one CAS or `SELECT ... FOR UPDATE`.
- **DEF-3**: An `UPDATE ... SET status` without a from-state guard, an ignored `rows_affected`, or a
  cursor/epoch assigned from an `Option` fetch or a raw `set`.
- **DEF-4**: `unwrap_or(<literal>)`, `unwrap_or_default()` or `_ => <valid variant>` when parsing
  external data, or a request option silently ignored or downgraded.
- **DEF-4**: User payload quoted/wrapped to make it parse, or a request string joined into a path
  without `Component::Normal`/containment checks.
- **DEF-5**: A request- or config-sized duration, count, allocation, decompression or drain with no
  `MAX_` cap at the boundary, or a limit enforced on only some output paths.
- **DEF-5**: A raised limit whose dependent limits are not rechecked and pinned with
  `const _: () = assert!(..)`, or a `clamp` whose computed lower bound can exceed the upper.
- **DEF-6**: `expect`/`assert!`/`unreachable!` on a condition input, a peer, the clock, randomness
  or a race can break.
- **DEF-6**: `expect`/`panic!` in a spawned service loop on shared state another component
  maintains, instead of cancelling the root token or returning an `Internal` error.
- **DEF-6**: A comment stating an assumption about a constant or limit relation that should be a
  const assert.
- **DEF-7**: A retry loop without a classifier, budget, capped backoff and jitter, or an error arm
  that `continue`s without sleeping.
- **DEF-7**: A non-idempotent create/register/enqueue under retry without an idempotency key or
  deterministic ID, or random output names for retriable tasks.
- **DEF-7**: A permanent error retried on every poll tick, or `let _ = op().await` used to make a
  replay idempotent instead of matching the one already-done variant.
- **DEF-8**: Unchecked `+`/`-`/`*`/`<<`/`fetch_sub` on input-derived values or meaningful counters
  (lossy `as` casts are TYPE-8).
- **DEF-8**: `Instant + Duration` with a caller-controlled duration, or a test gated on
  `debug_assertions`/`should_panic(expected = "overflow")`.
- **DEF-9**: `[]` indexing, range slicing or `as usize` on an input-derived offset/length, or a
  manual `pos + len > len` check before a slice.
- **DEF-9**: `with_capacity`/`reserve`/`vec![_; n]` sized by an input-declared count without capping
  to remaining bytes.
- **DEF-10**: An `unsafe` block without a `// SAFETY:` invariant, or a `# Safety` section on a safe
  `fn`.
- **DEF-10**: An `extern "C"` export (including macro-generated) without `catch_unwind`, or an owned
  FFI buffer without `Drop`.

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
  instead of a sync fn returning `impl Future + Send + use<>`; public spawnable futures lacking
  per-method compile-time `Send` assertions (TLC-5).

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
- **BND-8**: A password/secret/token held as `String`/`Vec<u8>` on a `Debug`/`Serialize` type, a
  credential compared with `==`, or a credential field serialized.
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
