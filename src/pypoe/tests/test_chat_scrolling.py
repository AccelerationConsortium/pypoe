#!/usr/bin/env python3
"""
Test Chat Scrolling Functionality for PyPoe Web Interface
"""

import sys
import webbrowser
import time
import pytest
from pathlib import Path

# Get the root project directory
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

from pypoe.interfaces.web.runner import main

@pytest.mark.skip(reason="Manual integration test - starts web server")
def test_chat_scrolling():
    """
    Manual integration test for chat scrolling functionality.
    
    This test starts a web server for manual testing and should not be run
    during automated test runs. To run manually:
    
    pytest src/pypoe/tests/test_chat_scrolling.py::test_chat_scrolling -s
    """
    print("Starting PyPoe web interface...")
    print("Testing chat scrolling functionality:")
    print("   - Auto-scroll to bottom when loading conversations")
    print("   - Auto-scroll during message streaming")
    print("   - Navigation buttons (Home/End keys)")
    print("   - Smooth scrolling behavior")
    print("   - Mobile responsive design")
    print()
    print("Manual testing steps:")
    print("   1. Select a conversation with many messages")
    print("   2. Verify auto-scroll to latest message")
    print("   3. Test Home/End key navigation")
    print("   4. Test navigation buttons in chat header")
    print("   5. Send new messages and verify auto-scroll")
    print("   6. Test on mobile view (resize browser)")
    print()
    print("Opening browser...")
    
    # Give a moment for output to be visible
    time.sleep(2)
    
    # Open browser
    webbrowser.open("http://localhost:8000")
    
    # Start the web server
    main()

if __name__ == "__main__":
    test_chat_scrolling() 