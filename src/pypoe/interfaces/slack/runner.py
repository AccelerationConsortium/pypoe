#!/usr/bin/env python3
"""
PyPoe Slack Bot Runner

Simple script to run the Slack bot from the pypoe package.
The actual implementation is in src/pypoe/slack_bot.py

Usage:
    python src/pypoe/slack_bot_runner.py
    
Or use the CLI:
    pypoe slack-bot
"""

import asyncio
import sys

def run_bot():
    """Run the Slack bot."""
    try:
        from .bot import main
        return asyncio.run(main())
    except ImportError as e:
        print(f"Failed to import PyPoe Slack integration: {e}")
        print("\nMake sure you have installed PyPoe:")
        print("   pip install -e .")
        print("\nAnd install Slack dependencies:")
        print("   pip install slack-bolt slack-sdk")
        print("\nOr use the CLI command:")
        print("   pypoe slack-bot")
        sys.exit(1)

if __name__ == "__main__":
    run_bot() 