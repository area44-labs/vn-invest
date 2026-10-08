# Python Coding Standards & Project Conventions

This document specifies the practical Python coding standards, design patterns, and engineering conventions enforced across **VN Invest** (`area44-labs/vn-invest`).

---

## 1. Environment & Language Baseline

- **Python Version**: `>= 3.14` (managed deterministically via `uv`).
- **Dependency Source of Truth**: `pyproject.toml` and `uv.lock`.
- **Package Management**: All Python commands must run via `uv run --frozen ...`.

---

## 2. Typing & Data Structure Standards

### 2.1 Type Annotations
- All production functions, methods, and class attributes must have explicit type annotations.
- Use native standard library generic types (`list[str]`, `dict[str, Any]`, `tuple[int, ...]`, `set[str]`) available in Python 3.9+.
- Use `typing.Optional` or `X | None` for optional fields.
- Avoid using `Any` unless interfacing with raw, untyped JSON or external library return values.

### 2.2 Domain Models & Frozen Dataclasses
- Domain contracts and configuration models must be implemented as immutable dataclasses using `@dataclass(frozen=True)`:
  ```python
  from dataclasses import dataclass

  @dataclass(frozen=True)
  class UniverseCandidate:
      symbol: str
      company_name: str
      sector: str
      exchange: str
  ```
- Use `FrozenDict` (from `scripts.quant.config`) for nested dictionary fields inside frozen dataclasses (e.g. `QuantConfig`) to prevent nested mutation while remaining JSON-serializable and supporting `copy.deepcopy`.

### 2.3 Serialization & Mutation Isolation (`.to_dict()`)
- Dataclasses and result containers that serialize to JSON must provide a `.to_dict()` method.
- `.to_dict()` methods must return **detached, deep copies** of internal collections (lists, dicts, nested dataclasses) to prevent caller mutation leaks:
  ```python
  def to_dict(self) -> dict[str, Any]:
      return {
          "symbol": self.symbol,
          "parameters": dict(self.parameters),
          "evaluations": [e.to_dict() for e in self.evaluations],
      }
  ```

---

## 3. Error Handling & Fail-Closed Principles

### 3.1 Exception Hierarchy
Custom exceptions must inherit from domain-specific base exceptions:
- Market Data Exceptions: `AcquisitionError`, `InvalidSymbolError`, `ExplicitlyInvalidDataError`, `ProviderRateLimitError` (in `scripts/data/providers/base.py`).
- Data Validation Exceptions: `CanonicalOHLCVError` (in `scripts/data/validation.py`).
- Schema Exceptions: `SchemaResolutionError` (in `scripts/schema/registry.py`).

### 3.2 Fail-Closed Principle
When data quality fails or provider limits are exceeded:
- Do **not** silently fill missing values with zeros or synthetic numbers.
- Return `None`, mark status as `INSUFFICIENT` or `EXPLICITLY_INVALID`, or raise an explicit exception.
- In production update mode (`--update`), data failures must raise `RuntimeError` to abort report generation without overwriting existing on-disk report artifacts in `generated/`.

---

## 4. Import & Dependency Rules

### 4.1 Grouping & Ordering
Imports must be structured into three distinct blocks separated by single blank lines:
1. Standard library imports
2. Third-party library imports (`pandas`, `numpy`, `pytest`, etc.)
3. Project canonical package imports (`scripts.domain`, `scripts.quant`, etc.)

```python
import logging
from typing import Any

import numpy as np
import pandas as pd

from scripts.domain.universe import Universe
from scripts.quant.config import DEFAULT_QUANT_CONFIG
```

### 4.2 Explicit Imports
- Wildcard imports (`from module import *`) are strictly prohibited.
- Absolute imports using canonical package roots (`from scripts.quant.signal import compute_signal`) are required.
- Do not import from removed `scripts.lib/*` modules.

---

## 5. Formatting & Linting Rules

- **Linter & Formatter**: Ruff (`astral-sh/ruff`).
- **Formatting Standard**: Enforced automatically via:
  ```bash
  uv run --frozen ruff check --fix scripts
  uv run --frozen ruff format scripts
  ```
- Line length, code formatting, and unused import cleanup are managed directly by Ruff rules defined in `pyproject.toml`.

---

## 6. Docstrings & Comments

- **Module Docstrings**: Every Python module should contain a top-level docstring stating its canonical responsibility.
- **Function Docstrings**: Use concise Google-style or standard Python docstrings specifying purpose, non-obvious parameters, return types, and raised exceptions.
- **Financial & Quantitative Notes**: Document mathematical logic, formula definitions, or market rules (e.g., Vietnam T+2.5 settlement cycle, floor/ceiling price calculation rules) directly in function docstrings where applicable.
