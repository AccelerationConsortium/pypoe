#!/usr/bin/env python3
"""
Test script to demonstrate PyPoe web conversation history functionality.

This script shows how to:
1. Access conversations programmatically 
2. Use the web interface to visualize conversation history
3. Test the new history features

Usage:
    python examples/demo_web_history.py
"""

import asyncio
import sys
import os
from pathlib import Path

from pypoe.core.client import PoeChatClient
from pypoe.core.config import get_config

async def demonstrate_conversation_history():
    """Demonstrate conversation history features."""
    
    print("🧪 PyPoe Web History Demo")
    print("=" * 40)
    
    # Initialize client
    config = get_config()
    client = PoeChatClient(config=config)
    
    try:
        # Get conversations
        print("\n📚 Getting conversation history...")
        conversations = await client.get_conversations()
        
        if not conversations:
            print("📭 No conversations found.")
            print("💡 Try running: pypoe chat 'Hello, tell me a joke' --save-history")
            print("💡 Then run this script again to see the conversation in the web interface")
            return
        
        print(f"✅ Found {len(conversations)} conversations")
        
        # Show summary
        for i, conv in enumerate(conversations[:3], 1):  # Show first 3
            print(f"\n{i}. {conv.get('title', 'Untitled')}")
            print(f"   Bot: {conv.get('bot_name', 'Unknown')}")
            print(f"   Created: {conv.get('created_at', 'Unknown')}")
            
            # Get message count
            messages = await client.get_conversation_messages(conv['id'])
            print(f"   Messages: {len(messages)}")
            
            if messages:
                last_msg = messages[-1]
                preview = last_msg['content'][:60] + '...' if len(last_msg['content']) > 60 else last_msg['content']
                print(f"   Last: [{last_msg['role']}] {preview}")
        
        if len(conversations) > 3:
            print(f"\n... and {len(conversations) - 3} more conversations")
        
        # Instructions for viewing in web browser
        print("\n🌐 Tabbed Web Interface Instructions:")
        print("=" * 40)
        print("1. Start the web interface:")
        print("   pypoe web")
        print("\n2. Open your browser to:")
        print("   http://localhost:8000")
        print("\n3. Switch between tabs:")
        print("   • 💬 Chat Tab: Real-time conversation interface")
        print("   • 📚 History Tab: Browse all past conversations")
        print("\n4. History Tab Features:")
        print("   • 📊 Live conversation statistics")
        print("   • 🔍 Search conversations by title or content")
        print("   • 📱 Responsive list view with metadata")
        print("   • 👀 Click any conversation to view details in modal")
        print("   • 📜 Auto-scroll to latest messages with navigation buttons")
        print("   • ⌨️  Keyboard shortcuts: Esc (close), Home/End (navigate)")
        print("   • 🔢 Message numbers for easy chronological navigation")
        print("   • ▶️  Continue conversations directly from history")
        print("   • 💾 Export individual conversations")
        print("   • 🗑️  Delete conversations with confirmation")
        print("\n5. Seamless Integration:")
        print("   • All tabs share the same sidebar and data")
        print("   • Switch between chat and history without losing context")
        print("   • Real-time updates across all interface components")
        
        # API endpoints available
        print("\n🔌 Available API Endpoints:")
        print("=" * 40)
        print("• GET /history - Browse conversation history")
        print("• GET /conversation/{id} - View detailed conversation")
        print("• GET /api/conversations - Get all conversations (JSON)")
        print("• GET /api/conversations/search - Search conversations")
        print("• GET /api/stats - Get conversation statistics") 
        print("• GET /api/conversation/{id}/messages - Get conversation messages")
        
        print("\n✨ Try the web interface for the best conversation browsing experience!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        
    finally:
        await client.close()

def main():
    """Main function."""
    
    # Check if POE_API_KEY is set
    if not os.getenv('POE_API_KEY'):
        print("⚠️  POE_API_KEY not found in environment")
        print("💡 Set it with: export POE_API_KEY='your-api-key'")
        print("📖 Or copy pypoe.env.example to .env and fill in your key")
        return
    
    asyncio.run(demonstrate_conversation_history())

if __name__ == "__main__":
    main() 