#!/usr/bin/env python3
"""
PyPoe CLI Entry Point

Main command-line interface for PyPoe.
"""

import asyncio
import argparse
import sys
from pathlib import Path

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
  daemon  - Manage PyPoe services as background daemons
  
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
  
  # Daemon/Service Usage (background)
  pypoe daemon web start        # Start web server as background service
  pypoe daemon web status       # Check web server status
  pypoe daemon web stop         # Stop web server service
  pypoe daemon slack start      # Start Slack bot as background service
  pypoe daemon slack logs       # View Slack bot logs

Difference between modes:
  - pypoe web          -> Runs in foreground, stops when you close terminal
  - pypoe daemon web   -> Runs in background, keeps running after you close terminal
  
Quick Start:
  1. Web interface:      pypoe web
  2. CLI interface:      pypoe cli select  
  3. Background service: pypoe daemon web start
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
    
    # Daemon management interface
    daemon_parser = subparsers.add_parser('daemon', help='Manage PyPoe services as daemons')
    daemon_subparsers = daemon_parser.add_subparsers(dest='daemon_command', help='Daemon commands')
    
    # Web daemon commands
    web_daemon_parser = daemon_subparsers.add_parser('web', help='Manage web server daemon')
    web_daemon_subparsers = web_daemon_parser.add_subparsers(dest='web_daemon_action', help='Web daemon actions')
    web_daemon_subparsers.add_parser('start', help='Start web server as daemon')
    web_daemon_subparsers.add_parser('stop', help='Stop web server daemon')
    web_daemon_subparsers.add_parser('restart', help='Restart web server daemon')
    web_daemon_subparsers.add_parser('status', help='Check web server daemon status')
    web_daemon_subparsers.add_parser('logs', help='View web server daemon logs')
    
    # Slack daemon commands
    slack_daemon_parser = daemon_subparsers.add_parser('slack', help='Manage Slack bot daemon')
    slack_daemon_subparsers = slack_daemon_parser.add_subparsers(dest='slack_daemon_action', help='Slack daemon actions')
    slack_daemon_subparsers.add_parser('start', help='Start Slack bot as daemon')
    slack_daemon_subparsers.add_parser('stop', help='Stop Slack bot daemon')
    slack_daemon_subparsers.add_parser('restart', help='Restart Slack bot daemon')
    slack_daemon_subparsers.add_parser('status', help='Check Slack bot daemon status')
    slack_daemon_subparsers.add_parser('logs', help='View Slack bot daemon logs')
    
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

def run_daemon_command(args):
    """Run daemon management commands."""
    try:
        if args.daemon_command == 'web':
            from ..scripts.setup.run_pypoe_daemon import (
                start_daemon, stop_daemon, restart_daemon,
                status_daemon, show_logs
            )
            
            if args.web_daemon_action == 'start':
                start_daemon()
            elif args.web_daemon_action == 'stop':
                stop_daemon()
            elif args.web_daemon_action == 'restart':
                restart_daemon()
            elif args.web_daemon_action == 'status':
                status_daemon()
            elif args.web_daemon_action == 'logs':
                show_logs()
            else:
                print("❌ Unknown web daemon action")
                
        elif args.daemon_command == 'slack':
            # TODO: Implement Slack daemon management
            if args.slack_daemon_action == 'start':
                print("🚀 Starting Slack bot daemon...")
                print("⚠️  Slack daemon management not yet implemented")
                print("💡 Use 'pypoe slack' for interactive mode")
            elif args.slack_daemon_action == 'stop':
                print("🛑 Stopping Slack bot daemon...")
                print("⚠️  Slack daemon management not yet implemented")
            elif args.slack_daemon_action == 'status':
                print("📊 Slack bot daemon status:")
                print("⚠️  Slack daemon management not yet implemented")
            elif args.slack_daemon_action == 'logs':
                print("📋 Slack bot daemon logs:")
                print("⚠️  Slack daemon management not yet implemented")
            else:
                print("❌ Unknown Slack daemon action")
        else:
            print("❌ Unknown daemon command")
            print("💡 Use 'pypoe daemon web' or 'pypoe daemon slack'")
            
    except ImportError as e:
        print(f"❌ Daemon management not available: {e}")
        print("💡 Check that daemon scripts are properly installed")
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
        elif args.interface == 'daemon':
            # Daemon management is synchronous
            run_daemon_command(args)
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