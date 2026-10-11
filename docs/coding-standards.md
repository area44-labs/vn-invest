# Python Coding Standards & Project Conventions

This document specifies the practical Python coding standards, design patterns, and engineering conventions enforced across **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Purpose & When to Consult

Consult this document before writing, refactoring, or reviewing Python code in `scripts/`.

---

## 2. Environment & Tooling

- **Python Requirements**: `>= 3.14` managed deterministically via `uv`.
- **Dependency Source of Truth**: `pyproject.toml` and `uv.lock`.
- **Execution Command**: All Python scripts and tests run via `uv run --frozen ...`.

---

## 3. Typing & Model Standards

### 3.1 Explicit Type Annotations

- All production functions, methods, and class attributes must have explicit type annotations.
- Use standard library generic types (`list[str]`, `dict[str, Any]`, `tuple[int, ...]`, `set[str]`).

### 3.2 Domain Models & Frozen Dataclasses

- Domain contracts and configuration models are implemented as immutable dataclasses using `@dataclass(frozen=True)`.
- Use `FrozenDict` (from `scripts.quant.config`) for nested dictionary fields inside frozen dataclasses to support deep immutability and `copy.deepcopy`.

### 3.3 Mutation Isolation (`.to_dict()`)

- Dataclasses and result containers that serialize to JSON must provide a `.to_dict()` method returning detached, deep copies of internal collections to prevent caller mutation leaks.

---

## 4. Exception Handling & Fail-Closed Principles

- **Custom Exceptions**: Inherit from domain-specific base exceptions (`AcquisitionError`, `CanonicalOHLCVError`, `SchemaResolutionError`).
- **Fail-Closed Strategy**: When data quality checks fail or external provider limits are exceeded, do not synthesize default values or fake numbers. Return `None`, set status to `INSUFFICIENT`, or raise an explicit error.
- **Artifact Protection**: In update mode (`--update`), data failures raise `RuntimeError` to abort report generation without modifying existing files in `generated/`.

---

## 5. Formatting & Imports

- **Linter & Formatter**: Enforced via Ruff (`astral-sh/ruff`):
  ```bash
  uv run --frozen ruff check --fix scripts
  uv run --frozen ruff format scripts
  ```
- **Import Block Order**:
  1. Standard library imports
  2. Third-party imports (`pandas`, `numpy`, `pytest`)
  3. Internal package imports (`scripts.domain`, `scripts.quant`)
- **No Wildcard Imports**: `from module import *` is prohibited. Use explicit imports.
