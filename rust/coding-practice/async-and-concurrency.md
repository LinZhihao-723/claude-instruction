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

## Checklist

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
