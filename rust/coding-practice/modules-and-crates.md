# Modules, crates and API surface

A crate's visibility markers, re-exports and `Cargo.toml` are its API. They decide what other code
can depend on, and so what you can no longer change freely. Every item that is wider than it needs
to be is a promise someone else can rely on, and every dependency edge that points the wrong way
turns the next refactor into a change across several crates. The rules below keep the public surface
small and deliberate, put each piece of code in the one crate that owns it, and make contract
changes visible before they break a consumer in another repository or another language.

## MOD-1: Give every item the narrowest visibility its intended callers need

**Rule.** Start every item private. Widen it to `pub(super)` or `pub(crate)` only as far as a real
caller needs, and make it `pub` only when it belongs to the crate's external API. In a package
delivered as a binary, even one with a `lib.rs` that its `src/bin/` targets use, only what those
targets call is `pub`.

**Why.** Every `pub` item is a contract. Other crates can depend on it, and narrowing it later is a
breaking change. A `pub` item in `api-server`, which is not delivered as a library, promises an API
to consumers that don't exist, and readers can no longer tell the real entry points from the
helpers. Rust privacy is per module, not per type. Developers coming from C++ often make a field
`pub` to imitate `friend`, which lets any crate break the type's invariants. Putting the two types
in the same module gives the same access and exports nothing.

```rust,ignore
// Bad: `timeline/bucket.rs`
pub struct Bucket {
    pub count: u64,
}

impl Bucket {
    pub fn try_from_aggregation_document(document: &Document) -> Result<Self, Error> { /* ... */ }
}
```

```rust,ignore
// Good
pub struct Bucket {
    count: u64,
}

impl Bucket {
    pub const fn count(&self) -> u64 {
        self.count
    }

    pub(super) fn try_from_aggregation_document(document: &Document) -> Result<Self, Error> { /* ... */ }
}
```

**Review.**
- For each new `pub` item, ask who outside the crate calls it. If nobody does, or the package is a
  binary whose `src/bin/` targets don't call it, ask for `pub(crate)` or narrower.
- Flag a `pub` field that exists only so a sibling type can write it. The fix is to move the two
  types into one module, or to add a narrow method.
- Flag internal DTOs, parsing helpers, encodings and test structs that are `pub`.

See also: OBJ-1 (private fields protect invariants).

**Sources.**

- [y-scope/clp#2578](https://github.com/y-scope/clp/pull/2578#discussion_r4503774877): reviewer narrows `Bucket::try_from_aggregation_document` to `pub(super)`
- [y-scope/clp#2690](https://github.com/y-scope/clp/pull/2690#discussion_r4530585669): `SseEncoding` should be crate-public, since `api-server` isn't delivered as a library
- [y-scope/clp#2564](https://github.com/y-scope/clp/pull/2564#discussion_r4253602162): reviewer flags a `pub` struct that is only for internal use
- [RustTraining c-cpp-book § `friend` and Access Control → Module Visibility](https://microsoft.github.io/RustTraining/c-cpp-book/ch18-cpp-rust-semantic-deep-dives.html#friend-and-access-control--module-visibility): same-module access replaces `friend`

## MOD-2: Treat every contract change as breaking, and make the breakage loud rather than tolerated

**Rule.** Mark a PR breaking (`!`, with a migration note) when it changes any of these: the public
items of a crate consumed from another repository; a serialized format (DB schema or JSON/msgpack
column, task input, wire protocol, FFI entry points); or a user-visible config, including an added
or removed key, a renamed variant or a changed default. Before merging, list every producer and
consumer of the format, including non-Rust ones, and either update them or file tracked issues.
Readers of a format that has changed reject the old shape. They don't quietly accept it.

**Why.** The Rust compiler can't see a Python or WebUI producer. In
[y-scope/clp#2652](https://github.com/y-scope/clp/pull/2652#pullrequestreview-5729998540), the typed
`QueryJobConfig` with `deny_unknown_fields` broke the MCP server, which still wrote the old flat
config, so its searches would fail on new deployments. The failure was loud, so it was found in
review and tracked ([y-scope/clp#2656](https://github.com/y-scope/clp/issues/2656)). A tolerant
reader would have run an empty query in silence. Users who never set a field still depend on its
default. Raising a buffer threshold 16x can run memory-constrained systems out of memory with no
change to their config. A `pub` item that no other repository consumes is not a contract, so
changing it doesn't need `!`.

```rust,ignore
// Bad: every field optional, unknown fields ignored
#[derive(Deserialize)]
pub struct QueryJobConfig {
    pub query_string: Option<String>,
    pub begin_timestamp: Option<i64>,
    pub end_timestamp: Option<i64>,
    pub max_num_results: Option<u32>,
}
```

```rust,ignore
// Good: a writer still on another shape fails to deserialize
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct QueryJobConfig {
    #[serde(default = "QueryJobConfig::default_datasets")]
    pub datasets: Vec<DatasetName>,
    pub query: SearchQuery,
    pub output: QueryOutput,
}
```

**Review.**
- For any change to a serde type stored in a database or sent over the wire, ask for the list of
  writers and readers across languages. A Rust build that compiles is not evidence of compatibility.
- Treat a changed `#[serde(default = ...)]` value, a renamed `#[serde(rename)]` or a new required
  field as breaking. Check the title for `!` and the description for an `[!Important]` migration
  note, and check that the chart and image versions are bumped: the publish workflow skips a Helm
  chart whose version didn't change, while CI still reports success.
- Flag `#[non_exhaustive]` on enums that only our own crates consume. It makes adding a variant
  non-breaking by switching off exhaustiveness checking in every other crate, which removes the
  compile error that would have forced each consumer to handle the new state.

**Exceptions.** The RustTraining books recommend `#[non_exhaustive]` for public enums. That advice
fits a crate published for third parties that mirrors a vocabulary outside our control and expected
to grow, such as an external API's status codes.

See also: pr-review.md § PR Title Convention, Common Review Checks #10, BND-2 (strict schemas) and
BND-6 (defaults).

**Sources.**

- [y-scope/clp#2652](https://github.com/y-scope/clp/pull/2652#pullrequestreview-5729998540): reviewer finds the MCP server still writes the old flat config
- [y-scope/clp#2656](https://github.com/y-scope/clp/issues/2656): tracks MCP server searches failing on the new `QueryJobConfig`
- [y-scope/clp#2564](https://github.com/y-scope/clp/pull/2564#discussion_r4253602162): `ArchiveMetadata` is internal, so replacing its field isn't breaking
- [y-scope/clp#2620](https://github.com/y-scope/clp/pull/2620#discussion_r4403220812): reviewer asks to mark a partitioning behaviour change as breaking
- [y-scope/clp#1965](https://github.com/y-scope/clp/pull/1965#discussion_r2788682533): a 16x default threshold may crash memory-constrained deployments
- [y-scope/clp#1965](https://github.com/y-scope/clp/pull/1965#pullrequestreview-3781975663): maintainers confirm the changed default is breaking and add `!`
- [y-scope/clp#1962](https://github.com/y-scope/clp/pull/1962): renames the `ec2` auth variant to `default`, marked breaking
- [y-scope/spider#464](https://github.com/y-scope/spider/pull/464#discussion_r3897792061): reviewer asks to mark the storage and protocol changes breaking
- [y-scope/spider#418](https://github.com/y-scope/spider/pull/418): Helm chart version bump required, or publishing silently skips it
- [y-scope/spider#409](https://github.com/y-scope/spider/pull/409): a new FFI entry point, marked breaking with a migration note
- [RustTraining type-driven-correctness-book § `#[non_exhaustive]` for Evolving Enums](https://microsoft.github.io/RustTraining/type-driven-correctness-book/ch11-fourteen-tricks-from-the-trenches.html#trick-3--non_exhaustive-for-evolving-enums): the `#[non_exhaustive]` advice the Exceptions narrow
- [RustTraining rust-patterns-book § Public API Design Checklist](https://microsoft.github.io/RustTraining/rust-patterns-book/ch15-crate-architecture-and-api-design.html#public-api-design-checklist): recommends `#[non_exhaustive]` on public enums (see Exceptions)

## MOD-3: Declare each dependency once, pin cross-repo ones to a commit, and bump every reference together

**Rule.** Declare every external crate and every git dependency once, in the root
`[workspace.dependencies]`. Members use `{ workspace = true }` and only add features. Pin a git
dependency on a sibling repository to a `rev`, never a branch. When you bump it, update every
artifact built from that repository (Cargo, Dockerfiles, Compose and Helm image tags) in the same
PR. Prefer a mature, widely used crate over a newer one that exposes `unsafe` interfaces or says it
isn't production-ready.

**Why.** Versions pinned per crate drift apart. The clp workspace once had `tokio` at both 1.49.0
and 1.52.3, which meant duplicate builds and a separate edit per crate for every bump. Tracking
`main` lets an upstream merge break us with no change on our side. A partial bump fails silently. In
[y-scope/clp#2532](https://github.com/y-scope/clp/pull/2532#issuecomment-5908243126), one Dockerfile
kept an older Spider worker image that ignored the resource-group env vars, so dedicated workers
registered as general and nothing reported an error. A dependency with an `unsafe` API hands its
memory-safety obligations to our code. A deprecated but widely used crate is still safer than a
maintained alternative with a thousandth of the users.

```toml
# Bad: `components/foo/Cargo.toml`
spider-client = { git = "https://github.com/y-scope/spider.git", branch = "main" }
tokio = { version = "1.49.0", features = ["rt"] }
```

```toml
# Good: root `Cargo.toml`
[workspace.dependencies]
spider-client = { git = "https://github.com/y-scope/spider.git", rev = "278d06f81fe0fd0ff62292ee8c6f4cd63a529bfc" }
tokio = "1.52.3"

# `components/foo/Cargo.toml`
tokio = { workspace = true, features = ["rt"] }
```

**Review.**
- Flag a `version =` or `git =` in a member manifest.
- On a cross-repo bump, grep the repository for the old revision and image tag. Every hit must
  change in the PR, and the PR is a candidate for `!` (MOD-2).
- Flag a dependency that isn't the obvious mature crate when the PR description gives no reason for
  choosing it.

See also: coding-style.md § Dependencies (exact patch versions, sorted, no unused entries).

**Sources.**

- [y-scope/clp#2471](https://github.com/y-scope/clp/pull/2471): moves every crate version into `[workspace.dependencies]`
- [y-scope/clp#2532](https://github.com/y-scope/clp/pull/2532#pullrequestreview-5360553746): reviewer asks to pin Spider to a commit instead of `main`
- [y-scope/clp#2532](https://github.com/y-scope/clp/pull/2532#issuecomment-5908243126): one Dockerfile's Spider worker image was left unpinned
- [y-scope/clp#2549](https://github.com/y-scope/clp/pull/2549#discussion_r4170144866): the Spider bump changes the DB schema, so mark it breaking
- [y-scope/clp#2375](https://github.com/y-scope/clp/pull/2375#discussion_r3814730160): prefer `zstd` over `libzstd-rs-sys`, which has `unsafe` APIs and isn't production-ready
- [y-scope/clp#2312](https://github.com/y-scope/clp/pull/2312#issuecomment-4650233848): a deprecated but widely used crate beats a little-used alternative
- [y-scope/spider#285](https://github.com/y-scope/spider/pull/285#discussion_r2970704684): reviewer asks to lock dependencies to exact patch versions
- [y-scope/spider#289](https://github.com/y-scope/spider/pull/289): locks `serde` to 1.0.228

## MOD-4: Place code by dependency direction, and share it once a second consumer needs it

**Rule.** Keep the crate graph layered. The internal utils crate depends on no other workspace
crate. The core domain crate depends only on utils and its derive crate, and stays
protocol-agnostic. The protocol crate holds only generated code and the `From`/`TryFrom` impls
between wire and domain types. A client trait lives in the crate that consumes it, next to its
implementation. A helper moves down into a shared crate when a second crate uses it. Until then it
stays with its only consumer and that consumer's tests.

**Why.** Depending on `spider-storage` to reuse one struct pulls in its whole DB stack and can
create a dependency cycle. A domain crate that depends on protobuf types forces every protocol
change on consumers that never speak gRPC, and it mixes domain invariants with wire details such as
`Unspecified` or optional sub-messages. The conversions satisfy the orphan rule when they live in
the protocol crate, because the generated types are local there, so no wrapper types are needed. A
helper moved into a shared crate too early, like `scan_prefix` in
[y-scope/clp#2224](https://github.com/y-scope/clp/pull/2224#discussion_r3144459192), also loses the
test infrastructure (localstack) that its only consumer already had.

```toml
# Bad: `spider-scheduler/Cargo.toml`
[dependencies]
spider-storage = { workspace = true } # only for `RegisteredScheduler`
```

```toml
# Good: `RegisteredScheduler` lives in `spider-core`
[dependencies]
spider-core = { workspace = true }
spider-proto-rust = { workspace = true }
```

**Review.**
- For each new `[dependencies]` edge between workspace crates, ask what is used across it. If it is
  one type, ask for that type to move down.
- Flag `prost`/`tonic` imports in a domain crate, and wire conversions defined outside the protocol
  crate (BND-4).
- Flag a component-specific trait placed in the protocol or core crate. The fix is
  `consumer/src/xxx_client/{mod.rs (trait), grpc.rs (impl)}`.

**Exceptions.** A planned PR series that adds the second consumer soon may move the code early. Say
so in the PR description.

See also: coding-style.md § Reusable code belongs in `clp-rust-utils`. That section says where
shared code goes, and this rule says when code counts as shared.

**Sources.**

- [y-scope/spider#333](https://github.com/y-scope/spider/pull/333#pullrequestreview-4422940472): a component's client trait stays in its consumer crate, not the proto crate
- [y-scope/spider#340](https://github.com/y-scope/spider/pull/340#pullrequestreview-4489303309): restructures the client as `storage_client/{mod.rs, grpc.rs}`
- [y-scope/spider#347](https://github.com/y-scope/spider/pull/347#pullrequestreview-4519930341): moves `RegisteredScheduler` into `spider-core` rather than depending on `spider-storage`
- [y-scope/spider#355](https://github.com/y-scope/spider/pull/355): `spider-utils` depends on no Spider crate; `spider-core` builds on it
- [y-scope/spider#362](https://github.com/y-scope/spider/pull/362): config loader moves into `spider-utils` once a second service needs it
- [y-scope/clp#2224](https://github.com/y-scope/clp/pull/2224#discussion_r3144459192): keep `scan_prefix` in `log-ingestor`, its only consumer, with localstack tests
- [y-scope/clp#2655](https://github.com/y-scope/clp/pull/2655): a crate is shared if other crates depend on it and nothing deploys it
- [spider `spider-proto-rust/src/lib.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-proto-rust/src/lib.rs#L3-L51): generated code plus wire/domain conversion modules only
- [spider `spider-utils/Cargo.toml`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-utils/Cargo.toml#L10-L21): `[dependencies]` lists no workspace crate

## MOD-5: Make `mod.rs` a table of contents: declarations and named re-exports only

**Rule.** A multi-file module's `mod.rs` (or parent file) only declares submodules and re-exports
items by name: `pub use` for the API and `pub(crate) use` for crate-internal entry points. A
submodule that only organises files stays private. Use `pub mod` only for a namespace that is itself
part of the API. Never write `pub use child::*`.

**Why.** A glob re-export publishes every `pub` item ever added to the child, so a new helper joins
the crate's API without showing up in any diff. Public file-organising submodules let siblings and
other crates reach into each other's internals. Before
[y-scope/clp#2713](https://github.com/y-scope/clp/pull/2713), `connection` and `cursor` sat beside
`session` at the crate root, so `session` and `connection` depended on each other's internals
through `pub(crate)` items. Named re-exports document the contract in one place, and they let the
files behind the module be rearranged without touching any caller.

```rust,ignore
// Bad
pub mod connection;
pub mod cursor;
pub mod registry;

pub use registry::*;
```

```rust,ignore
// Good: `session/mod.rs`
mod cancellation_guard;
mod connection;
mod cursor;
mod open_session;
mod registry;

pub(crate) use connection::serve;
pub use open_session::OpenSession;
pub(crate) use registry::SessionRegistry;
```

**Review.**
- Flag `pub use ...::*`, and `pub mod` on a submodule that only exists to organise files.
- When a large file is split into a module directory, check that nothing new became visible outside
  the parent. Items that tests in sibling files use get `pub(super)`, not `pub(crate)`.
- Ask for the split to land as a move-only PR, separate from any behaviour change. Verify it with
  `git diff --color-moved` and an unchanged test list.

See also: coding-style.md § Module Organization.

**Sources.**

- [y-scope/clp#2713](https://github.com/y-scope/clp/pull/2713): turns `session` into a module that owns `connection` and `cursor`
- [y-scope/spider#382](https://github.com/y-scope/spider/pull/382): converts multi-file modules to the `mod.rs` layout
- [y-scope/spider#542](https://github.com/y-scope/spider/pull/542): move-only split of `db/mariadb.rs`, checked with `git diff --color-moved`
- [y-scope/spider#555](https://github.com/y-scope/spider/pull/555): `mod.rs` holds only submodule declarations and named re-exports
- [clp `clp-rust-libs/query-result-listener/src/session/mod.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/query-result-listener/src/session/mod.rs#L3-L19): private submodules with named `pub` and `pub(crate)` re-exports

## MOD-6: Give each shared type one owning crate and one import path

**Rule.** Define a shared type in exactly one crate, and have every consumer import it from there. A
crate that other crates depend on doesn't `pub use` another workspace crate's type unless its own
public signatures need it (MOD-7). For a domain-specific name, rename the type at the import (`use
spider_core::types::id::JobId as SpiderJobId;`). A crate-internal re-export under that name from the
module that owns the concept is fine.

**Why.** If a type can be imported from several paths, consumers drift onto whichever path they
found first. Moving the type then breaks all of them, and it is no longer clear which crate owns its
invariants. In
[y-scope/spider#469](https://github.com/y-scope/spider/pull/469#discussion_r3985370201), the review
removed `spider-storage`'s re-export of `ExternalResourceGroupCredentials` once the type lived in
`spider-core`. Otherwise callers would have kept depending on the storage crate just to name a
credentials type.

```rust,ignore
// Bad: `spider-storage/src/db/mod.rs`
pub use spider_core::types::resource_group::ExternalResourceGroupCredentials;
```

```rust,ignore
// Good: consumers import it from the owner
use spider_core::types::resource_group::ExternalResourceGroupCredentials;
```

**Review.**
- Flag `pub use` of another workspace crate's type in a library's public API when none of the
  library's public signatures mention it.
- When a type moves, check that the old path is deleted rather than kept as a forwarding re-export.
  If another repository imported the old path, the PR is breaking (MOD-2).

See also: coding-style.md § Type Aliases for External Types, which applies the same one-owner
principle to third-party types.

**Sources.**

- [y-scope/spider#469](https://github.com/y-scope/spider/pull/469#discussion_r3985370201): reviewer removes `spider-storage`'s re-export of the moved credentials type
- [y-scope/clp#2087](https://github.com/y-scope/clp/pull/2087#discussion_r2965730998): move `JobId` to its owning module and re-export it as `IngestionJobId`
- [clp `query-coordinator/src/coordination.rs`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/query-coordinator/src/coordination.rs#L37-L39): imports `JobId as SpiderJobId` and credentials from `spider_core`

## MOD-7: Give user-facing crates a small facade, and keep transport and generated types private

**Rule.** A crate meant for callers outside the workspace exposes a small facade (for example
`SpiderClient` and its builder) whose methods take and return domain types. It re-exports at the
crate root every type from an internal helper crate that a public signature mentions. Transport
clients, connection pools and generated-proto wrappers live in a private module.

**Why.** If the inner gRPC clients are public, users come to depend on transport details, and then
changing the connection pool or the proto layout needs a breaking release. If a public signature
mentions a type from an internal crate (`RetryConfig` from `spider-utils`) or a deep generated path
(`job_orchestration_service_client::JobOrchestrationServiceClient`) and that type isn't re-exported,
every caller has to add the internal crate as a dependency or spell out codegen paths, and any
codegen change breaks them.

```rust,ignore
// Bad: `spider-client/src/lib.rs`
pub mod client;
pub mod job;
pub mod resource_group;
```

```rust,ignore
// Good
mod client;
mod error;
mod grpc;

pub use client::SpiderClient;
pub use client::SpiderClientBuilder;
pub use error::ClientError;
pub use spider_utils::grpc::retry::RetryConfig;
```

**Review.**
- Read the crate root as a user would. Can every public signature be written using only the names it
  exports plus the domain crate users already depend on?
- Flag public items, docs or signatures that expose connection pools, channels, or generated gRPC
  clients and messages.

**Sources.**

- [y-scope/spider#363](https://github.com/y-scope/spider/pull/363#discussion_r3492747900): users shouldn't need to know the underlying client types
- [y-scope/spider#363](https://github.com/y-scope/spider/pull/363#discussion_r3492717206): group the gRPC clients in a crate-private `grpc` module
- [y-scope/spider#382](https://github.com/y-scope/spider/pull/382): hides deep tonic-generated paths behind tidy re-exports
- [y-scope/spider#396](https://github.com/y-scope/spider/pull/396): re-exports `SpiderClientBuilder` and `RetryConfig` from the crate root
- [spider `spider-client/src/lib.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-client/src/lib.rs#L10-L16): the crate-root facade (the Good example adapts it to MOD-5)
- [spider `spider-proto-rust/src/lib.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-proto-rust/src/lib.rs#L26-L51): flat re-exports of deep generated client and server paths

## MOD-8: Keep test-only code out of the production surface and dependency graph

**Rule.** Put test helpers in `#[cfg(test)]` modules. Gate a helper behind a `test-utils` Cargo
feature (`#[cfg(any(test, feature = "test-utils"))]`) only when another crate's tests use it, add
the feature in the same PR as that use, and enable it only from consumers' `[dev-dependencies]`.
Declare the helper's dependencies as `dep:` optional deps of the feature and again under
`[dev-dependencies]`, because `cfg(test)` does not turn the feature on. A `pub` item whose docstring
says "for tests" is not a gate.

**Why.** `#[cfg(test)]` does not cross crate boundaries, so helpers that other crates need tend to
become plain `pub`. `spider-core`'s `Id::random()` is public, so production code can create IDs that
collide with storage-assigned ones. It also makes `rand` a normal dependency of every crate built on
`spider-core`, although only tests call it. The opposite mistake is a speculative `test-utils`
feature that nothing uses. It adds public API and a build configuration that nobody runs.

```rust,ignore
// Bad: `spider-core/src/types/id.rs`, `rand` under `[dependencies]`
/// Creates a random ID for tests.
pub fn random() -> Self {
    Self::from(rand::random())
}
```

```rust,ignore
// Good: `[features] test-utils = ["dep:rand"]`, and `rand` also under `[dev-dependencies]`
#[cfg(any(test, feature = "test-utils"))]
pub fn random() -> Self {
    Self::from(rand::random())
}
```

**Review.**
- Flag `pub` items documented as test-only, and test-only crates (`rand`, mocks, fixtures) listed
  under `[dependencies]`.
- Flag a new `test-utils` or `test-hooks` feature that no other crate's tests use in the same PR.
  The fix is `#[cfg(test)]`.
- Check that the feature is enabled only under `[dev-dependencies]`, never under `[dependencies]`.

See also: coding-style.md § What deserves a unit test (no test-only seams), TEST-7 (enabling the
feature for a crate's own integration tests, and keeping mocks within the real contract).

**Sources.**

- [spider `spider-core/src/types/id.rs`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/src/types/id.rs#L42-L48): `Id::random()` is `pub` and only documented as for tests (the Bad example)
- [spider `spider-core/Cargo.toml`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-core/Cargo.toml#L12): `rand` is a normal dependency of `spider-core`
- [y-scope/clp#2649](https://github.com/y-scope/clp/pull/2649#discussion_r4438381331): reviewer questions an unused `test-utils` feature; `#[cfg(test)]` suffices
- [y-scope/clp#2690](https://github.com/y-scope/clp/pull/2690#discussion_r4530585669): integration tests made `SseEncoding` `pub`; move them into `src/sse.rs`
- [clp `clp-rust-libs/query-result-listener/Cargo.toml`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/clp-rust-libs/query-result-listener/Cargo.toml#L10-L29): `test-utils` feature, enabled for its own tests from `[dev-dependencies]`
- [clp `api-server/Cargo.toml`](https://github.com/y-scope/clp/blob/2c617be50c21aa66968033bbcaefc4c2d8665fa2/components/api-server/Cargo.toml#L46-L49): enables `test-utils` only under `[dev-dependencies]`

## MOD-9: Declare the intended visibility when staged code lands, and silence dead code with `expect`

**Rule.** When a library item or subsystem lands before its consumer, give its items the visibility
the final design calls for, not "private until used". Silence the interim dead-code warning on the
module declaration with `#[expect(dead_code, reason = "...")]`, never `#[allow(dead_code)]`. Use
`#[cfg_attr(not(test), expect(...))]` when the module's own tests use every item.

**Why.** If everything is private, reviewers can't tell which methods are the API and which are
helpers. If everything is `pub`, siblings start coupling to internals. An `allow` stays in the code
silently after it is no longer needed. An `expect` raises an "unfulfilled lint expectation" warning
as soon as the consumer lands, the lint task (`clippy --all-targets -- -D warnings`) rejects that
warning, and the `reason` tells the author which line to delete. A plain `expect` on a module whose
tests use every item is unfulfilled when the tests are built, so it raises the warning it was meant
to silence.

```rust,ignore
// Bad
#[allow(dead_code)]
pub mod job_registry;
```

```rust,ignore
// Good
#[cfg_attr(
    not(test),
    expect(dead_code, reason = "the core that consumes the registry has not landed yet")
)]
mod job_registry;
```

**Review.**
- Flag a new subsystem whose items are all private "because nothing calls them yet". Ask for their
  final visibility plus an `expect`.
- Flag `#[allow(dead_code)]`, and an `expect` with no `reason`.
- Check that the PR that wires up the consumer also deletes the `expect`.

**Exceptions.** This is the one sanctioned way to suppress a lint while code is being staged. Any
other `allow` or `expect`, and any clippy lint in particular, still follows coding-style.md §
Linting: fix the code, or ask first.

**Sources.**

- [y-scope/clp#2676](https://github.com/y-scope/clp/pull/2676#discussion_r4488093523): reviewer asks for final visibility instead of all-private, silencing `dead_code`
- [y-scope/clp#2690](https://github.com/y-scope/clp/pull/2690): the `sse` module expects `dead_code` outside tests until the endpoint lands
- [y-scope/spider#444](https://github.com/y-scope/spider/pull/444): items are `pub(super)` for the coming core, with `expect(dead_code, reason)`
- [y-scope/spider#449](https://github.com/y-scope/spider/pull/449): uses `cfg_attr(not(test), expect(...))` since its tests use every item
- [y-scope/spider#465](https://github.com/y-scope/spider/pull/465): the shared reader lands `pub(super)` before its second consumer

## MOD-10: Keep Cargo features additive and declare optional dependencies with `dep:`

**Rule.** A feature only adds capability. Enabling it never removes or changes behaviour that other
code relies on. Declare optional dependencies as `feature = ["dep:crate"]`, keep `default` minimal,
and make sure the crate builds both with no features and with all features.

**Why.** Cargo unifies features across the whole dependency graph. Once any one crate enables a
feature that changes behaviour, every crate gets the change, and a crate that never asked for it
breaks. A bare optional dependency also creates an implicit feature named after the dependency. That
leaks the dependency's name into the public feature set and makes renaming it a breaking change. Our
lint task builds only `--all-features`, so code behind `#[cfg(not(feature = "..."))]` and the
no-feature build go unchecked unless someone asks for them.

```toml
# Bad
[features]
derive = ["spider-tdl-derive"]
legacy-encoding = [] # switches the wire format when enabled
```

```toml
# Good: `spider-tdl/Cargo.toml`
[features]
default = []
derive = ["dep:spider-tdl-derive"]
```

**Review.**
- Flag `#[cfg(not(feature = "x"))]` code that is an alternative implementation rather than an absent
  capability.
- Flag optional dependencies declared without `dep:`, and features added to `default` without a
  reason.
- For a crate with two or more features, ask for `--no-default-features` and `--all-features` builds
  (or `cargo hack check --each-feature`) in CI or in the PR's testing notes.

**Sources.**

- [spider `spider-tdl/Cargo.toml`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/components/spider-tdl/Cargo.toml#L6-L8): `default = []` and `derive = ["dep:spider-tdl-derive"]`
- [spider `taskfiles/lint.yaml`](https://github.com/y-scope/spider/blob/d229555f31b40c63e2196a6d505cbbcc692cb91e/taskfiles/lint.yaml#L206-L215): clippy runs only with `--all-features`
- [RustTraining rust-patterns-book § Feature Flags and Conditional Compilation](https://microsoft.github.io/RustTraining/rust-patterns-book/ch15-crate-architecture-and-api-design.html#feature-flags-and-conditional-compilation): use `dep:` and keep `default` minimal
- [RustTraining engineering-book § Verifying Feature Combinations with `cargo-hack`](https://microsoft.github.io/RustTraining/engineering-book/ch09-no-std-and-feature-verification.html#verifying-feature-combinations-with-cargo-hack): build-check every feature combination

## Checklist

- **MOD-1**: A new `pub` item with no caller outside the crate, or in a binary package not called by
  its `src/bin/` targets; ask for `pub(crate)`/`pub(super)`, or a private field plus a getter.
- **MOD-2**: A serde/DB/wire/FFI/config contract changed (default, rename, new required field,
  removed key) without `!`, a migration note, a list of cross-language writers/readers, or a
  chart/image bump, or with a tolerant reader that silently accepts the old shape;
  `#[non_exhaustive]` on an enum only our crates consume.
- **MOD-3**: `version =`/`git =` in a member manifest, a git dep on `branch`, a cross-repo bump that
  leaves an old rev/image tag behind, or an immature/unsafe-API crate chosen without a reason.
- **MOD-4**: A new workspace dependency edge used for one type, `prost`/`tonic` in the domain crate,
  wire conversions outside the protocol crate, a component-specific trait in core/proto, or a helper
  moved to a shared crate before it has a second consumer.
- **MOD-5**: `pub use child::*`, `pub mod` on a file-organising submodule, a module split that
  widens visibility (sibling test files need `pub(super)`), or a split mixed with behaviour changes.
- **MOD-6**: A library `pub use` of another workspace crate's type that none of its public
  signatures mention, or a forwarding re-export kept at a moved type's old path.
- **MOD-7**: A user-facing crate exposes pools, channels or generated gRPC clients, or a public
  signature names an internal-crate type that the crate root doesn't re-export.
- **MOD-8**: A `pub` item documented as test-only, a test-only crate under `[dependencies]`, a
  `test-utils` feature with no cross-crate test consumer in the PR or enabled outside
  `[dev-dependencies]`, or a feature-gated helper whose deps are missing from `[dev-dependencies]`.
- **MOD-9**: `#[allow(dead_code)]` or an `expect` without `reason`, a plain `expect` on a module its
  tests fully use (needs `cfg_attr(not(test), ...)`), a staged subsystem left all-private, or a
  consumer PR that leaves the `expect` in place.
- **MOD-10**: A feature that switches behaviour instead of adding capability, an optional dep
  without `dep:`, an unexplained `default` addition, or a multi-feature crate with no
  no-default/all-features build evidence.
