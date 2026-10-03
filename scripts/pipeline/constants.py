"""Constants for VN Invest pipeline orchestration."""

import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GENERATED_DIR = os.path.join(ROOT_DIR, "generated")
SCHEMA_PATH = os.path.join(ROOT_DIR, "schemas", "recommendations.schema.json")
PERFORMANCE_SCHEMA_PATH = os.path.join(ROOT_DIR, "schemas", "performance.schema.json")

__all__ = [
    "GENERATED_DIR",
    "PERFORMANCE_SCHEMA_PATH",
    "ROOT_DIR",
    "SCHEMA_PATH",
]
