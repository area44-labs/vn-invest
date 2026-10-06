"""Constants for VN Invest pipeline orchestration."""

import os

from scripts.artifacts.provenance import SCHEMA_VERSION

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GENERATED_DIR = os.path.join(ROOT_DIR, "generated")
SCHEMA_PATH = os.path.join(ROOT_DIR, "schemas", "recommendations.schema.json")
PERFORMANCE_SCHEMA_PATH = os.path.join(ROOT_DIR, "schemas", "performance.schema.json")

# Canonical Pipeline Software Implementation Version
PIPELINE_VERSION = "2.0.0"

__all__ = [
    "GENERATED_DIR",
    "PERFORMANCE_SCHEMA_PATH",
    "PIPELINE_VERSION",
    "ROOT_DIR",
    "SCHEMA_PATH",
    "SCHEMA_VERSION",
]
