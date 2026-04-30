#!/usr/bin/env python3
"""
Simple Linux diagnostic for PyPoe history issues.

This script tests the core functionality that might be failing on Linux.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Add PyPoe to path
try:
    from pypoe.core.config import get_config
    from pypoe.core.client import PoeChatClient
    from pypoe.core.models import DEFAULT_CHAT_MODEL
    from pypoe.interfaces.web.app import WebApp
    print("✅ PyPoe imports successful")
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)

async def test_basic_functionality():
    """Test basic PyPoe functionality that might fail on Linux."""
    
    print("🔍 Testing PyPoe on Linux...")
    print(f"Platform: {sys.platform}")
    print(f"Python: {sys.version}")
    print(f"CWD: {os.getcwd()}")
    print(f"User: {os.getenv('USER', 'unknown')}")
    
    # Test 1: Config loading
    print("\n1️⃣ Testing config loading...")
    try:
        config = get_config()
        print(f"✅ Config loaded")
        print(f"   Database path: {config.database_path}")
        print(f"   API key set: {'Yes' if config.poe_api_key else 'No'}")
        
        # Check database directory permissions
        db_dir = Path(config.database_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"   Database dir exists: {db_dir.exists()}")
        print(f"   Database dir writable: {os.access(db_dir, os.W_OK)}")
        
    except Exception as e:
        print(f"❌ Config loading failed: {e}")
        return False
    
    # Test 2: Client initialization
    print("\n2️⃣ Testing PyPoe client...")
    try:
        client = PoeChatClient(config=config, enable_history=True)
        print("✅ Client created")
        
        # Test history initialization
        await client._ensure_history_initialized()
        print("✅ History initialized")
        
    except Exception as e:
        print(f"❌ Client initialization failed: {e}")
        return False
    
    # Test 3: Basic history operations
    print("\n3️⃣ Testing history operations...")
    try:
        # Test conversation creation
        conv_id = await client.history.create_conversation(
            title="Linux Test",
            bot_name=DEFAULT_CHAT_MODEL
        )
        print(f"✅ Conversation created: {conv_id[:8]}...")
        
        # Test message adding
        await client.history.add_message(
            conversation_id=conv_id,
            role="user", 
            content="Test message"
        )
        print("✅ Message added")
        
        # Test conversation retrieval
        conversations = await client.get_conversations()
        print(f"✅ Retrieved {len(conversations)} conversations")
        
        # Test message retrieval  
        messages = await client.get_conversation_messages(conv_id)
        print(f"✅ Retrieved {len(messages)} messages")
        
    except Exception as e:
        print(f"❌ History operations failed: {e}")
        return False
    
    # Test 4: Web interface creation
    print("\n4️⃣ Testing web interface...")
    try:
        webapp = WebApp(config=config)
        print("✅ Web app created")
        
        # Test conversation creation via web interface
        from pypoe.interfaces.web.app import ConversationCreate
        conv_data = ConversationCreate(
            title="Web Test",
            bot_name=DEFAULT_CHAT_MODEL,
            chat_mode="chatbot"
        )
        
        result_conv_id = await webapp.client.history.create_conversation(
            title=conv_data.title,
            bot_name=conv_data.bot_name
        )
        print(f"✅ Web conversation created: {result_conv_id[:8]}...")
        
    except Exception as e:
        print(f"❌ Web interface test failed: {e}")
        return False
    
    # Test 5: Database file inspection
    print("\n5️⃣ Testing database file...")
    try:
        import sqlite3
        
        with sqlite3.connect(config.database_path) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            print(f"✅ Database accessible, tables: {tables}")
            
            cursor = conn.execute("SELECT COUNT(*) FROM conversations")
            conv_count = cursor.fetchone()[0]
            print(f"✅ Database has {conv_count} conversations")
            
    except Exception as e:
        print(f"❌ Database inspection failed: {e}")
        return False
    
    print("\n🎉 All tests passed! PyPoe should be working correctly.")
    return True

async def main():
    """Main test function."""
    try:
        success = await test_basic_functionality()
        if not success:
            print("\n❌ Some tests failed. Please check the errors above.")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n⚠️  Tests interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 