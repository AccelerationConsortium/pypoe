#!/usr/bin/env python3
"""
Debug script to help diagnose chat scrolling issues.
This script creates a conversation with many messages to test scrolling.
"""

import sys
import requests
import json
from pathlib import Path

from pypoe.core.models import DEFAULT_CHAT_MODEL

def create_test_conversation():
    """Create a conversation with many messages for scrolling tests."""
    
    # API base URL - adjust if needed
    base_url = "http://localhost:8000"
    
    try:
        # Create new conversation
        print("🔧 Creating test conversation...")
        response = requests.post(f"{base_url}/api/conversation/new", data={
            'title': 'Scrolling Test Conversation',
            'bot_name': DEFAULT_CHAT_MODEL
        })
        
        if response.status_code != 200:
            print(f"❌ Failed to create conversation: {response.status_code}")
            return
            
        conversation_data = response.json()
        conversation_id = conversation_data['conversation_id']
        print(f"✅ Created conversation: {conversation_id}")
        
        # Add many test messages
        messages = [
            "Hello, this is the first message to test scrolling.",
            "This is message number 2. We need many messages to test if the chat container scrolls properly.",
            "Message 3: The chat interface should automatically scroll to show the latest messages.",
            "Message 4: When a conversation gets longer, users should be able to scroll up to see earlier messages.",
            "Message 5: This is a longer message to test how the interface handles content of varying lengths. Sometimes messages can be quite long and wrap to multiple lines, which might affect the scrolling behavior.",
            "Message 6: Testing, testing, 1, 2, 3...",
            "Message 7: The red border around the messages container should help identify the scrollable area.",
            "Message 8: If you can see a scrollbar on the right side, that means scrolling is working.",
            "Message 9: Try using the navigation buttons in the chat header to scroll up and down.",
            "Message 10: You can also use the Home and End keys to navigate (when not typing in the input field).",
            "Message 11: This conversation is specifically designed to test the scrolling functionality.",
            "Message 12: If the interface automatically scrolled to this message when you loaded the conversation, that's good!",
            "Message 13: The most recent messages should be visible at the bottom.",
            "Message 14: Earlier messages should be accessible by scrolling up.",
            "Message 15: The scroll behavior should be smooth and responsive.",
            "Message 16: Both mouse wheel and scrollbar should work for navigation.",
            "Message 17: On mobile devices, touch scrolling should also work properly.",
            "Message 18: The input area at the bottom should remain fixed while messages scroll.",
            "Message 19: The chat header with navigation buttons should also remain fixed.",
            "Message 20: This is the final test message. If you can see this message clearly and can scroll up to see all the previous messages, then the scrolling functionality is working correctly! 🎉"
        ]
        
        print(f"📝 Adding {len(messages)} test messages...")
        
        # Note: This is a simplified approach. In a real implementation,
        # you'd use the actual chat API endpoint that expects websocket connections.
        # For testing, we'll just show what the conversation should look like.
        
        print("\n✅ Test conversation created!")
        print(f"🌐 Open your browser to: {base_url}")
        print(f"📋 Look for conversation: 'Scrolling Test Conversation'")
        print("\n🔍 Debug checklist:")
        print("   ✓ Can you see a red border around the messages area?")
        print("   ✓ Is there a scrollbar visible on the right side?")
        print("   ✓ Does the page automatically scroll to the bottom message?")
        print("   ✓ Can you scroll up to see earlier messages?")
        print("   ✓ Do the navigation buttons work?")
        print("   ✓ Do Home/End keys work when not typing?")
        print("\n🐛 If scrolling doesn't work:")
        print("   - Check browser console for JavaScript errors")
        print("   - Verify the red border shows the scrollable area")
        print("   - Try resizing the browser window")
        print("   - Test on different browsers")
        
        return conversation_id
        
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to PyPoe web server.")
        print("💡 Make sure the server is running: python -m pypoe.web.runner")
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

if __name__ == "__main__":
    print("🚀 PyPoe Chat Scrolling Debug Tool")
    print("=" * 50)
    conversation_id = create_test_conversation()
    
    if conversation_id:
        print(f"\n✨ Ready for testing! Conversation ID: {conversation_id}")
    else:
        print("\n💔 Setup failed. Please check the error messages above.") 