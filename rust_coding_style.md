When editing/reviewing Rust source code, please be aware of the following coding style guidelines.
Please use subagents to parallelize file reading or code processing.

# Linting

Please run the following command in the root directory to make sure all linters are passed (and
fix the errors if necessary):

```bash
task lint:fix-rust
```

For clippy errors, please try to fix it instead of disabling the check by adding
`#[allow(clippy::...)]` to the code. If you need to disable a check, please ask before doing so.

# Using `unwrap`

Do not use `unwrap` in the code, even in the tests. Use `expect` instead, with a descriptive error
message. For example:

```rust
// Bad
let result = some_function().unwrap();

// Good
let result = some_function().expect("this is the error");
```

# Docstrings

You should add docstrings for every function with the following format:

```
/// The short description of what this function does.
///
/// Long description, if the function is complicated.
///
/// # Type Parameters
///
/// * `T` - The first type parameter, if any (with explanation of the type parameter).
/// * `U` - The second type parameter, if any (with explanation of the type parameter).
/// * ...
///
/// # Returns
///
/// The return value. This section can be omitted if the function doesn't return anything, or if
/// it returns `()`. Add "on success" in the end if the function returns a result.
///
/// # Errors
///
/// Returns an error if:
///
/// * Error enum 1 that this function directly returns (with explanation of the error).
///   * The first situation, if multiple
///   * The second situation, if multiple
/// * Error enum 2 that this function directly returns (with explanation of the error).
/// * ...
/// * Forwards [`func`]'s return values on failure (don't need to explain the error, but need to
///   document every function whose return errors are forwarded using `?`).
///
/// # Panics
///
/// The situation where this function panics.
```

You should always use [`symbol`] when referring to a valid symbol in the code.

Examples:

## Example 1: No return value, multiple possible errors.

```
    /// Creates a new S3 ingestion job instance and adds it to the job table with key prefix
    /// conflict detection.
    ///
    /// When multiple ingestion jobs run in parallel, this function ensures that key prefixes do not
    /// conflict with each other, preventing duplicate object ingestion.
    ///
    /// A conflict is detected when all the following conditions are met:
    ///
    /// * The regions of an existing job and the new job are identical, and
    /// * The bucket names of an existing job and the new job are identical, and
    /// * The datasets of an existing job and the new job are identical, and
    /// * The key prefixes are not mutually prefix-free (i.e., one is a prefix of the other).
    ///
    /// # Errors
    ///
    /// Returns an error if:
    ///
    /// * [`Error::InternalError`] if a job ID collision is detected (which is unlikely in
    ///   practice).
    /// * [`Error::PrefixConflict`] if the given key prefix conflicts with an existing job's prefix.
    /// * Forwards [`ValidatedSqsListenerConfig::validate_and_create`]'s return values on failure.
    /// * Forwards [`ClpIngestionState::start`]'s return values on failure.
    async fn create_s3_ingestion_job_instance(
        &self,
        ingestion_job_context: ClpIngestionJobContext,
    ) -> Result<(), Error>
```

## Example 2: With `Returns` section and `Panics` section.

```
    /// Factory function.
    ///
    /// Creates a new ingestion job manager from the given CLP configuration and credentials.
    ///
    /// # Returns
    ///
    /// A newly created ingestion job manager on success.
    ///
    /// # Errors
    ///
    /// Returns an error if:
    ///
    /// * [`anyhow::Error`] if the logs input type in the CLP configuration is unsupported.
    /// * Forwards [`ClpDbIngestionConnector::connect`]'s return values on failure.
    ///
    /// # Panics
    ///
    /// Panics if `clp_config.log_ingestor` is `None`.
    pub async fn from_config(
        clp_config: ClpConfig,
        clp_credentials: ClpCredentials,
    ) -> anyhow::Result<Self>
```

Note: You don't need a docstring for the following situations:

* The function is simple enough, for example, a getter or a setter.
* The function is an implementation of a trait function, and the trait function already has a
  docstring.
* The struct member is private. 

# Symbol ordering

We should use the following symbol ordering rules:

* List by visibility in the order of `pub`, `pub(crate)`, `pub(super)`, `pub(in path)`, private.
* Inside each visibility group:
  * `const` variables/members -> `static` variables/members -> normal variables/members.
  * `struct/enum` followed by their `impl` blocks:
    * `impl` block for itself comes first.
    * `impl` block for internal traits comes second.
    * `impl` block for external traits comes third.
  * Functions.

Note: Inside each `impl` block, public functions should be listed before private functions.

# Error messages

* For error messages inside an error enum, an `expect`, or `panic`, the error message should not
  capitalize the first letter, and it should not end with a period.
* In a log message (e.g., in `tracing`), the error message should start with a capitalized letter,
  and end with a period.

# Naming

## Trait names

We name trait as a type, for example, `Cache` instead of `CacheTrait` or `CacheType`.

## Generic type parameter names

We use long descriptive names for generic type parameters, instead of single letters.

* For lifetime parameters, we use `'lifetime_name`, for example, `'cache_lifetime`.
* For type parameters, we use `XxxType`, for example, `CacheType`.
  * We prefer to put type constraints in the type parameter, for example, `CacheType: Cache` instead
    of `CacheType` with a `where CacheType: Cache` clause.

# Dependencies

Dependencies are specified inside `Cargo.toml` with the requirements:

* The version requirement must be given to the exact patch version, for example, `1.2.3` instead of
  `^1.2` or `~1.2`.
* The dependencies must be sorted alphabetically by the package name.
* Remove unused dependencies. Do not leave stale entries in `Cargo.toml`.

# Enum vs Trait Objects

Prefer enum dispatch over trait objects (`Box<dyn Trait>`) when all variant types are known at compile
time:

```rust
// Preferred: all types known at compile time
enum IngestionJob {
    SqsListener(SqsListener),
    S3Scanner(S3Scanner),
}

// Avoid: unnecessary dynamic dispatch
Box<dyn IngestionJob>
```

Reasons:

* More compact memory layout.
* Enforces explicit handling for all variants (no missing match arms).
* No virtual function overhead.
* Follows the same philosophy as C++ `std::variant` over inheritance.

Only use trait objects when the set of types is truly dynamic or unknown at compile time.

# Ownership and Efficiency

## Pass ownership instead of borrowing when the callee needs owned data

If a function receives a reference but then clones or reconstructs an owned value from it, pass
ownership directly:

```rust
// Bad: callee reconstructs a Vec from the reference
fn submit(ids: &[u64]) {
    let owned = ids.to_vec(); // unnecessary copy
    ...
}

// Good: pass ownership down the call chain
fn submit(ids: Vec<u64>) {
    ...
}
```

## Use `&str` for read-only string access

When a function only needs to read a string value (e.g., checking prefixes, logging), accept `&str`
rather than `&String` or `&NonEmptyString`.

## Use `u64` for sizes that may exceed 32-bit

Prefer `u64` over `usize` for sizes that may exceed the 32-bit range (e.g., S3 object sizes,
accumulated buffer sizes), since `usize` is platform-dependent. For size config variables, use
`xxx_size` without a `_bytes` suffix -- the unit always defaults to bytes.

# Type-Level Validation

Use newtype wrappers to enforce invariants at the type level rather than relying on runtime
validation:

* Use `NonEmptyString` for config fields that must not be empty.
* Wrap validated configs in dedicated types and pass them through the call chain, so downstream code
  can trust the invariants without re-validating.

```rust
// Good: validation at type level
pub struct ValidatedSqsListenerConfig { /* ... */ }

impl ValidatedSqsListenerConfig {
    pub fn validate_and_create(raw: SqsListenerConfig) -> Result<Self, Error> { /* ... */ }
}
```

# Mirroring Python Types

When Rust types mirror existing Python definitions in the codebase:

* Document the Python source in a doc comment.
* Add a note if the type is partially defined (unused fields omitted).
* Defaults must be kept in sync.

```rust
/// Mirror of `job_orchestration.scheduler.constants.QueryJobStatus`. Must be kept in sync.
///
/// # NOTE
///
/// * This type is partially defined: unused fields are omitted and discarded through
///   deserialization.
/// * The default values must be kept in sync with the Python definition.
#[derive(Debug, Serialize, Deserialize)]
pub struct SomeConfig {
    // ...
}
```

# Testing

## No `unwrap` in tests

Use `expect("descriptive message")` even in test code. This rule applies everywhere, including tests.

## Use `anyhow::Result` in test functions

```rust
#[tokio::test]
async fn test_something() -> anyhow::Result<()> {
    let result = do_something().await?;
    assert_eq!(result, expected);
    Ok(())
}
```

## Prefer real-time testing for complex async code

Avoid `tokio::time::pause()` when the implementation uses `select!` in long-running loops. Time
simulation only guarantees ordering for `sleep` calls and does not reliably control `select!`
behavior. Use real-time testing with appropriate timeouts instead.

## Use mock/noop states for unit tests

Implement trivial noop or mock state structs so that unit tests don't require external services
(e.g., databases). Trait-based state abstractions enable this pattern.

# Module Organization

## Shorten internal type names

When a type is internal to a module, use a short name and let users reference it via the module path:

```rust
// Inside ingestion_job/sqs_listener.rs
pub struct SqsListener { /* ... */ }
struct Task { /* ... */ }  // internal, shortened from SqsListenerTask

// Users reference as:
use ingestion_job::SqsListener;
```

## Dedicated error files

For components with multiple error types, create a dedicated `error.rs` module rather than defining
errors inline.

## Reusable code belongs in `clp-rust-utils`

If code in `api-server` or `log-ingestor` could be shared across components, it should be moved to
`clp-rust-utils`. Examples:

* MySQL pool creation utilities
* Config structs and deserialization
* AWS client creation helpers
* Common type definitions (e.g., job IDs)
