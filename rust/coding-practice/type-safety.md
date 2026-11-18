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

## Checklist

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
