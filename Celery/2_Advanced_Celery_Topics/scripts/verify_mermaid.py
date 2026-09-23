#!/usr/bin/env python3
"""Mermaid diagram validation harness for documentation files.

Validates that all Mermaid diagrams (flowcharts, sequence diagrams, state diagrams,
class diagrams, er diagrams) within Markdown documentation files conform to official
Mermaid syntax rules and render without errors.

Usage:
    python scripts/verify_mermaid.py
    python scripts/verify_mermaid.py docs/ARCHITECTURE_AND_STANDARDS.md
    python scripts/verify_mermaid.py 03_routing_and_capacity/
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MJS_SCRIPT = REPO_ROOT / "scripts" / "verify_mermaid.mjs"


def main() -> int:
    """Execute the Node-based Mermaid syntax verification script."""
    cmd = ["node", str(MJS_SCRIPT)] + sys.argv[1:]
    try:
        result = subprocess.run(cmd, cwd=str(REPO_ROOT))
        return result.returncode
    except FileNotFoundError:
        print("ERROR: 'node' executable not found on PATH. Node.js is required to validate Mermaid diagrams.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
