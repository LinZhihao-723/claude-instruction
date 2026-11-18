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

## Checklist

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
