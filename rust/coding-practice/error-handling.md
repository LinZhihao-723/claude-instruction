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

## Checklist

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
