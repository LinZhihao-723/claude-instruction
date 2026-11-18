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

## Checklist

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
