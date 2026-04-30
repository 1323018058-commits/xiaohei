from __future__ import annotations

import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[3] / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from src.platform.db.session import apply_sql_directory


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python packages/db/scripts/apply_dir.py <sql-directory>")
    apply_sql_directory(Path(sys.argv[1]))


if __name__ == "__main__":
    main()
