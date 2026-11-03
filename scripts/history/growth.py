"""Lightweight data growth monitoring and storage metrics."""

import logging
import os
from dataclasses import dataclass

from scripts.artifacts.manifest import load_history_index
from scripts.artifacts.transaction import GENERATED_DIR, ROOT_DIR
from scripts.history.models import HistoryDirectoryConventions

logger = logging.getLogger(__name__)


def _get_directory_size_bytes(dir_path: str) -> int:
    """Calculate total size of all files in directory in bytes."""
    total = 0
    if not os.path.exists(dir_path):
        return 0
    for root, _, files in os.walk(dir_path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def _count_lines_in_dir(dir_path: str, extension: str = ".jsonl") -> int:
    """Count lines across all files with specific extension in a directory tree."""
    count = 0
    if not os.path.exists(dir_path):
        return 0
    for root, _, files in os.walk(dir_path):
        for f in files:
            if f.endswith(extension):
                fp = os.path.join(root, f)
                try:
                    with open(fp, "r", encoding="utf-8") as fl:
                        count += sum(1 for line in fl if line.strip())
                except OSError:
                    pass
    return count


def _get_git_repo_size_bytes(repo_root: str) -> int | None:
    """Attempt to get .git directory size in bytes."""
    git_dir = os.path.join(repo_root, ".git")
    if os.path.exists(git_dir):
        return _get_directory_size_bytes(git_dir)
    return None


@dataclass(frozen=True)
class DataGrowthMetrics:
    """Summary of storage metrics for VN Invest artifacts and git repository."""

    generated_dir_bytes: int
    git_dir_bytes: int | None
    retained_reports_count: int
    recommendation_ledger_entries_count: int
    run_manifest_entries_count: int
    evaluation_entries_count: int

    def to_dict(self) -> dict:
        return {
            "generated_dir_bytes": self.generated_dir_bytes,
            "generated_dir_mb": round(self.generated_dir_bytes / (1024 * 1024), 2),
            "git_dir_bytes": self.git_dir_bytes,
            "git_dir_mb": round(self.git_dir_bytes / (1024 * 1024), 2)
            if self.git_dir_bytes is not None
            else None,
            "retained_reports_count": self.retained_reports_count,
            "recommendation_ledger_entries_count": self.recommendation_ledger_entries_count,
            "run_manifest_entries_count": self.run_manifest_entries_count,
            "evaluation_entries_count": self.evaluation_entries_count,
        }


def check_data_growth(
    generated_dir: str | None = None, repo_root: str | None = None
) -> DataGrowthMetrics:
    """Compute current storage usage and record counts."""
    g_dir = os.path.abspath(generated_dir or GENERATED_DIR)
    r_root = os.path.abspath(repo_root or ROOT_DIR)
    conventions = HistoryDirectoryConventions(g_dir)

    idx_data = load_history_index(conventions.history_index_path)
    retained_reports = len(idx_data.get("dates", []))

    ledger_count = _count_lines_in_dir(conventions.recommendation_ledger_dir, ".jsonl")
    manifest_count = _count_lines_in_dir(conventions.run_manifest_dir, ".jsonl")
    evaluation_count = _count_lines_in_dir(conventions.evaluations_dir, ".jsonl")

    gen_size = _get_directory_size_bytes(g_dir)
    git_size = _get_git_repo_size_bytes(r_root)

    return DataGrowthMetrics(
        generated_dir_bytes=gen_size,
        git_dir_bytes=git_size,
        retained_reports_count=retained_reports,
        recommendation_ledger_entries_count=ledger_count,
        run_manifest_entries_count=manifest_count,
        evaluation_entries_count=evaluation_count,
    )


__all__ = [
    "DataGrowthMetrics",
    "check_data_growth",
]
