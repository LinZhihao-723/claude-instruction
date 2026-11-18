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
mistake got a different status code and message (raised in review of
[y-scope/clp#2567](https://github.com/y-scope/clp/pull/2567#discussion_r4277862603), fixed in
[y-scope/clp#2581](https://github.com/y-scope/clp/pull/2581)). With `try_from`, the deserialized
value is valid by construction, the error names the offending value and its position, and there is
only one validation code path.

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

**Sources.**

- [y-scope/clp#2567](https://github.com/y-scope/clp/pull/2567#discussion_r4277862603): reviewer notes the two fields are validated at different stages
- [y-scope/clp#2572](https://github.com/y-scope/clp/issues/2572): asks for one status code and error format for invalid values
- [y-scope/clp#2581](https://github.com/y-scope/clp/pull/2581): rejects invalid bucket sizes with the same 422 as `max_num_results`
- [y-scope/clp#2484](https://github.com/y-scope/clp/pull/2484#discussion_r3818189641): reviewer: an unvalidated bucket size gets a 200, then the job fails
- [clp `clp-rust-libs/clp-rust-utils/src/job_config/search.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/clp-rust-utils/src/job_config/search.rs#L55-L115): `TimeRange` deserialized through `try_from = "UncheckedTimeRange"`
- [clp `clp-rust-libs/clp-rust-utils/src/types.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/clp-rust-utils/src/types.rs#L140-L183): `PositiveI64` with `try_from = "NonZeroU64"` and `into = "i64"`
- [spider `spider-core/src/task/task_graph.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/task/task_graph.rs#L956-L1063): `TaskGraphVisitor` replays the checked `TaskGraph::new` and `insert_task`
- [y-scope/spider#320](https://github.com/y-scope/spider/pull/320#discussion_r3211197530): reviewer: name the checking constructor `create`, not `validate`
- [RustTraining type-driven-correctness-book § Parse, Don't Validate](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch07-validated-boundaries-parse-dont-validate.html#parse-dont-validate): parse once into a type that carries validity
- [RustTraining type-driven-correctness-book § The Untyped Redfish Client](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch17-redfish-applied-walkthrough.html#the-untyped-redfish-client): indexing `serde_json::Value` with `unwrap()` at every use

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
and rejects the nested-map form, and Helm values cannot express YAML tags
([y-scope/spider#412](https://github.com/y-scope/spider/pull/412)).

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

**Sources.**

- [spider `spider-scheduler/src/config.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/config.rs#L36-L50): `SchedulerConfig` adjacently tagged with `deny_unknown_fields`
- [spider `spider-scheduler/src/runtime.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-scheduler/src/runtime.rs#L24-L40): `RuntimeConfig` has `#[serde(default)]` fields but no `deny_unknown_fields`
- [spider `spider-storage/src/config.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/config.rs#L74-L80): `DatabasePoolConfig` pairs struct-level `default` with `deny_unknown_fields`
- [spider `spider-storage/src/state/runtime.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/state/runtime.rs#L32-L40): `RuntimeConfig` has defaulted sections but no `deny_unknown_fields`
- [y-scope/spider#412](https://github.com/y-scope/spider/pull/412): externally tagged enum needs YAML tags; switches to adjacent tagging
- [y-scope/spider#433](https://github.com/y-scope/spider/pull/433): renaming config keys breaks old configs; Helm values updated in lockstep
- [y-scope/clp#1663](https://github.com/y-scope/clp/pull/1663#discussion_r2562757119): reviewer adds `deny_unknown_fields` to the API's `QueryConfig`
- [y-scope/clp#1828](https://github.com/y-scope/clp/pull/1828#issuecomment-3720487052): schema change without a Helm update fails deployments with "missing field"
- [y-scope/clp#2452](https://github.com/y-scope/clp/pull/2452#discussion_r3725303501): reviewer: the Rust mirror of the changed Python config wasn't updated
- [y-scope/clp#2613](https://github.com/y-scope/clp/pull/2613#discussion_r4383980759): reviewer adds `deny_unknown_fields` to a new job-config struct
- [y-scope/clp#2652](https://github.com/y-scope/clp/pull/2652): `QueryOutput` tagged by `type`; every config struct denies unknown fields
- [RustTraining rust-patterns-book § Enum Representations](https://microsoft.github.io/RustTraining/rust-patterns-book/ch11-serialization-zero-copy-and-binary-data.html#enum-representations): the four serde enum representations and when to use each

## BND-3: Guard read-then-write DB transitions in the statement itself

**Rule.** Write a state transition as one `UPDATE ... WHERE id = ? AND <every precondition>` and
check `rows_affected()`. The preconditions are the valid previous states and, where writers can be
superseded, the writer's session or fence. If a transaction must read a value before deciding what
to write, read it with `SELECT ... FOR UPDATE` (or `LOCK IN SHARE MODE` when nothing in the
transaction later writes that row). Failure paths are no exception: marking a job failed also names
the states it may move from. Each storage method is one transaction, and a failed call leaves no
side effects.

**Why.** In InnoDB and MariaDB, a plain `SELECT` inside a transaction reads a snapshot and takes no
lock. The team once assumed otherwise, and the resulting inconsistent status check needed a
dedicated fix ([y-scope/clp#2045](https://github.com/y-scope/clp/pull/2045)). Read, check in Rust,
then write is a TOCTOU race, and upgrading a shared lock to an exclusive one deadlocks under
concurrency, which is why spider's transitions bind both the expected and the target state
([y-scope/spider#283](https://github.com/y-scope/spider/pull/283#discussion_r2921926472)). An
ownership check done only in memory let a superseded storage process keep committing transitions
after its replacement took over, so jobs ran twice; the fix fences every write in SQL (issue
[y-scope/spider#520](https://github.com/y-scope/spider/issues/520), fixed in
[y-scope/spider#532](https://github.com/y-scope/spider/pull/532)). In clp, marking a query job failed
"regardless of its current status" could overwrite a terminal `Cancelled` set by the API server
([y-scope/clp#2513](https://github.com/y-scope/clp/pull/2513#discussion_r4077243068)).

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
- Treat a `rows_affected()` mismatch as a corruption error such as `CorruptedDbState`, not a silent
  skip. A second "confirmation" `SELECT` that could only disagree if the DB were corrupt adds round
  trips and locks without adding safety.
- Flag a storage method split into several transactions without a measured reason and a docstring
  stating what a partial failure leaves behind.
- Flag `ON UPDATE CURRENT_TIMESTAMP` on columns with a meaning (`end_at`, `death_confirmed_at`);
  write them explicitly in the transition. Flag vendor-only SQL such as `INSERT ... RETURNING` in
  crates that support both MariaDB and MySQL; use `last_insert_id()`.

**Exceptions.** Large `IN` lists may be batched in bounded transactions; the method's docstring then
says it is not atomic.

See also: coding-style.md § SQL and Database Patterns, DEF-2 (the same race in memory).

**Sources.**

- [y-scope/clp#2045](https://github.com/y-scope/clp/pull/2045): a plain read takes a snapshot, not a lock; adds `LOCK IN SHARE MODE`
- [y-scope/clp#2038](https://github.com/y-scope/clp/pull/2038#discussion_r2856964175): reviewer assumes the unlocked status read already holds an `S` lock
- [y-scope/spider#283](https://github.com/y-scope/spider/pull/283#discussion_r2921926472): pass expected and target states for one conditional update, avoiding lock-promotion deadlocks
- [y-scope/spider#292](https://github.com/y-scope/spider/pull/292#discussion_r3041909365): reviewer objects to splitting a method into non-atomic transactions
- [y-scope/spider#314](https://github.com/y-scope/spider/pull/314#discussion_r3149589314): reviewer: name it `death_confirmed_at`, without `ON UPDATE CURRENT_TIMESTAMP`
- [y-scope/spider#450](https://github.com/y-scope/spider/pull/450): replaces MariaDB-only `RETURNING id` with `last_insert_id()` for MySQL
- [y-scope/spider#493](https://github.com/y-scope/spider/pull/493#discussion_r4090973454): select-then-insert races, and deadlocks on gap locks
- [y-scope/spider#520](https://github.com/y-scope/spider/issues/520): an in-memory-only session check lets a superseded process keep committing
- [y-scope/spider#532](https://github.com/y-scope/spider/pull/532): fences every database write with the storage session
- [y-scope/spider#540](https://github.com/y-scope/spider/pull/540): multi-job updates in one fenced, state-guarded statement or transaction
- [y-scope/spider#557](https://github.com/y-scope/spider/pull/557): commits up to 256 planned events in one fenced transaction
- [y-scope/clp#2513](https://github.com/y-scope/clp/pull/2513#discussion_r4077243068): the precondition must be checked even when marking a job failed
- [y-scope/clp#2513](https://github.com/y-scope/clp/pull/2513#pullrequestreview-5286744460): `from: None` overwrote terminal statuses; a locked read reports which failure applied
- [y-scope/clp#2617](https://github.com/y-scope/clp/pull/2617): `request_cancellation` reads and updates the status in one transaction
- [y-scope/spider#373](https://github.com/y-scope/spider/pull/373#discussion_r3539743682): a confirmation `SELECT` is meaningless; check the affected-row count instead
- [spider `spider-storage/src/db/mariadb/tree_transition.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/db/mariadb/tree_transition.rs#L366-L378): `UpdateStatement::ensure_every_row_matched` turns a guarded-update mismatch into `CorruptedDbState`

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
fields in different orders without a compiler error;
[y-scope/spider#471](https://github.com/y-scope/spider/pull/471) turned such a tuple into
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
  it yet; that backend returns a typed `Unsupported` error itself
  ([y-scope/spider#471](https://github.com/y-scope/spider/pull/471)).

**Exceptions.** A domain-to-wire conversion that cannot fail on any supported target may use
`expect("...")` stating why.

See also: coding-style.md § API design (named fields over positional tuples), coding-style.md § What
deserves a unit test.

**Sources.**

- [spider `spider-proto-rust/src/unpack/mod.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-proto-rust/src/unpack/mod.rs#L31-L48): `RequestUnpack`, the one fallible proto-to-native conversion layer
- [spider `spider-proto-rust/src/unpack/storage.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-proto-rust/src/unpack/storage.rs#L84-L113): `ReportTaskSuccessRequest` still unpacks into a five-value tuple
- [spider `spider-proto-rust/src/unpack/scheduler.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-proto-rust/src/unpack/scheduler.rs#L16-L44): `NextTaskRequestPayload`, a named-field struct instead of a tuple
- [spider `spider-proto-rust/src/job.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-proto-rust/src/job.rs#L23-L39): `TryFrom` maps `JobState::Unspecified` to a named error
- [spider `spider-execution-manager/src/client/storage.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/client/storage.rs#L78-L109): `report_task_success` requires `None` outputs for commit and cleanup tasks
- [spider `spider-execution-manager/src/client/grpc/storage.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/client/grpc/storage.rs#L91-L114): `serialized_outputs.unwrap_or_default()` erases `None` versus empty
- [y-scope/spider#353](https://github.com/y-scope/spider/pull/353): introduces `RequestUnpack` to convert proto requests into native types
- [y-scope/spider#354](https://github.com/y-scope/spider/pull/354): typed `ExecutionContext` via `TryFrom`, failing on missing nested messages
- [y-scope/spider#471](https://github.com/y-scope/spider/pull/471): unpacking yields `NextTaskRequestPayload`; the core, not the protocol, refuses groups

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
schemas that drift apart
([y-scope/clp#2532](https://github.com/y-scope/clp/pull/2532#discussion_r4106135253)).

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
  every sub-config
  ([y-scope/spider#346](https://github.com/y-scope/spider/pull/346#pullrequestreview-4546792735)).
- If an env key is optional by default but the operator listed it explicitly, log a warning when it
  is missing
  ([y-scope/spider#389](https://github.com/y-scope/spider/pull/389#discussion_r3573945411)).

See also: TEST-5 (testing env-dependent code without mutating the environment).

**Sources.**

- [spider `spider-execution-manager/src/config.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/config.rs#L38-L73): `runtime_config` turns any credential error into a warning and `None`
- [spider `spider-core/src/types/resource_group.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/types/resource_group.rs#L36-L60): `from_env` reports every `VarError` as `MissingEnvVar`
- [spider `spider-storage/src/config.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/config.rs#L82-L140): `DatabaseCredentials` resolves config, else env, via `try_from = "Option<RawCredentials>"`
- [spider `spider-execution-manager/src/client/scheduler.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/client/scheduler.rs#L31-L64): `next_task` without a resource group takes tasks from any group
- [y-scope/spider#341](https://github.com/y-scope/spider/pull/341#pullrequestreview-4493746031): reviewer: `create_runtime` takes the GC config, grouped into `RuntimeConfig`
- [y-scope/spider#346](https://github.com/y-scope/spider/pull/346#pullrequestreview-4546792735): reviewer: a serde `RuntimeConfig` instead of rebuilding config from CLI flags
- [y-scope/spider#379](https://github.com/y-scope/spider/pull/379): test driver's lazy singleton reads `SPIDER_CONCURRENCY`, defaulting to 8
- [y-scope/spider#389](https://github.com/y-scope/spider/pull/389#discussion_r3573945411): warn when an explicitly listed env key is unset
- [y-scope/spider#397](https://github.com/y-scope/spider/pull/397#pullrequestreview-4698875645): serde resolves optional config credentials, else env vars
- [y-scope/clp#2532](https://github.com/y-scope/clp/pull/2532#discussion_r4106135253): use Spider's own credential env-var names, as with AWS
- [y-scope/clp#2549](https://github.com/y-scope/clp/pull/2549#discussion_r4170140547): load credentials with `from_env()?` and propagate the error

## BND-6: Make every default an intended value, owned in one place

**Rule.** Use field-level `#[serde(default)]` only when `Default::default()` is the value you
actually want; otherwise use `default = "fn"` returning a validated type, or make the field
required. For a section whose fields all have defaults, put `#[serde(default)]` on the struct and
write one `impl Default`. When a downstream component owns the default, make the field `Option<T>`
and pass `None` through instead of copying its literal.

**Why.** `#[serde(default)] max_connections: usize` yields 0 when the key is missing: a pool that
hands out no connections, with no error. Without a struct-level default, `{"buffer_config":
{"timeout_sec": 100}}` is rejected with "missing field", because a nested object that is present
must list every field
([y-scope/clp#2150](https://github.com/y-scope/clp/pull/2150#discussion_r3015802782)). A copied
default drifts: Celery and clp-s each hard-coded a result limit of 1000, so changing one silently
made them disagree
([y-scope/clp#2503](https://github.com/y-scope/clp/pull/2503#discussion_r3900175343)).

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
  absent or null; a required collection is an empty `Vec`, not `None`
  ([y-scope/clp#2087](https://github.com/y-scope/clp/pull/2087#discussion_r2965812887)).

See also: coding-style.md § Mirroring Python Types (defaults kept in sync), MOD-2 (a changed default
is a breaking change).

**Sources.**

- [y-scope/clp#2150](https://github.com/y-scope/clp/pull/2150#discussion_r3015802782): reviewer: a partial `buffer_config` is rejected without struct-level default
- [y-scope/clp#2503](https://github.com/y-scope/clp/pull/2503#discussion_r3900175343): reviewer: let clp-s own the result-limit default instead of copying 1000
- [y-scope/clp#2087](https://github.com/y-scope/clp/pull/2087#discussion_r2965812887): reviewer: the Python field isn't nullable, so don't make it optional
- [y-scope/clp#1729](https://github.com/y-scope/clp/pull/1729#discussion_r2594209669): reviewer asks for struct-level `#[serde(default)]` on `ArchiveOutput`
- [spider `spider-execution-manager/src/config.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/config.rs#L88-L122): `max_log_line_bytes` defaults through a fn returning `NonZeroUsize`
- [spider `spider-storage/src/config.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/config.rs#L69-L80): defaulted `pool` section with struct-level `#[serde(default)]` and `Default`
- [RustTraining rust-patterns-book § Common serde Attributes](https://microsoft.github.io/RustTraining/rust-patterns-book/ch11-serialization-zero-copy-and-binary-data.html#common-serde-attributes): `default`, `default = "fn"` and `deny_unknown_fields`

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
end of stream ([tokio-rs/tokio#3976](https://github.com/tokio-rs/tokio/issues/3976),
[y-scope/spider#418](https://github.com/y-scope/spider/pull/418)). Real log data contains invalid
UTF-8: strict decoding turned one bad line into a failed query, and `String::from_utf8_lossy` alone
was 2-4x slower on valid ASCII than trying `str::from_utf8` first
([y-scope/clp#2649](https://github.com/y-scope/clp/pull/2649#discussion_r4449178317)).

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

See also: SRV-3 (caps on what a peer can size) and DEF-4 (checked slicing of decoded buffers).

**Sources.**

- [y-scope/spider#418](https://github.com/y-scope/spider/pull/418): capped `LinesCodec`, oversized lines dropped, `FramedRead`'s post-error `None` handled
- [spider `spider-execution-manager/src/process_pool.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/process_pool.rs#L436-L489): `forward_executor_logs` drops an oversized line with a `warn` and resumes
- [y-scope/clp#2649](https://github.com/y-scope/clp/pull/2649#discussion_r4438307065): reviewer: non-UTF-8 clp-s output fails strict decoding; decode lossily
- [y-scope/clp#2649](https://github.com/y-scope/clp/pull/2649#discussion_r4449178317): reviewer: try `str::from_utf8` first; lossy alone is 2-4x slower
- [clp `clp-rust-libs/query-result-listener/src/protocol.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/query-result-listener/src/protocol.rs#L284-L318): `read_str` caps the length, borrows valid UTF-8, else decodes lossily
- [clp `clp-tdl-package/src/task/query/search.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-tdl-package/src/task/query/search.rs#L534-L601): `run_clp_s_search` uses `Command::new(..).args(..)` and logs stderr on failure
- [tokio-rs/tokio#3976](https://github.com/tokio-rs/tokio/issues/3976): `Framed` keeps reading after a decode error instead of terminating

## BND-8: Keep secrets typed, unserialized, out of logs, and compared in constant time

**Rule.** Hold passwords and tokens as `secrecy::SecretString` or `SecretSlice<u8>`, and call
`expose_secret()` only where the value is used. Mark credential fields `#[serde(skip_serializing)]`
on any type that derives `Serialize`. Compare a supplied credential with the stored one using
`subtle::ConstantTimeEq`. Keep the wrapper on every internal API that carries the secret, down to
the call that sends or compares it. Don't log an access-granting value (a session token, a presigned
URL) on the success path.

**Why.** A plain `String` password leaks through `#[derive(Debug)]` into logs and panic messages,
and through re-serializing the config; `SecretString`'s `Debug` prints `[REDACTED]`. `==` on byte
strings may stop at the first differing byte, which leaks timing information. A valid session token
logged on every accepted connection lets anyone who can read the logs join that session
([y-scope/clp#2689](https://github.com/y-scope/clp/pull/2689)). A rejected, unknown token grants
nothing, so it may be logged. A wrapper protects only as far as it reaches: Spider's
`ExternalResourceGroupCredentials` keeps its password in a `SecretSlice`, so `Debug` redacts it, but
`Client::verify_resource_group` takes the password as a bare `Vec<u8>`. From that call on, a single
`?password` in a log line prints it.

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
- Flag a secret that crosses a function boundary as a `Vec<u8>` or `String`, even between internal
  layers.
- Flag `tracing` fields that carry tokens or credentials on accept or success paths; log the peer
  address or task index instead.
- Flag `expose_secret()` results stored in a variable or struct that outlives the call that needs
  the value.

**Exceptions.** A wrapper has to prevent a real misuse.
[y-scope/clp#1704](https://github.com/y-scope/clp/pull/1704#discussion_r2590945683) dropped
`SecretString` from the AWS secret-key path, where the keys already arrive through environment
variables and the wrapper only added conversions. When a reviewer asks what a wrapper prevents, the
answer must be concrete.

**Sources.**

- [spider `spider-storage/src/config.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/config.rs#L32-L88): `credentials` is `skip_serializing`, its password a `SecretString`
- [spider `spider-storage/src/db/mariadb/resource_group.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/db/mariadb/resource_group.rs#L100-L123): `verify` compares the stored password with `ct_eq`
- [spider `spider-core/src/types/resource_group.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/types/resource_group.rs#L12-L20): the resource group password held as `SecretSlice<u8>`
- [y-scope/spider#397](https://github.com/y-scope/spider/pull/397): database credentials from env vars instead of plaintext config
- [y-scope/spider#469](https://github.com/y-scope/spider/pull/469#issuecomment-5527563360): maintainer agrees to make the password a `secrecy` secret
- [y-scope/spider#493](https://github.com/y-scope/spider/pull/493#discussion_r4100744256): reviewer's rewrite checks the stored password with `ct_eq`
- [y-scope/clp#2689](https://github.com/y-scope/clp/pull/2689): listener logs omit valid session tokens; only unknown tokens are named
- [spider `spider-client/src/client.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-client/src/client.rs#L217-L240): `verify_resource_group` takes the password as a bare `Vec<u8>`
- [y-scope/spider#292](https://github.com/y-scope/spider/pull/292#discussion_r3041915941): the password check uses `subtle::ConstantTimeEq`
- [y-scope/clp#1704](https://github.com/y-scope/clp/pull/1704#discussion_r2590945683): reviewer: `SecretString` only adds hassle on the AWS key path

## BND-9: Treat wire status codes as a contract, and keep client-facing errors coarse

**Rule.** Give each status code one meaning across the whole system, decode statuses into the
client's domain error in a single `status_to_error` function, and change the server mapping and the
client decoder in the same PR. Reserve `UNAVAILABLE` for "retry later, the request itself was fine"
(a lost connection, a server shutting down), never for an application error. Answer "not found" and
"wrong credential" for a protected resource with the same `UNAUTHENTICATED`, and answer internal
failures with a fixed `INTERNAL` message while logging the detail on the server.

**Why.** Storage used to return `UNAVAILABLE` for a stale session and for a fatal cache error, so
the execution manager couldn't tell "reconnect" from "your request is wrong". When
[y-scope/spider#358](https://github.com/y-scope/spider/pull/358) moved stale sessions to
`NOT_FOUND`, the client's catch-all `_ => Server(..)` arm would have silently absorbed the new code
and broken stale-session recovery had the decoder not changed in the same PR. Separate not-found and
bad-password replies let a caller enumerate resource groups, and internal error strings expose SQL,
schema, or cache state.

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
conservative `Server` error.

**Review.**
- Flag RPC methods that inspect `status.code()` themselves, and any server-side change to a status
  code without the matching change to the client decoder. Ask for one decoder test per mapped code
  (TEST-3).
- Flag `Status::unavailable` for anything but retryable unavailability, and
  `Status::internal(e.to_string())` or `{e:?}` sent to clients.
- Flag error responses or client-visible messages that reveal whether a protected resource exists.

See also: ERR-6 (translating errors in one exhaustive place).

**Sources.**

- [y-scope/spider#353](https://github.com/y-scope/spider/pull/353): `UNAUTHENTICATED` for unknown group or bad password; opaque `INTERNAL` otherwise
- [y-scope/spider#354](https://github.com/y-scope/spider/pull/354): adds the client's `status_to_error`; stale sessions were still `UNAVAILABLE`
- [y-scope/spider#358](https://github.com/y-scope/spider/pull/358): reserves `UNAVAILABLE` for transport errors and updates the client decoder
- [y-scope/spider#359](https://github.com/y-scope/spider/pull/359#discussion_r3488354927): reviewer: the client handler ignores `UNAVAILABLE`'s reserved meaning
- [y-scope/spider#364](https://github.com/y-scope/spider/pull/364#discussion_r3525523065): reviewer: per-service handlers, everything else through one default handler
- [y-scope/spider#369](https://github.com/y-scope/spider/pull/369#discussion_r3525908337): reviewer: the client-side status handling belongs in the same PR
- [y-scope/spider#464](https://github.com/y-scope/spider/pull/464): one `UNAUTHENTICATED` for a wrong resource group ID or password
- [spider `spider-storage/src/grpc.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/grpc.rs#L162-L230): task-instance error handler: `NOT_FOUND` for stale sessions, rest to the default
- [spider `spider-execution-manager/src/client/grpc/storage.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/client/grpc/storage.rs#L142-L161): `status_to_error` decodes each code, falling back to `Server`
- [spider `spider-execution-manager/src/client/grpc/liveness.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-execution-manager/src/client/grpc/liveness.rs#L96-L113): liveness `status_to_error`; its fallback is `Transport`, not `Server`

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
for ServerError::BadRequest` would report a corrupted row as a client mistake, so
[y-scope/spider#351](https://github.com/y-scope/spider/pull/351#discussion_r3470399072) maps it to
`CorruptedDbState` on recovery and to `BadRequest` on submission. Formatting in SQL (`DATE_FORMAT`,
`ROUND`, `FROM_UNIXTIME(? / 1000.0)`) splits the type contract across two languages and makes
clients re-parse values, and in
[y-scope/clp#2197](https://github.com/y-scope/clp/pull/2197#discussion_r3069536389) a
vendor-specific aggregate (`ANY_VALUE`) failed on MariaDB.

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

**Sources.**

- [y-scope/spider#339](https://github.com/y-scope/spider/pull/339#pullrequestreview-4471850284): reviewer adds `RecoverableJobRowProjection` to make the query readable
- [y-scope/spider#351](https://github.com/y-scope/spider/pull/351#discussion_r3470399072): reviewer: map `JobSubmissionError` to `CorruptedDbState` on recovery
- [y-scope/spider#351](https://github.com/y-scope/spider/pull/351#discussion_r3470408829): reviewer: forward the same error as `BadRequest` on submission
- [y-scope/spider#353](https://github.com/y-scope/spider/pull/353): a database-minted duplicate job ID is internal, not a client-facing error
- [y-scope/spider#285](https://github.com/y-scope/spider/pull/285#discussion_r2972593594): reviewer: no hard-coded `'Ready'`; derive the state enum's SQL mapping
- [spider `spider-storage/src/db/mariadb/job.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/db/mariadb/job.rs#L296-L342): `RecoverableJobRowProjection` re-runs `ValidatedJobSubmission::create` as `CorruptedDbState`
- [spider `spider-storage/src/db/mariadb/scheduler.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-storage/src/db/mariadb/scheduler.rs#L60-L90): `SchedulerRowProjection` re-validates the stored host as a `Host`
- [y-scope/clp#2197](https://github.com/y-scope/clp/pull/2197#discussion_r3068016843): reviewer: derive `sqlx::FromRow` instead of mapping with `try_get`
- [y-scope/clp#2197](https://github.com/y-scope/clp/pull/2197#discussion_r3069560459): reviewer: drop SQL `ROUND` and `FROM_UNIXTIME`; bind typed values
- [y-scope/clp#2420](https://github.com/y-scope/clp/pull/2420#discussion_r3654294879): reviewer: add a struct for the row projection
- [y-scope/clp#2513](https://github.com/y-scope/clp/pull/2513#discussion_r3963842747): reviewer: bind job status through `sqlx::Type`, not an enum-to-int cast
- [y-scope/clp#2058](https://github.com/y-scope/clp/pull/2058#discussion_r2877153900): reviewer: `i8` for a `TINYINT` column, as a named constant

## Checklist

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
- **BND-8**: A password/secret/token held as `String`/`Vec<u8>` on a `Debug`/`Serialize` type or
  passed across an API as `String`/`Vec<u8>`, a credential compared with `==`, or a credential field
  serialized.
- **BND-8**: A session token, presigned URL or credential logged on an accept/success path.
- **BND-9**: Status codes decoded outside a single `status_to_error`, a server status change without
  the matching client decoder change, or no per-code decoder test.
- **BND-9**: `Status::unavailable` for an application error, internal error detail sent to clients,
  or responses that distinguish not-found from wrong-credential.
- **BND-10**: A tuple `query_as` with 3+ columns, `row.try_get("col")`, `.bind(status as i32)`, or
  SQL-side formatting/rounding/vendor functions.
- **BND-10**: A DB row converted without re-running validating constructors, or a validation error
  mapped by a blanket `From` into a client error instead of `CorruptedDbState` at the read site.
