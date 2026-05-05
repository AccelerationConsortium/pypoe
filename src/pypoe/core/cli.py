#!/usr/bin/env python3
"""
PyPoe CLI Entry Point

Main command-line interface for PyPoe.
"""

import asyncio
import argparse
import sys

def create_main_parser():
    """Create the main argument parser."""
    parser = argparse.ArgumentParser(
        prog='pypoe',
        description='PyPoe - Command Line Interface for Poe.com Chat',
        formatter_class=argparse.RawDescriptionHelpFormatter,
                 epilog="""
Available Interfaces:
  web     - Start web interface interactively (browser-based UI)
  cli     - Interactive command-line chat interface  
  slack   - Start Slack bot interactively
  
Examples:
  # Interactive Usage (foreground)
  pypoe web                     # Start web interface at http://localhost:8000
  pypoe web --host 0.0.0.0      # Start web interface on all interfaces
  pypoe slack                   # Start Slack bot interactively
  
  # CLI Usage  
  pypoe cli chat                # Start new CLI chat
  pypoe cli list                # List all conversations  
  pypoe cli select              # Interactive conversation browser
  pypoe cli show --conv-id XXX  # Show conversation history

Background services:
  Use systemd to keep pypoe web and pypoe slack running after logout.
  
Quick Start:
  1. Web interface:      pypoe web
  2. CLI interface:      pypoe cli select  
  3. Slack bot:          pypoe slack
        """
    )
    
    subparsers = parser.add_subparsers(dest='interface', help='Interface to use')
    
    # Web interface (default)
    web_parser = subparsers.add_parser('web', help='Start web interface')
    web_parser.add_argument('--host', default='127.0.0.1', help='Host to bind to')
    web_parser.add_argument('--port', type=int, default=8000, help='Port to bind to')
    
    # CLI interface
    cli_parser = subparsers.add_parser('cli', help='Interactive CLI interface')
    cli_subparsers = cli_parser.add_subparsers(dest='cli_command', help='CLI commands')
    
    # Add CLI subcommands
    cli_subparsers.add_parser('chat', help='Start or continue a chat')
    cli_subparsers.add_parser('list', help='List all conversations') 
    cli_subparsers.add_parser('select', help='Interactive conversation selection')
    cli_subparsers.add_parser('show', help='Show conversation history')
    cli_subparsers.add_parser('delete', help='Delete a conversation')
    
    # Slack interface (interactive)
    slack_parser = subparsers.add_parser('slack', help='Start Slack bot interactively')
    
    return parser

def run_web_interface(host: str = '127.0.0.1', port: int = 8000):
    """Run the web interface."""
    try:
        from ..interfaces.web.runner import run_web_server
        from .config import get_config
        config = get_config()
        # Note: run_web_server is synchronous, not async
        run_web_server(host=host, port=port, config=config)
    except ImportError as e:
        print(f"❌ Web interface not available: {e}")
        print("💡 Install web dependencies: pip install -e '.[web-ui]'")
        sys.exit(1)

async def run_cli_interface(args):
    """Run the CLI interface."""
    try:
        from ..interfaces.cli.app import main as cli_main

        # If no CLI command specified, default to interactive select
        if not args.cli_command:
            sys.argv = ['pypoe-cli', 'select']
        else:
            # Reconstruct argv for CLI
            sys.argv = ['pypoe-cli', args.cli_command]

        await cli_main()
    except ImportError as e:
        print(f"❌ CLI interface not available: {e}")
        sys.exit(1)

async def run_slack_interface():
    """Run the Slack interface."""
    try:
        from ..interfaces.slack.bot import main as slack_main
        await slack_main()
    except ImportError as e:
        print(f"❌ Slack interface not available: {e}")
        print("💡 Install Slack dependencies: pip install -e '.[web-ui]'")
        sys.exit(1)

def main():
    """Main entry point."""
    parser = create_main_parser()
    args = parser.parse_args()
    
    # If no interface specified, show help
    if not args.interface:
        parser.print_help()
        return
    
    try:
        if args.interface == 'web':
            # Web interface is synchronous, not async
            run_web_interface(getattr(args, 'host', '127.0.0.1'), getattr(args, 'port', 8000))
        elif args.interface == 'cli':
            # CLI interface is async, so run it in asyncio
            asyncio.run(run_cli_interface(args))
        elif args.interface == 'slack':
            # Slack interface is async, so run it in asyncio
            asyncio.run(run_slack_interface())
        else:
            parser.print_help()
            
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

def run():
    """Entry point for console scripts."""
    main()

if __name__ == "__main__":
    run()