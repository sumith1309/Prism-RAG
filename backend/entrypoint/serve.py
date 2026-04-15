"""Launch the FastAPI server.

Usage:
    python -m entrypoint.serve
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn


def main() -> None:
    import os
    port = int(os.environ.get("PORT", "8765"))
    reload = os.environ.get("RELOAD", "0") == "1"
    uvicorn.run("src.api.app:app", host="127.0.0.1", port=port, reload=reload)


if __name__ == "__main__":
    main()
