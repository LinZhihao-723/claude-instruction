# C++ Code Review Guideline

Use this guideline when reviewing C++ pull requests. This document is derived from 111
reviewer-approved PRs in the [y-scope/clp](https://github.com/y-scope/clp) project (April 2024 --
March 2026), reviewed by senior maintainers. Apply these rules consistently during code review.

---

## 1. Naming Conventions

The baseline naming rules (case, prefix, suffix for all identifier categories) are enforced by
clang-tidy's `readability-identifier-naming` checks. Refer to the authoritative
[`.clang-tidy`](https://github.com/y-scope/yscope-dev-utils/blob/main/exports/lint-configs/.clang-tidy)
config for the complete rule set. The subsections below cover **conventions that go beyond what
clang-tidy enforces** -- semantic naming rules, prefixes with domain meaning, and common pitfalls
caught during review.

### 1.1 Semantic Naming Rules (Not Enforced by Tooling)

| Context | Convention | Examples |
|---|---|---|
| Counter / size variables | `num_` prefix | `num_uncompressed_bytes`, `num_log_events` (not `uncompressed_bytes`) |
| Index variables | `idx` suffix (not `ix`) | `placeholder_idx`, `log_event_idx` |
| Optional variables | `optional_` prefix | `optional_two_digit_year`, `optional_timezone_offset` |
| Boolean variables | Descriptive predicate names | `is_escaped`, `case_sensitive_match`, `has_scientific_notation` |
| Template type parameters | `UpperCamelCase` + `Type` suffix | `EntryType`, `ReaderType`, `DictionaryEntryType` |

### 1.2 Naming Precision

- Names must be semantically accurate and not temporally biased.
  - Bad: `cNewTimestampFormatVersion` (won't always be "new").
  - Good: `cDeprecatedTimestampFormatVersionMarker`.
- Method names must describe the full action, including side effects.
  - Bad: `pop_stack` when it also updates results.
  - Good: `pop_from_ast_dfs_stack_and_update_evaluation_results`.
- Use `indices` as the plural of `index` (not `indexes`).

### 1.3 File Naming

- Files containing class/type definitions: `UpperCamelCase.hpp` / `UpperCamelCase.cpp`.
- Files containing only free functions or utilities (no classes/types): `snake_case.hpp` /
  `snake_case.cpp`.

---

## 2. Formatting and Style

### 2.1 Brace Initialization

Use `{}` (brace initialization) for **all** variable initialization and object construction:

```cpp
// Good
size_t search_start_pos{0};
bool is_escaped{false};
char const* tame_current{tame.data()};
auto const init_result{ZSTD_initCStream(m_compression_stream, compression_level)};

// Bad
size_t search_start_pos = 0;
bool is_escaped = false;
char const* tame_current = tame.data();
```

### 2.2 Trailing Return Type

All functions must use the trailing return type syntax:

```cpp
// Good
[[nodiscard]] auto find_first_of(std::string_view haystack, char const* needles) -> size_t;
auto to_lower(std::string& str) -> void;
auto operator=(FilterExpr const&) -> FilterExpr& = delete;

// Bad
size_t find_first_of(std::string_view haystack, char const* needles);
void to_lower(std::string& str);
```

### 2.3 Yoda Conditions

Place the literal / constant on the **left** side of comparisons:

```cpp
// Good
if (false == is_escaped) { ... }
if (0 == wild_length) { ... }
if (nullptr != ctx.pattern) { ... }
if ('\\' == pattern[pattern_idx]) { ... }

// Bad
if (is_escaped == false) { ... }
if (wild_length == 0) { ... }
```

**Exception**: Do NOT use `true == condition`; only use `false == condition` for boolean negation.

### 2.4 Const Correctness

- Mark all non-reassigned local variables as `const`:
  ```cpp
  auto const haystack_length{haystack.length()};
  auto const* const str_end{str.cend()};
  ```
- All getter methods and non-mutating methods must be `const`.
- Do **not** use `const` on fundamental types in function **declarations** (clang-tidy:
  `readability-avoid-const-params-in-decls`):
  ```cpp
  // Good (declaration)
  auto process(size_t length) -> void;

  // Bad (declaration)
  auto process(const size_t length) -> void;
  ```
- Prefer `auto const` over `const auto`:
  ```cpp
  auto const result{compute()};  // Good
  const auto result{compute()};  // Bad
  ```

### 2.5 `[[nodiscard]]`

- Apply `[[nodiscard]]` to **all** functions that return a value.
- Only place `[[nodiscard]]` in the **declaration**, not in the definition (if separate).

### 2.6 Line Length

- Wrap code and comments at **100 characters**. Do not wrap earlier than 100 characters
  unnecessarily.

### 2.7 `else` After `return` / `throw`

Eliminate `else` branches when the preceding `if` block returns or throws:

```cpp
// Good
if (it == op_end()) {
    return nullptr;
}
return std::static_pointer_cast<Literal>(*it);

// Bad
if (it == op_end()) {
    return nullptr;
} else {
    return std::static_pointer_cast<Literal>(*it);
}
```

### 2.8 `'\n'` Over `std::endl`

```cpp
os << "\n";       // Good -- no unnecessary flush
os << std::endl;  // Bad
```

### 2.9 Structured Bindings

Use structured bindings instead of `.first` / `.second`:

```cpp
// Good
auto const& [original_key, projected_index]{map.at(col)};
for (auto const& [col, _] : projected_columns) { ... }

// Bad
auto const& pair{map.at(col)};
use(pair.first, pair.second);
```

### 2.10 `NOTE` and `TODO` Comments

- Use uppercase `NOTE:` (not `Note:`), consistent with `TODO:`.
- **Never leave `TODO` comments** in committed code -- open a GitHub issue instead and reference it:
  ```cpp
  // Issue: #1971
  ```

### 2.11 Anonymous Namespace for File-Local Helpers

Place file-local helper functions in an anonymous namespace, not as `private static` methods:

```cpp
// Good (in .cpp file)
namespace {
auto helper_function(int x) -> int { ... }
}  // namespace

// Bad
class Foo {
    static auto helper_function(int x) -> int;  // only used in .cpp
};
```

### 2.12 String Line Continuations

Place continuation operators at the **start** of the next line:

```cpp
// Good
return "Internal invariant violated during AST evaluation. This indicates a serious"
       " bug in the evaluation logic.";
```

---

## 3. Include Ordering

Include grouping, sorting, and regrouping are enforced by clang-format's `IncludeBlocks: Regroup`
and `IncludeCategories` settings. Refer to the authoritative
[`.clang-format`](https://github.com/y-scope/yscope-dev-utils/blob/main/exports/lint-configs/.clang-format)
config for the complete rule set.

The following rules are **not** enforced by tooling and must be checked during review:

- Project headers use **angle brackets** with the full project path (not relative `"../..."` paths):
  ```cpp
  // Good
  #include <clp/ErrorCode.hpp>
  #include <clp_s/ArchiveWriter.hpp>

  // Bad
  #include "../clp/ErrorCode.hpp"
  #include "ArchiveWriter.hpp"
  ```
- Only include what is **directly** needed -- do not rely on transitive includes.
- When adding a new external dependency, update the `.clang-format` config to register it as an
  external library header.

---

## 4. Header Guards

Use traditional `#ifndef` include guards (not `#pragma once`). The guard name mirrors the file path
in `UPPER_SNAKE_CASE`:

```cpp
#ifndef CLP_S_SEARCH_AST_VALUE_HPP
#define CLP_S_SEARCH_AST_VALUE_HPP

// ...

#endif  // CLP_S_SEARCH_AST_VALUE_HPP
```

---

## 5. Docstring Format

Use Doxygen-style `/**` block comments.

### 5.1 General Structure

```cpp
/**
 * Brief description of the function ending with a period.
 *
 * @param param_name Description of the parameter.
 * @param output_param Returns the computed value.
 * @return Description of return value.
 */
```

- Always insert a **blank `*` line** between the description and `@param` / `@return` tags.
- All descriptions, `@param`, `@return`, and `@throw` lines must end with a **period**.
- Do not indent continuation lines under `@param` / `@return` bullet points.
- Parameters whose meaning is obvious from the name alone (e.g., `@param reader`, `@param tag`) do
  **not** require a description -- listing just the name is sufficient. Only add a description when
  the parameter needs clarification beyond what the name conveys.

### 5.2 `@param` for Output Parameters

Use "Returns ..." phrasing for output reference parameters:

```cpp
/**
 * @param begin_pos_ref The beginning position of the last variable. Returns the beginning
 * position of the next variable.
 */
```

### 5.3 `@return` for `Result` Types

Follow this exact template:

```cpp
/**
 * @return A result containing the parsed timestamp on success, or an error code indicating the
 * failure:
 * - ErrorCodeEnum::IncompatibleTimestampPattern if no candidates match.
 * - Forwards `get_default_patterns`'s return values on failure.
 */
```

- For void results: `@return A void result on success, or an error code indicating the failure:`
- For abstract methods whose error codes depend on derived classes:
  `- Error codes are defined by the derived class.`
- List **direct errors before forwarded errors**.
- Do not use backticks around error code enum values in `@return` lists.
- Do not specify the full namespace if the error code is resolvable from the current namespace.

### 5.4 `@return` for `std::optional`

```cpp
/**
 * @return The integer value on success.
 * @return std::nullopt otherwise.
 */
```

Do not use backticks around `std::nullopt` in return statements.

### 5.5 `@return` for Boolean / "Whether"

Do not add "or not" in a "whether" return statement:

```cpp
// Good
@return Whether the value satisfies the filter.

// Bad
@return Whether the value satisfies the filter or not.
```

### 5.6 Class Docstrings

- Avoid starting with "Class for" or "This class is" -- these are redundant.
  - Good: `Handler for KV-pair IR stream search queries.`
  - Bad: `Class for handling KV-pair IR stream search queries.`
- When a class is designed to be used by a specific caller, mention it:
  - Good: `Virtual base class defining methods for deserializing IR units and log events called by
    \`Deserializer\`.`
- Enum value descriptions go as **inline comments above each value**, not in the class docstring.

### 5.7 Error Message Strings

- Do **not** capitalize the first character.
- Do **not** add a period at the end.
- Error messages should be general and match the error code name.

```cpp
// Good
"integer value exceeds the 64-bit signed integer range"

// Bad
"Integer value exceeds the 64-bit signed integer range."
```

### 5.8 Derived Class Override Docstrings

Derived class method overrides should **not** duplicate the base class's full docstring. Only
document what is specific to the override -- typically the concrete error codes:

```cpp
// Good -- only documents what's specific to this override
/**
 * The possible error codes:
 * - IrDeserializationErrorEnum::InvalidTag if the tag doesn't represent a valid IR unit.
 * - Forwards `deserialize_tag`'s return values on failure.
 */
[[nodiscard]] auto deserialize_ir_unit_type(ReaderInterface& reader)
        -> Result<IrUnitType> override;

// Bad -- duplicates the base class description
/**
 * Deserializes the type of the next IR unit from the given reader.
 * @param reader
 * @return A result containing the IR unit type on success, or an error code indicating the
 * failure:
 * - IrDeserializationErrorEnum::InvalidTag if the tag doesn't represent a valid IR unit.
 */
```

### 5.9 Function Name Accuracy in Doxygen

References to function names in Doxygen comments must use the **exact** function name. Do not
abbreviate or use an outdated name. If a method is named `deserialize_ir_unit_utc_offset_change`,
do not refer to it as `deserialize_utc_offset_change`.

### 5.10 Docstrings Must Stay in Sync

When parameters are added/removed, return codes change, or implementation changes, the docstring
**must** be updated accordingly in the same PR.

---

## 6. Class Design

### 6.1 Member Ordering

Within a class, follow this order:

1. **`public:`**
   - `// Types` (nested classes, type aliases, enums)
   - `// Factory methods` (static `create` functions)
   - `// Constructors`
   - `// Destructor`
   - `// Delete copy constructor and assignment operator` / `// Default move constructor and
     assignment operator`
   - `// Methods`
2. **`protected:`**
3. **`private:`**
   - `// Constructor` (private constructors)
   - `// Methods`
   - `// Variables`

In derived classes, label the override section as `// Methods implementing \`BaseClassName\``:

```cpp
public:
    // Methods implementing `DeserializerImpl`
    [[nodiscard]] auto deserialize_ir_unit_type(ReaderInterface& reader)
            -> Result<IrUnitType> override;
```

Static variables come before methods. Static methods come before constructors. Definition order
must match declaration order.

### 6.2 Rule of Five

Always be explicit about all five special member functions. Use labeled comments:

```cpp
// Delete copy constructor and assignment operator
Compressor(Compressor const&) = delete;
auto operator=(Compressor const&) -> Compressor& = delete;

// Default move constructor and assignment operator
Compressor(Compressor&&) noexcept = default;
auto operator=(Compressor&&) noexcept -> Compressor& = default;
```

For base classes that allow all operations:

```cpp
Value() = default;
Value(Value const&) = default;
auto operator=(Value const&) -> Value& = default;
Value(Value&&) = default;
auto operator=(Value&&) -> Value& = default;
virtual ~Value() = default;
```

**Abstract base classes**: Even abstract base classes should declare all five special members
explicitly -- clang-tidy flags missing declarations regardless of whether the class has pure virtual
methods. Typically: delete copy, default move, and add a virtual destructor:

```cpp
// Delete copy constructor and assignment operator
DeserializerImpl(DeserializerImpl const&) = delete;
auto operator=(DeserializerImpl const&) -> DeserializerImpl& = delete;

// Default move constructor and assignment operator
DeserializerImpl(DeserializerImpl&&) noexcept = default;
auto operator=(DeserializerImpl&&) noexcept -> DeserializerImpl& = default;

// Destructor
virtual ~DeserializerImpl() = default;
```

If a class appears to be an interface but has no pure virtual methods, flag it during review -- it
should either have at least one `= 0` method or follow the full Rule of Five.

### 6.3 Member Initialization at Declaration Site

Initialize members where they are declared, not in the constructor body:

```cpp
// Good
private:
    MetadataDBType m_metadata_db_type{MetadataDBType::SQLite};
    std::string m_metadata_db_host{"localhost"};
    int m_metadata_db_port{cDefaultMetadataDbPort};

// Bad -- initialization in constructor body
GlobalMetadataDBConfig()
    : m_metadata_db_type(MetadataDBType::SQLite),
      m_metadata_db_host("localhost"),
      m_metadata_db_port(3306) {}
```

### 6.4 Factory Function Pattern (Two-Phase Construction)

- Constructors must **not** throw exceptions.
- Make the constructor private and provide a static factory function returning
  `Result<ClassName>`:

```cpp
class ReadOnlyMemoryMappedFile {
public:
    [[nodiscard]] static auto create(std::string const& path)
            -> ystdlib::error_handling::Result<ReadOnlyMemoryMappedFile>;

private:
    ReadOnlyMemoryMappedFile(/* ... */);
};
```

### 6.5 Static Methods

If a method does not use `this`, make it `static`. Check clang-tidy warnings for
`readability-convert-member-functions-to-static`. Static methods should be placed before
constructors per the member ordering in section 6.1.

### 6.6 `explicit` on Single-Parameter Constructors

Always mark single-parameter constructors as `explicit` to prevent implicit conversions.

### 6.7 Structs vs. Classes

- Use `struct` when all members should be immutable (public `const` members).
- Avoid aggregate initialization; prefer constructors for predictable initialization.
- Do not use `const` or reference data members in classes (violates
  `cppcoreguidelines-avoid-const-or-ref-data-members`).

---

## 7. Error Handling

### 7.1 Result-Based Error Handling

- Functions that can fail should return `ystdlib::error_handling::Result<T>`.
- Use `YSTDLIB_ERROR_HANDLING_TRYX(expr)` for early-return on error:
  ```cpp
  auto const value{YSTDLIB_ERROR_HANDLING_TRYX(parse_value(input))};
  ```
- Use `.has_error()` to check results (not implicit bool conversion).

### 7.2 Error Code Enums

- The first enum value must start at **1** (not 0), to avoid false-success when cast to bool:
  ```cpp
  enum class ErrorCodeEnum : uint8_t {
      DuplicateKey = 1,
      InvalidFormat,
      // ...
  };
  ```
- Separate serialization and deserialization error enums into distinct types.
- Error code names must be precise: prefer `UnknownSchemaTreeNodeType` over
  `UnsupportedSchemaTreeNodeType` when the type is truly unknown (not just unsupported).

### 7.3 `std::errc` for errno-Based Errors

```cpp
return static_cast<std::errc>(errno);
```

### 7.4 Error Log Message Format

```cpp
// Format: "Failed to <action> - (<error_value>) <error_message>"
SPDLOG_ERROR("Failed to create directory \"{}\" - ({}) {}", path, errno, strerror(errno));

// For std::error_code:
SPDLOG_ERROR("Failed to ... - ({}) {}", error.category().name(), error.message());
```

### 7.5 Do Not Log Inside Library Classes

Leave logging to the caller. Library code should return errors, not log them.

### 7.6 Exception Classes

Use nested `OperationFailed` classes inheriting from `TraceableException`:

```cpp
class OperationFailed : public TraceableException {
public:
    OperationFailed(ErrorCode error_code, char const* const filename, int line_number)
            : TraceableException{error_code, filename, line_number} {}

    [[nodiscard]] auto what() const noexcept -> char const* override {
        return "streaming_compression::Compressor operation failed";
    }
};
```

Throw with `__FILENAME__` and `__LINE__`:

```cpp
throw OperationFailed(ErrorCode_NotInit, __FILENAME__, __LINE__);
```

---

## 8. Modern C++ Best Practices

### 8.1 `std::string_view` Over `std::string const&`

For read-only string parameters that are not stored:

```cpp
// Good
auto find_first_of(std::string_view haystack, char const* needles) -> size_t;

// Bad
auto find_first_of(std::string const& haystack, char const* needles) -> size_t;
```

### 8.2 `constexpr std::string_view` for Compile-Time Strings

```cpp
// Good
constexpr std::string_view cDefaultHost{"localhost"};

// Bad
static std::string const cDefaultHost{"localhost"};
```

### 8.3 `constexpr std::array` for Compile-Time Arrays

```cpp
constexpr std::array<std::string_view, 3> cOptions{"a", "b", "c"};
```

### 8.4 Prefer Standard Algorithms Over Raw Loops

```cpp
// Good
std::ranges::find_if(entries, [](auto const& e) { return e.matches(); });
std::ranges::any_of(values, pred);
std::ranges::equal(a, b);

// Bad -- manual iteration
for (auto it = entries.begin(); it != entries.end(); ++it) {
    if (it->matches()) return it;
}
```

### 8.5 `emplace_back` / `emplace` Over `push_back` / `insert`

Use `emplace` variants for non-fundamental types to avoid unnecessary copies:

```cpp
// Good
container.emplace_back(arg1, arg2);
map.try_emplace(key, value);

// Acceptable for fundamental types
vec.push_back(42);
```

### 8.6 `std::optional` Over Boolean Flag + Data

```cpp
// Good
std::optional<std::pair<size_t, int>> m_timezone_info;

// Bad
bool m_has_timezone_info{false};
size_t m_timezone_size{0};
int m_timezone_offset{0};
```

Use `emplace` to set optional values:

```cpp
m_timezone_info.emplace(size, offset);
```

### 8.7 `std::filesystem::path` for Path Construction

```cpp
// Good
auto const output_path{std::filesystem::path{output_dir} / "result.json"};

// Bad
auto const output_path{output_dir + "/result.json"};
```

### 8.8 `find` Over `contains` + `at` for Map Lookups

```cpp
// Good -- single hash lookup
if (auto const it{map.find(key)}; it != map.end()) {
    use(it->second);
}

// Bad -- two hash lookups
if (map.contains(key)) {
    use(map.at(key));
}
```

### 8.9 Reserve Container Capacity

```cpp
encoded_vars.reserve(entries.size());
```

### 8.10 `static_cast` Over `reinterpret_cast`

Prefer `static_cast` whenever safe. Use `static_cast<bool>(std::isdigit(c))` for explicit
int-to-bool conversion.

### 8.11 `switch` for Enum Dispatch

Use `switch` statements instead of `if/else if` chains when dispatching on enum values.

### 8.12 Output Parameters Go Last

```cpp
// Good
auto serialize(InputType input, OutputType& output) -> Result<void>;

// Bad
auto serialize(OutputType& output, InputType input) -> Result<void>;
```

### 8.13 `[[maybe_unused]]` for Unused Parameters

```cpp
[[nodiscard]] auto try_seek_from_begin([[maybe_unused]] size_t pos) -> ErrorCode override {
    return ErrorCode_Unsupported;
}
```

### 8.14 Using Declarations -- Specific, Not Whole Namespaces

```cpp
// Good
using antlr4::ANTLRInputStream;
using antlr4::CommonTokenStream;

// Bad
using namespace antlr4;
```

### 8.15 Declare Variables Close to First Use

Minimize the scope of variables by declaring them as close as possible to their first use.

---

## 9. clang-tidy Compliance

### 9.1 NOLINT Scoping

- Prefer `// NOLINTNEXTLINE(rule-name)` scoped directly above the violating line.
- Only use `// NOLINTBEGIN` / `// NOLINTEND` when multiple consecutive lines violate the same
  rule.
- Always specify the exact rule name(s) being suppressed.
- Add a comment explaining **why** the suppression is necessary.

### 9.2 All New Files Must Be clang-tidy Clean

Address all clang-tidy violations in newly added files.

### 9.3 Common Violations to Watch For

- `readability-avoid-const-params-in-decls` -- `const` on fundamental types in declarations.
- `cppcoreguidelines-special-member-functions` -- missing deleted/defaulted special members.
- `readability-identifier-naming` -- naming convention violations.
- `cppcoreguidelines-avoid-const-or-ref-data-members` -- `const` or reference class members.
- `readability-convert-member-functions-to-static` -- methods that don't use `this`.

---

## 10. Testing Conventions

- Use `REQUIRE_FALSE(expr)` instead of `REQUIRE(!expr)`.
- Use `REQUIRE((x <op> y))` with extra parentheses for complex comparison operators.
- Use `GENERATE` for parameterized tests where applicable.
- Individual `REQUIRE` assertions are preferred over aggregating booleans.
- Test file naming: `test-<component>-<feature>.cpp` with hyphens.
- Test case naming: `"component-feature-scenario"` with hyphens and `[tag]` groups.
- Use long-form CLI flags in test commands for readability.

---

## 11. PR Conventions

### 11.1 PR Title Format

```
<type>(<scope>): <imperative description> (fixes #NNN).
```

- **Types**: `feat`, `fix`, `refactor`, `test`, `build`, `chore`, `docs`, `style`, `perf`,
  `revert`.
- **Scope**: Use component names like `core`, `clp-s`, `kv-ir`, `clp` (not granular namespaces).
- Always end the title with a **period**.
- Reference related issues: `(fixes #NNN)` or `(resolves #NNN)` before the period.
- Use backticks around specific class/function names in titles.
- Multi-line descriptions for PRs with multiple changes:
  ```
  feat(kv-ir): Improve error handling in `clp::ffi::ir_stream::Serializer`:

  - Add specific error codes for serialization failures.
  - Update docstrings to follow the Result return format.
  ```

### 11.2 PR Scope Discipline

- Keep PRs focused on their stated scope. Do not touch unrelated files.
- PR descriptions must be updated to reflect the latest code changes.

### 11.3 Commit Messages

- Follow the same conventional commit format as PR titles.
- Use multi-line messages when introducing multiple logically distinct changes.
