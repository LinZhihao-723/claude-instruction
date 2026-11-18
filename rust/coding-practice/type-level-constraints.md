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

## Checklist

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
