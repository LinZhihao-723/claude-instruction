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

## Checklist

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
