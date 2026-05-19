#!/usr/bin/env python3
"""
PyPoe CLI Runner

Entry point for the PyPoe CLI interface.
Can be run directly or used as a module.
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to the path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from pypoe.interfaces.cli.app import main

def run_cli():
    """Run the CLI interface."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nGoodbye!")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_cli() 