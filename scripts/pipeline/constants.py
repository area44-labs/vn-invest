"""Constants for VN Invest pipeline orchestration."""

import os

from scripts.schema import SCHEMA_VERSION, get_registered_schema_path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GENERATED_DIR = os.path.join(ROOT_DIR, "generated")
SCHEMA_PATH = get_registered_schema_path("recommendations", SCHEMA_VERSION)
PERFORMANCE_SCHEMA_PATH = get_registered_schema_path("performance", SCHEMA_VERSION)

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
