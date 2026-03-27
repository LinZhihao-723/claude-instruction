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
