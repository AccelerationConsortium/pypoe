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
  web         - Start web interface interactively (browser-based UI)
  cli         - Interactive command-line chat interface
  slack       - Start Slack bot interactively
  lab-mcp     - Read-only MCP server for the AC Organic Self-driving Lab
  lab-status  - One-shot health summary for the lab aggregator

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

  # Lab integration (requires `pip install -e '.[lab]'`)
  pypoe lab-status              # Print aggregator health + non-ready devices
  pypoe lab-mcp                 # Run the MCP server on stdio (for Claude Desktop)

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

    # Lab integration (AC Organic Self-driving Lab dashboard)
    lab_mcp_parser = subparsers.add_parser(
        'lab-mcp',
        help='Run the read-only lab MCP server on stdio (for Claude Desktop / Code)',
    )
    lab_mcp_parser.add_argument(
        '--base-url',
        default=None,
        help='Override LAB_API_URL (default: http://localhost:8000).',
    )

    lab_status_parser = subparsers.add_parser(
        'lab-status',
        help='Print aggregator health + non-ready devices and exit',
    )
    lab_status_parser.add_argument(
        '--base-url',
        default=None,
        help='Override LAB_API_URL (default: http://localhost:8000).',
    )

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
        print(f"Web interface not available: {e}")
        print("Install web dependencies: pip install -e '.[web-ui]'")
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
        print(f"CLI interface not available: {e}")
        sys.exit(1)

async def run_slack_interface():
    """Run the Slack interface."""
    try:
        from ..interfaces.slack.bot import main as slack_main
        await slack_main()
    except ImportError as e:
        print(f"Slack interface not available: {e}")
        print("Install Slack dependencies: pip install -e '.[web-ui]'")
        sys.exit(1)

def run_lab_mcp(base_url=None):
    """Run the lab MCP server on stdio."""
    try:
        from ..lab.mcp_server import main as mcp_main
    except ImportError as e:
        print(f"Lab MCP not available: {e}")
        print("Install lab dependencies: pip install -e '.[lab]'")
        sys.exit(1)
    if base_url:
        import os
        os.environ["LAB_API_URL"] = base_url
    mcp_main()

async def run_lab_status(base_url=None):
    """Print aggregator health + a one-line summary of every device."""
    try:
        from ..lab.http_client import LabClient
    except ImportError as e:
        print(f"Lab integration not available: {e}")
        print("Install lab dependencies: pip install -e '.[lab]'")
        sys.exit(1)

    async with LabClient(base_url=base_url) as client:
        try:
            health = await client.health()
        except Exception as exc:
            print(f"Aggregator unreachable at {client.base_url}: {exc}")
            sys.exit(2)

        version = health.get("version", "?")
        count = health.get("equipment_count", "?")
        print(f"Aggregator healthy — version {version}, {count} device(s) registered")

        try:
            data = await client.list_equipment()
        except Exception as exc:
            print(f"Could not list equipment: {exc}")
            return

        equipment = data.get("equipment", [])
        healthy_states = {"ready", "idle", "running", "dry_run"}
        unhealthy = []
        for e in equipment:
            state = ((e.get("status") or {}).get("equipment_status")
                     or ("unreachable" if e.get("fetch_error") else "unknown"))
            if state not in healthy_states:
                unhealthy.append((e.get("id"), state, e))

        if not unhealthy:
            print("All devices in a healthy state.")
            return

        print(f"{len(unhealthy)} device(s) need attention:")
        for eq_id, state, eq in unhealthy:
            status = eq.get("status") or {}
            msg = status.get("message") or ""
            line = f"  - {eq_id}: {state}"
            if msg:
                line += f" — {msg}"
            print(line)

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
        elif args.interface == 'lab-mcp':
            # MCP server is sync (FastMCP runs its own event loop over stdio).
            run_lab_mcp(getattr(args, 'base_url', None))
        elif args.interface == 'lab-status':
            asyncio.run(run_lab_status(getattr(args, 'base_url', None)))
        else:
            parser.print_help()
            
    except KeyboardInterrupt:
        print("\nGoodbye!")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

def run():
    """Entry point for console scripts."""
    main()

if __name__ == "__main__":
    run()