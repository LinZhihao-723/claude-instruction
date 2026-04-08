# Rust PR Review Skill

When reviewing Rust PRs in y-scope repositories (e.g., `y-scope/clp` for `api-server`, `log-ingestor`,
`clp-rust-utils` components, and `y-scope/spider` for `spider-core`, `spider-storage` components),
apply the following review guidelines. These are derived from historical review patterns and project
conventions.

Also refer to `coding-style.md` for coding style requirements. This skill focuses on PR-level
review patterns and conventions beyond the coding style.

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

### Prefix error context with lowercase, no trailing period

Use `context("cannot load config file ...")` with lowercase start, no period -- consistent with the
error message conventions in `rust_coding_style.md`.

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
2. **Changes requested**: List specific items to fix. Use GitHub suggestion blocks for small fixes.
3. **Follow-up reviews**: Verify requested changes are addressed.
4. **Approval**: Suggest a final PR title. Verify the PR can be merged.

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

## Common Review Checks

1. **Cargo.toml**: Dependencies pinned to exact patch version? Alphabetically sorted? Unused
   dependencies removed?
2. **Docstrings**: All public functions documented with the project's docstring format? `Returns`,
   `Errors`, `Panics` sections present where applicable? Forwarded errors name the exact function?
3. **Error handling**: No `unwrap`? `expect` messages descriptive? Error types appropriate? Dead
   error variants removed?
4. **Symbol ordering**: Public before private? `const` before `static` before normal?
5. **Generic parameters**: Long descriptive names (`Db` not `DB`)? Constraints in parameter position?
6. **Config mirroring**: Python source documented? Defaults in sync?
7. **OpenAPI**: API documentation updated if endpoints changed?
8. **Breaking changes**: PR title marked with `!`? Migration path documented?
9. **Naming**: Trait names as types (not suffixed)? Module-level name shortening where appropriate?
10. **Efficiency**: Ownership passed where callee needs owned data? No unnecessary clones? References
    preferred over `Arc`/`Vec` when ownership isn't needed?
11. **Binary data**: Using msgpack for binary payloads? Binary column types in SQL schema?
12. **Constants scoping**: SQL query constants local to methods that use them? Not unnecessarily
    module-level?
13. **Formatting**: Blank line before docstring blocks? Use `import` at function scope when the import
    is local to one function?
