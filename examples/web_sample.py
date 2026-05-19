#!/usr/bin/env python3
"""
PyPoe Web Interface Example

This script demonstrates how to run the PyPoe web interface programmatically.
"""

import asyncio
import os
from pathlib import Path
import sys

try:
    from pypoe.core.config import get_config
    from pypoe.interfaces.web.app import run_server
    from pypoe.interfaces.web import WEB_AVAILABLE
except ImportError as e:
    print(f"Error importing pypoe: {e}")
    print("Make sure you have installed pypoe with: pip install pypoe[web-ui]")
    sys.exit(1)

def main():
    """Run the web interface example."""
    
    if not WEB_AVAILABLE:
        print("Web UI dependencies not installed!")
        print("Please install with: pip install -e '.[web-ui]'")
        print("Or install everything: pip install -e '.[all]'")
        return
    
    print("PyPoe Web Interface Example")
    print("=" * 40)
    
    # Check if POE_API_KEY is set
    if not os.getenv('POE_API_KEY'):
        print("POE_API_KEY not found in environment")
        print("Please set your POE API key:")
        print("  export POE_API_KEY='your-api-key-here'")
        print("Get your key from: https://poe.com/api_key")
        return
    
    try:
        # Get configuration
        config = get_config()
        print(f"Configuration loaded")
        print(f"Database path: {config.database_path}")
        
        # Ensure database directory exists
        db_dir = Path(config.database_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        print(f"Database directory: {db_dir}")
        
        print()
        print("Starting web server...")
        print("Open your browser to: http://localhost:8000")
        print("Press Ctrl+C to stop")
        print("-" * 40)
        
        # Run the web server
        run_server(host="0.0.0.0", port=8000, config=config)
        
    except ValueError as e:
        print(f"Configuration error: {e}")
        print("Please check your environment setup.")
    except KeyboardInterrupt:
        print("\nWeb server stopped by user.")
    except Exception as e:
        print(f"Error starting web server: {e}")

if __name__ == "__main__":
    main() 