# Rust PR Review Skill

When reviewing Rust PRs in y-scope repositories (e.g., `y-scope/clp` for `api-server`, `log-ingestor`,
`clp-rust-utils` components, and `y-scope/spider` for `spider-core`, `spider-storage` components),
apply the following review guidelines. These are derived from historical review patterns and project
conventions.

Also refer to `coding-style.md` for coding style requirements. This skill focuses on PR-level
review patterns and conventions beyond the coding style.

## Review Discipline

Reviewers (including Claude) have repeatedly missed style violations that are clearly documented in
`coding-style.md`. Before concluding any review, walk the diff line-by-line and verify the points
in the "Common Review Checks" section below. Do not rely on the assumption that a high-level
architecture pass will surface naming, ordering, or docstring problems -- it won't.

If you find more than one or two violations of documented style rules, treat the PR as not yet
ready to approve. Request a self-audit pass from the author rather than absorbing a long polish
cycle into the review. Architecture-level design choices remain case-by-case judgment calls and
should be discussed in PR comments, not enforced as blanket rules.

## PR Title Convention

Suggest a PR title at the end of the review (typically at approval time) following this format:

```
<type>(<scope>): <Short description> (resolves #<issue>).
```

* The description should be concise but precise. End with a period.
* For breaking changes, add `!` after the scope: `feat(log-ingestor)!: ...`
* If the PR has multiple logical changes, use a multi-line title with bullet points:

```
feat(log-ingestor): Add ingestion job orchestration:

* Add `IngestionJobManager` for creating and deleting ingestion jobs.
* Add `CompressionJobSubmitter` for async compression-job submission.
```

## Code Organization

### Move reusable code to `clp-rust-utils`

If code in `api-server` or `log-ingestor` could be shared across components, suggest moving it to
`clp-rust-utils`. Examples include:

* MySQL pool creation utilities
* Config structs and deserialization
* AWS client creation helpers
* Common type definitions (e.g., job IDs, config types)

### Module structure

* Group related functionality into dedicated submodules (e.g., separate `routes` into submodules per
  API group).
* When a type is internal to a module, shorten its name (e.g., `SqsListenerTask` -> `Task` inside the
  module). Users reference it via the module path: `ingestion_job::SqsListener`.
* Public symbols should be listed before private symbols within each `impl` block.
* The `impl` block for a type must come **immediately after** the type definition, before any other
  type's `impl` blocks. Don't define `struct A`, then `impl SomeTrait for B`, then come back to
  `impl A`.

### Naming consistency on rename

When renaming a type, **rename every variable, field, parameter, message-variant field, and
closure binding** named after the old type. Example: renaming `TaskInstanceRecord` ->
`TaskInstanceMetadata` requires `record` -> `metadata` everywhere in the file (locals, struct
fields, function parameters, helpers like `make_record` -> `make_task_instance_metadata`). A
half-applied rename is worse than no rename.

When the team has agreed on a domain term (e.g., "execution manager" instead of "worker"), apply
the rename to the entire diff in this PR. "It would be a lot of edits" is not a valid reason to
defer -- a wide mechanical rename is exactly the kind of change Claude can do in one pass.

### Avoid weak identifiers

* Don't include the data-structure type in identifiers. Use `dead_workers`, not `dead_worker_set`.
  If you do mention "set", the underlying type must actually be a `HashSet` -- inconsistency
  between the name and the type is a defect.
* Avoid `Any_` prefix for type-erased enums; pick a concrete short name (e.g., `Tcb`) that conveys
  what the value represents.

### Generic type-parameter naming

In addition to the `Db` (not `DB`) rule from `coding-style.md`:

* Use the `XxxType` suffix to disambiguate type parameters from concrete types: `ReadyQueueSenderType`,
  `LivenessStoreType`, `DbConnectorType`, not `ReadyQueue`/`LivenessStore`/`Db`. Without the suffix,
  a reader can't tell at the call site whether `ReadyQueue` is a concrete type or a type parameter.
* When renaming a type parameter, rename **all** uses including the surrounding `impl<...>` line. A
  function and its enclosing `impl<>` must use the same names.

### Trait surface minimization

Don't expose methods on a connector or abstraction trait that the calling layer doesn't actually
invoke. Each trait method is a contract that all implementations must satisfy and all reviewers
must reason about. If only an internal helper or background coroutine needs a method, keep it on
the implementation type, not the trait.

Watch for trait methods that exist only to support tests or one internal helper -- those are signs
the abstraction is wrong.

### Enum dispatch vs dynamic dispatch

Prefer enum dispatch over trait objects (`Box<dyn Trait>`) when all variant types are known at compile
time:

* More compact memory layout.
* Enforces explicit handling for all variants.
* No virtual function overhead.
* Mirrors the C++ philosophy: prefer `std::variant` over inheritance.

Only use trait objects when the set of types is truly dynamic or unknown at compile time.

## Ownership and Efficiency

### Pass ownership instead of borrowing when the callee clones

If a function receives a reference but immediately clones or copies the data into a new structure,
restructure to pass ownership directly. Avoid unnecessary allocations:

```rust
// Bad: callee reconstructs a Vec from the slice
fn submit(ids: &[u64]) {
    let owned = ids.to_vec(); // unnecessary copy
    ...
}

// Good: pass ownership
fn submit(ids: Vec<u64>) {
    ...
}
```

### Conversely: don't take ownership when a reference suffices

If a helper only reads from its argument and the caller still needs the value, take `&T` instead of
`T`. Watch for unnecessary `T` parameters in helpers called from a loop where the caller's
iteration variable is reused.

### Prefer references over `Arc`/`Vec` when ownership isn't needed

For async trait methods that will not be run in detached coroutines, prefer `&T` and `&[T]` over
`Arc<T>` and `Vec<T>`:

```rust
// Good: borrows are sufficient when not detaching
async fn register(&self, task_graph: &TaskGraph, job_inputs: &[TaskInput]) -> Result<JobId, DbError>;

// Bad: unnecessary ownership transfer
async fn register(&self, task_graph: Arc<TaskGraph>, job_inputs: Vec<TaskInput>) -> Result<JobId, DbError>;
```

### Use `&str` for read-only string access

When a function only needs to read a string value (e.g., checking prefixes, logging), accept `&str`
rather than `&String` or `&NonEmptyString`.

### Use `u64` explicitly for sizes

Prefer `u64` over `usize` for sizes that may exceed 32-bit range (e.g., S3 object sizes, accumulated
buffer sizes), since `usize` is platform-dependent and could be 4 bytes on 32-bit platforms.

## Type-Level Validation

### Use newtype wrappers for validated values

* Use `NonEmptyString` for config fields that must not be empty.
* Wrap validated configs in special types and pass them through the call chain, so downstream code
  can trust the invariants without re-validating.

### Mirror Python types explicitly

When Rust types mirror existing Python definitions:

* Document the Python source with a doc comment:
  ```rust
  /// Mirror of `job_orchestration.scheduler.constants.QueryJobStatus`. Must be kept in sync.
  ```
* Add a note if the type is partially defined:
  ```rust
  /// # NOTE
  ///
  /// * This type is partially defined: unused fields are omitted and discarded through
  ///   deserialization.
  /// * The default values must be kept in sync with the Python definition.
  ```

## Error Handling

### Panic vs error returns

* Only use `panic!`/`expect` for internal invariant violations -- conditions that indicate a bug in
  the implementation.
* For external failures (DB errors, overflow from external IDs, network issues), return errors and
  let the top-level caller decide how to handle them.

### `anyhow` vs custom errors

* Use `anyhow::Result` for high-level APIs where callers just log and exit, hiding error details.
* Use typed error enums for library-level code where callers may need to match on specific error
  variants.

### Don't silently swallow errors

If a fallible call returns `Err`, don't pattern-match-and-ignore it on the success path:

```rust
// Bad: error vanishes; caller has no chance to react.
let alive = match store.is_alive(id).await {
    Ok(alive) => alive,
    Err(_) => return true,
};

// Good: bubble up.
let alive = store.is_alive(id).await?;
```

The same applies to `let _ = fallible().await;` -- replace with `?` or an explicit handling
comment that justifies the discard.

### Prefix error context with lowercase, no trailing period

Use `context("cannot load config file ...")` with lowercase start, no period -- consistent with the
error message conventions in `coding-style.md`.

## Docstring Audit

Beyond the templates in `coding-style.md`, watch for these recurring defects:

### Visibility does not exempt a function from a docstring

**Both public and non-public** functions need docstrings following the `coding-style.md` template.
Private and `pub(crate)` helpers are not exempt. The only legitimate exemptions are:

1. The function is simple enough (e.g., a one-line getter or setter).
2. The function is a trait implementation whose trait declaration already documents it.
3. The item is a private *struct field* (data, not a function).

If a private helper needs a paragraph of inline reasoning, that paragraph belongs in a docstring,
not inside the function body.

### Short description is optional; `# Returns` is not

For short / simple functions, the one-line description **can** be dropped — but the `# Returns`
section must stay (per `coding-style.md`, `# Returns` may be omitted only when the function
returns `()` or `Result<()>`).

Valid (preferred for a trivial getter):

```rust
/// # Returns
///
/// The current session ID.
fn session_id(&self) -> u64;
```

Also valid (description and `# Returns`):

```rust
/// Returns the current session ID.
///
/// # Returns
///
/// The current session ID.
fn session_id(&self) -> u64;
```

**Not** preferred — drops the structured `# Returns` for a non-`()` return:

```rust
/// Returns the current session ID.
fn session_id(&self) -> u64;
```

When auditing, do **not** flag a docstring that has only `# Returns` (no description). Conversely,
do flag a one-line description that omits `# Returns` for a function returning a non-trivial
value.

### Boolean `Returns` wording

Use **"Whether ... on success."** rather than `true if ... false otherwise`:

```rust
// Good
/// # Returns
///
/// Whether the execution manager is alive on success.

// Bad
/// # Returns
///
/// `true` if the execution manager is alive, `false` otherwise, on success.
```

This matches the convention used by C++/Python docstrings in y-scope projects.

### `# Parameters` only in trait declarations

Don't add a `# Parameters` section to regular functions or trait implementations. Parameter names
and types in the signature are self-documenting. Trait *declarations* are the exception (the trait
contract documents the parameter semantics).

### `# Type Parameters` is required when type parameters exist

Any function with type parameters must have a `# Type Parameters` section listing each one. Easy to
forget after refactoring a function from `pub fn new(...)` to `pub fn create<T1, T2>(...)`.

### `Forwards [\`func\`]` must name the exact function

* The named function must be the actual call site reached via `?`, not a generic placeholder
  ("the relevant job-state guard errors", "sqlx errors").
* Don't use `Forwards [\`Error::Variant\`]` for errors this function constructs and returns
  directly. Use `* [\`Error::Variant\`] if <condition>.` for direct errors; reserve `Forwards` for
  errors propagated via `?`.
* When a function is refactored to delegate to helpers, rewrite `# Errors` to forward each helper
  (e.g., `Forwards [\`Self::create_regular_task_instance\`]'s return values on failure.`) instead
  of re-listing every leaf error.
* Watch for placeholder names left over from a refactor (e.g., `Self::run_gc_cycle_at_claude_version`
  when the function is `run_gc_cycle_at`). These are signs of incomplete cleanup.

### Stale docstring sections

When code is refactored, the corresponding `# Returns`, `# Errors`, and prose blocks must be
updated. Common stale patterns:

* `# Errors` listing errors from a code path that was deleted.
* Bullets referencing methods that were removed.
* Sentence fragments left from a partial edit (missing blank line before `# Errors`, unterminated
  bullet).

### Drop redundant in-test narration

Comments like `// First registration should succeed via the verify call.` immediately above a line
that does exactly that are noise -- the test name and assertion already say it. Keep comments only
when they explain *why* (e.g., a corner case the code is intentionally tolerating).

## Testing Conventions

### No `unwrap` in tests

Use `expect("descriptive message")` even in test code.

### Use `anyhow::Result` in test functions

```rust
#[tokio::test]
async fn test_something() -> anyhow::Result<()> {
    let result = do_something().await?;
    assert_eq!(result, expected);
    Ok(())
}
```

### Cover all basic behaviors of stand-alone components

For a new stand-alone component (pool, actor, scheduler, etc.), don't ship with tests that only
exercise the most prominent method. Identify the component's basic behaviors -- registration,
background-loop cycles, recovery paths, terminal cleanup -- and cover each one.

If you can't probe the internal state needed to assert these behaviors, that itself is a signal the
component needs a test-only accessor or a different architecture; raise it in review rather than
shipping with thin coverage.

### Don't sprawl into unrelated test infra

If the new component compiles into the same crate as existing tests (e.g.,
`tests/scheduling_infra.rs`), leave that infra alone unless it actually exercises the new
component. Adding a noop implementation of the new trait there just to satisfy the compiler is a
sign the new component shouldn't be a hard dependency of that path. Push back on PRs that
restructure unrelated test scaffolding.

### Prefer real-time testing for complex async code

Avoid `tokio::time::pause()` when behavior involves `select!` in long-running loops, as time
simulation only guarantees ordering for `sleep` calls and complicates reasoning about `select!`
behavior. Use real-time testing with appropriate timeouts instead.

### Use mock states for unit tests

Implement trivial noop/mock state structs for testing so that unit tests don't require external
services (e.g., databases). Trait-based state abstractions enable this.

## Review Workflow

### Review phases

1. **First pass**: Review for correctness, architecture, and design decisions.
2. **Style sweep**: Walk the diff with `coding-style.md` open. Flag every naming, ordering, and
   docstring issue at once -- not in a drip across multiple rounds.
3. **Changes requested**: List specific items to fix. Use GitHub suggestion blocks for small fixes.
4. **Follow-up reviews**: Verify requested changes are addressed.
5. **Approval**: Suggest a final PR title. Verify the PR can be merged.

### When the polish burden is too high

If addressing review feedback would take the reviewer more time than re-doing the change themselves,
that's a signal the PR was not ready for review. Reviewers in y-scope have explicitly flagged this
pattern: a PR should not require the reviewer to push commits like "Polish.", "Further polishing
X.", "Last few fixes." to land. When you (Claude) are the author, run a self-audit pass against
`coding-style.md` before requesting review.

### Requesting follow-up work

When identifying work that is out of scope for the current PR but should be tracked:

* Ask the author or `@coderabbitai` to create an issue.
* Clearly explain what needs to be done and why.

### Scope management

* Do not block a PR for work that is explicitly planned for a future PR.
* When a reviewer asks about something not yet implemented, it's acceptable to respond with
  "will address in a future PR" if there's a clear plan.
* However, flag any issues that could cause problems if left unaddressed (e.g., missing validation
  that could cause runtime failures).

## When to add/update docstrings/comments and when not to

For any code changes, it is important to check when to add/update docstrings/comments and when not
to. The following are some guidelines:
- If the code changes update the existing docstring/comments, you should update them. Examples:
  - Update a type name.
  - Update a function's implementation with larger big-O complexity which was documented in the
    docstring.
- If the code changes add a new feature, you **SHOULD NOT** add additional docstrings/comments to
  explain the specific behavior of the new feature, unless explicitly asked for. For example, the
  following code added some new features for env var passing. However, the comments are useless
  and they should be omitted unless explicitly asked for.
  ```rust
  // Always forward `RUST_LOG` so the executor's log verbosity matches ours. It is commonly
  // unset, so a missing value is silently ignored rather than warned about.
  if let Ok(rust_log) = std::env::var("RUST_LOG") {
      command.env("RUST_LOG", rust_log);
  }

  // Additionally forward the user-configured env keys. Unlike `RUST_LOG` these are explicitly
  // requested, so a value that is unset (or non-Unicode) is surfaced as a warning.
  for key in &self.config.env_keys {
      match std::env::var(key) {
          Ok(value) => {
              command.env(key, value);
          }
          Err(e) => {
              tracing::warn!(
                  executor_id,
                  env_key = % key,
                  err = % e,
                  "Configured env key could not be read from the execution manager's \
                   environment; skipping."
              );
          }
      }
  }
  ```

## Common Review Checks

1. **Cargo.toml**: Dependencies pinned to exact patch version? Alphabetically sorted? Unused
   dependencies removed?
2. **Docstrings**:
   * **Every function -- public AND non-public** -- documented per `coding-style.md` (unless one of
     the three explicit exemptions applies)?
   * `# Returns` present for any non-`()` / non-`Result<()>` return? (Short description may be
     omitted for trivial functions, but `# Returns` should remain.)
   * `Errors`, `Panics` sections present where applicable?
   * Boolean returns worded as "Whether ... on success."?
   * No `# Parameters` outside trait declarations?
   * `# Type Parameters` present whenever type parameters exist?
   * `Forwards [\`func\`]` names the exact function (not generic prose); not used for direct errors?
   * No stale references to deleted methods or placeholder names?
   * Blank line before every `///` block?
3. **Error handling**: No `unwrap`? `expect` messages descriptive? No silently-swallowed `Err` arms?
   No bare `let _ = fallible().await`? Error types appropriate? Dead error variants removed?
4. **Symbol ordering**: Public before private? `const` before `static` before normal? Type's own
   `impl` block immediately follows the type definition?
5. **Generic parameters**: `XxxType` suffix? Long descriptive names (`Db` not `DB`)? Constraints
   inline (no `where` clause)? Names consistent between the function signature and its surrounding
   `impl<...>`?
6. **Naming consistency**: When a type was renamed in this PR, are all variables/fields/parameters
   named after the old type also renamed? No `Any_` prefix on type-erased enums? No
   data-structure-type words in identifiers (`dead_workers`, not `dead_worker_set`)?
7. **Trait surface**: Each trait method actually invoked by the consuming layer? No methods exposed
   only for internal helpers?
8. **Config mirroring**: Python source documented? Defaults in sync?
9. **OpenAPI**: API documentation updated if endpoints changed?
10. **Breaking changes**: PR title marked with `!`? Migration path documented?
11. **Efficiency**: Ownership passed where callee needs owned data? No unnecessary clones?
    References preferred over `Arc`/`Vec` when ownership isn't needed? Reference taken when caller
    still needs the value?
12. **Binary data**: Using msgpack for binary payloads? Binary column types in SQL schema?
13. **Constants scoping**: SQL query constants local to methods that use them? Not unnecessarily
    module-level?
14. **Test coverage**: Stand-alone components covered for all basic behaviors, not just the happy
    path? Unrelated test infra left alone?
15. **Formatting**: Blank line before docstring blocks? Use `import` at function scope when the
    import is local to one function?
