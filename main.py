"""Root entry point for LeadForge API and CLI.

Allows starting the server with `uvicorn main:app --reload`
or running the pipeline via `python main.py <city> <category>`.
"""

import sys
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Expose FastAPI app for Uvicorn (e.g. `uvicorn main:app --reload`)
from leadforge.server import app  # noqa: F401
from leadforge.main import main as cli_main

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        import uvicorn
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
    else:
        cli_main()
