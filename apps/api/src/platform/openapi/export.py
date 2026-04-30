import json
import sys
from pathlib import Path


def main() -> None:
    api_root = Path(__file__).resolve().parents[3]
    repo_root = api_root.parent.parent
    output_path = repo_root / "packages" / "generated" / "openapi.json"

    sys.path.insert(0, str(api_root))

    from api_main import app

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"OpenAPI exported to {output_path}")


if __name__ == "__main__":
    main()
