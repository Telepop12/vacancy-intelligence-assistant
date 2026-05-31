"""
Output lifecycle management.

Policy:
  - Keep at most MAX_OUTPUT_FILES pairs (md + json) in output/.
  - Oldest files are removed first (by mtime).
  - registry.csv is never deleted.
  - .gitkeep is never deleted.

Call cleanup_output_dir() after each analysis to enforce the policy.
"""
from __future__ import annotations

from pathlib import Path

MAX_OUTPUT_FILES = 50  # pairs, i.e. up to 100 actual files (50 md + 50 json)

_PROTECTED = {"registry.csv", ".gitkeep"}


def cleanup_output_dir(output_dir: Path, max_pairs: int = MAX_OUTPUT_FILES) -> int:
    """
    Remove oldest analysis pairs (md + json) if count exceeds max_pairs.

    Returns number of files deleted.
    """
    output_dir = Path(output_dir)
    if not output_dir.exists():
        return 0

    md_files = sorted(
        [f for f in output_dir.glob("analysis_*.md") if f.name not in _PROTECTED],
        key=lambda f: f.stat().st_mtime,
    )

    deleted = 0
    while len(md_files) > max_pairs:
        oldest_md = md_files.pop(0)
        oldest_json = oldest_md.with_suffix(".json")
        try:
            oldest_md.unlink(missing_ok=True)
            deleted += 1
        except OSError:
            pass
        try:
            oldest_json.unlink(missing_ok=True)
            deleted += 1
        except OSError:
            pass

    return deleted
