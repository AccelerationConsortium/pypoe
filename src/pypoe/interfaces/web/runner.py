#!/usr/bin/env python3
"""
PyPoe Web Interface Runner

A simple script to run the PyPoe web interface.
"""

import sys
from pathlib import Path

# Check if web dependencies are available
try:
    from .app import run_server, WEB_AVAILABLE
    from ...core.config import get_config, Config
except ImportError:
    WEB_AVAILABLE = False
    run_server = None
    Config = None

def run_web_server(host: str, port: int, config: Config):
    """Runs the web server."""
    if not WEB_AVAILABLE:
        print("Web UI dependencies not installed!")
        print("Please install with: pip install -e '.[web-ui]'")
        print("Or install everything: pip install -e '.[all]'")
        sys.exit(1)
    
    try:
        # Run the server
        run_server(host=host, port=port, config=config)
        
    except KeyboardInterrupt:
        print("\nWeb server stopped.")
        sys.exit(0)
    except Exception as e:
        print(f"Error starting web server: {e}")
        sys.exit(1)

def main():
    """Main function to run the web server."""
    from ...core.config import get_config
    
    if not WEB_AVAILABLE:
        print("Web UI dependencies not installed!")
        print("Please install with: pip install -e '.[web-ui]'")
        print("Or install everything: pip install -e '.[all]'")
        return 1
    
    print("Starting PyPoe Web Interface...")
    print("Make sure you have:")
    print("   - POE_API_KEY set in your environment or .env file")
    print("   - Get your API key from: https://poe.com/api_key")
    print()
    
    try:
        config = get_config()
        print("Configuration loaded successfully")
        print(f"Database: {config.database_path}")
        if config.web_username:
            print("Web interface is password protected")
        print()
        print("Starting web server...")
        print("   - Local: http://localhost:8000")
        print("   - Network: http://0.0.0.0:8000")
        print()
        print("Press Ctrl+C to stop the server")
        print("=" * 50)
        
        # Run the server
        run_server(host="0.0.0.0", port=8000, config=config)
        
    except ValueError as e:
        print(f"Configuration error: {e}")
        print("Please check your environment setup.")
        return 1
    except KeyboardInterrupt:
        print("\nWeb server stopped.")
        return 0
    except Exception as e:
        print(f"Error starting web server: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 