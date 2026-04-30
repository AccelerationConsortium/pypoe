#!/usr/bin/env python3
"""
Quick test script for chat scrolling functionality.
This script starts the web server and opens the browser for immediate testing.
"""

import sys
import webbrowser
import time
from pathlib import Path

# Add the src directory to Python path
src_path = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(src_path))

def main():
    print("🔧 PyPoe Chat Scrolling Quick Test")
    print("=" * 50)
    print()
    print("🚀 Starting web server...")
    print("📱 Opening browser...")
    print()
    print("🔍 What to test:")
    print("   1. Select any conversation with messages")
    print("   2. Look for RED BORDER around messages area")
    print("   3. Check if page scrolls to bottom automatically")
    print("   4. Try scrolling up/down with mouse wheel")
    print("   5. Test navigation buttons (up/down arrows)")
    print("   6. Try Home/End keys (when not typing)")
    print()
    print("✅ Scrolling is WORKING if:")
    print("   - You see a thick red border around messages")
    print("   - Scrollbar appears when there are many messages")
    print("   - Page auto-scrolls to latest message")
    print("   - You can scroll up to see older messages")
    print()
    print("❌ Scrolling is BROKEN if:")
    print("   - No red border visible")
    print("   - Messages overflow but can't scroll")
    print("   - Page doesn't auto-scroll to bottom")
    print("   - Navigation buttons don't work")
    print()
    print("🌐 Opening browser in 3 seconds...")
    
    # Give time to read instructions
    time.sleep(3)
    
    # Open browser
    webbrowser.open("http://localhost:8000")
    
    # Import and start the web server
    try:
        from pypoe.interfaces.web.runner import main as web_main
        web_main()
    except ImportError as e:
        print(f"❌ Could not import web runner: {e}")
        print("💡 Make sure you're in the PyPoe directory and dependencies are installed")
    except KeyboardInterrupt:
        print("\n👋 Web server stopped. Testing complete!")

if __name__ == "__main__":
    main() 