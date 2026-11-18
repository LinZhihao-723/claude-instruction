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

## Checklist

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
