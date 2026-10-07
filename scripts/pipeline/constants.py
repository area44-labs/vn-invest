"""Constants for VN Invest pipeline orchestration."""

import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GENERATED_DIR = os.path.join(ROOT_DIR, "generated")
SCHEMA_PATH = os.path.join(ROOT_DIR, "schemas", "v2", "recommendations.schema.json")
PERFORMANCE_SCHEMA_PATH = os.path.join(ROOT_DIR, "schemas", "v2", "performance.schema.json")

# Canonical Pipeline Software Implementation Version
PIPELINE_VERSION = "2.0.0"

# Production Update Provider Throttle Configuration
DEFAULT_UPDATE_THROTTLE_DELAY = 3.5

__all__ = [
    "DEFAULT_UPDATE_THROTTLE_DELAY",
    "GENERATED_DIR",
    "PERFORMANCE_SCHEMA_PATH",
    "PIPELINE_VERSION",
    "ROOT_DIR",
    "SCHEMA_PATH",
]
