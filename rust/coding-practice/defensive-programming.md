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

## Checklist

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
