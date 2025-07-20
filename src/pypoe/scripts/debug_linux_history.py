#!/usr/bin/env python3
"""
Linux History Manager Diagnostic Script

This script helps diagnose Linux-specific issues with PyPoe's history manager.
It tests database creation, permissions, and various operations to identify
where the problem might be occurring.

Usage:
    python src/pypoe/scripts/debug_linux_history.py
    
Or via CLI:
    pypoe debug-linux
"""

import asyncio
import os
import sys
import traceback
from pathlib import Path
from typing import Dict, Any

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

from pypoe.core.config import get_config
from pypoe.core.client import PoeChatClient

async def test_config():
    """Test configuration loading."""
    print("🔧 Testing Configuration...")
    try:
        config = get_config()
        print(f"✅ Config loaded successfully")
        print(f"   Database path: {config.database_path}")
        print(f"   Database path exists: {Path(config.database_path).exists()}")
        print(f"   Database directory: {Path(config.database_path).parent}")
        print(f"   Database directory exists: {Path(config.database_path).parent.exists()}")
        
        # Check permissions
        db_dir = Path(config.database_path).parent
        print(f"   Directory permissions: {oct(os.stat(db_dir).st_mode)[-3:]}")
        print(f"   Directory writable: {os.access(db_dir, os.W_OK)}")
        print(f"   Directory readable: {os.access(db_dir, os.R_OK)}")
        
        if Path(config.database_path).exists():
            print(f"   Database file permissions: {oct(os.stat(config.database_path).st_mode)[-3:]}")
            print(f"   Database file writable: {os.access(config.database_path, os.W_OK)}")
            print(f"   Database file readable: {os.access(config.database_path, os.R_OK)}")
        
        return config
    except Exception as e:
        print(f"❌ Config loading failed: {e}")
        traceback.print_exc()
        return None

async def test_history_manager_import():
    """Test importing and initializing history manager."""
    print("\n📦 Testing History Manager Import...")
    try:
        from pypoe.core import HistoryManager
        print(f"✅ HistoryManager imported: {HistoryManager}")
        print(f"   Module: {HistoryManager.__module__}")
        
        # HistoryManager with full feature set
        print("   Type: HistoryManager (with media and topic support)")
        
        return HistoryManager
    except Exception as e:
        print(f"❌ HistoryManager import failed: {e}")
        traceback.print_exc()
        return None

async def test_history_initialization(config, HistoryManager):
    """Test history manager initialization."""
    print("\n🔧 Testing History Manager Initialization...")
    try:
        # Test different initialization patterns
        print("   Testing direct initialization...")
        
        # Initialize HistoryManager with media support
        media_dir = Path(config.database_path).parent / "media"
        history = HistoryManager(
            db_path=str(config.database_path),
            media_dir=str(media_dir)
        )
        
        print("   ✅ History manager instance created")
        
        # Test initialization
        print("   Testing database initialization...")
        await history.initialize()
        print("   ✅ Database initialized successfully")
        
        return history
    except Exception as e:
        print(f"   ❌ History manager initialization failed: {e}")
        traceback.print_exc()
        return None

async def test_conversation_operations(history):
    """Test basic conversation operations."""
    print("\n💬 Testing Conversation Operations...")
    
    test_results = {
        "create_conversation": False,
        "add_message": False,
        "get_conversations": False,
        "get_messages": False
    }
    
    conversation_id = None
    
    try:
        # Test conversation creation
        print("   Testing conversation creation...")
        if hasattr(history, 'create_conversation'):
            conversation_id = await history.create_conversation(
                title="Linux Test Conversation",
                bot_name="GPT-3.5-Turbo"
            )
        else:
            conversation_id = await history.save_conversation("Linux Test Conversation")
        
        print(f"   ✅ Conversation created: {conversation_id}")
        test_results["create_conversation"] = True
        
    except Exception as e:
        print(f"   ❌ Conversation creation failed: {e}")
        traceback.print_exc()
    
    if conversation_id:
        try:
            # Test message adding
            print("   Testing message addition...")
            if hasattr(history, 'add_message'):
                await history.add_message(
                    conversation_id=conversation_id,
                    role="user",
                    content="Test message from Linux diagnostic"
                )
            else:
                await history.save_message(
                    conversation_id=conversation_id,
                    role="user",
                    content="Test message from Linux diagnostic"
                )
            
            print("   ✅ Message added successfully")
            test_results["add_message"] = True
            
        except Exception as e:
            print(f"   ❌ Message addition failed: {e}")
            traceback.print_exc()
    
    try:
        # Test conversation retrieval
        print("   Testing conversation retrieval...")
        conversations = await history.get_conversations()
        print(f"   ✅ Retrieved {len(conversations)} conversations")
        test_results["get_conversations"] = True
        
        if conversations:
            for conv in conversations[:3]:  # Show first 3
                print(f"      - {conv.get('id', 'No ID')[:8]}... | {conv.get('title', 'No title')}")
        
    except Exception as e:
        print(f"   ❌ Conversation retrieval failed: {e}")
        traceback.print_exc()
    
    if conversation_id:
        try:
            # Test message retrieval
            print("   Testing message retrieval...")
            if hasattr(history, 'get_messages'):
                messages = await history.get_messages(conversation_id)
            else:
                messages = await history.get_conversation_messages(conversation_id)
            
            print(f"   ✅ Retrieved {len(messages)} messages")
            test_results["get_messages"] = True
            
        except Exception as e:
            print(f"   ❌ Message retrieval failed: {e}")
            traceback.print_exc()
    
    return test_results

async def test_client_integration(config):
    """Test PyPoe client with history enabled."""
    print("\n🤖 Testing PyPoe Client Integration...")
    
    try:
        print("   Creating PyPoe client...")
        client = PoeChatClient(config=config, enable_history=True)
        print("   ✅ Client created successfully")
        
        print("   Testing client history initialization...")
        await client._ensure_history_initialized()
        print("   ✅ Client history initialized")
        
        print("   Testing get_conversations...")
        conversations = await client.get_conversations()
        print(f"   ✅ Client retrieved {len(conversations)} conversations")
        
        # Test creating a new conversation through the client
        print("   Testing new conversation creation through client...")
        test_conv_id = await client.history.create_conversation(
            title="Client Integration Test",
            bot_name="GPT-3.5-Turbo"
        )
        print(f"   ✅ Client created conversation: {test_conv_id}")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Client integration failed: {e}")
        traceback.print_exc()
        return False

async def test_web_interface_operations(config):
    """Test web interface specific operations."""
    print("\n🌐 Testing Web Interface Operations...")
    
    try:
        from pypoe.interfaces.web.app import WebApp
        
        print("   Creating web app...")
        webapp = WebApp(config=config)
        print("   ✅ Web app created")
        
        print("   Testing web client history operations...")
        conversations = await webapp.client.get_conversations()
        print(f"   ✅ Web app retrieved {len(conversations)} conversations")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Web interface test failed: {e}")
        traceback.print_exc()
        return False

async def check_sqlite_version():
    """Check SQLite version and capabilities."""
    print("\n🗄️  Checking SQLite Information...")
    
    try:
        import sqlite3
        import aiosqlite
        
        print(f"   SQLite3 version: {sqlite3.sqlite_version}")
        print(f"   Python SQLite3 API: {sqlite3.version}")
        print(f"   aiosqlite version: {aiosqlite.version}")
        
        # Test basic SQLite operations
        test_db = "/tmp/pypoe_sqlite_test.db"
        async with aiosqlite.connect(test_db) as db:
            await db.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, data TEXT)")
            await db.execute("INSERT INTO test (data) VALUES (?)", ("test",))
            await db.commit()
            
            cursor = await db.execute("SELECT * FROM test")
            rows = await cursor.fetchall()
            print(f"   ✅ SQLite basic operations work: {len(rows)} test rows")
        
        # Cleanup
        os.unlink(test_db)
        
        return True
        
    except Exception as e:
        print(f"   ❌ SQLite test failed: {e}")
        traceback.print_exc()
        return False

async def generate_report(test_results: Dict[str, Any]):
    """Generate a comprehensive diagnostic report."""
    print("\n" + "="*60)
    print("📋 LINUX HISTORY MANAGER DIAGNOSTIC REPORT")
    print("="*60)
    
    total_tests = sum(1 for v in test_results.values() if isinstance(v, bool))
    passed_tests = sum(1 for v in test_results.values() if v is True)
    
    print(f"Overall Status: {passed_tests}/{total_tests} tests passed")
    
    if passed_tests == total_tests:
        print("🎉 All tests passed! History manager should be working correctly.")
    else:
        print("⚠️  Some tests failed. See details below:")
        
        for test_name, result in test_results.items():
            if isinstance(result, bool):
                status = "✅ PASS" if result else "❌ FAIL"
                print(f"   {status} {test_name}")
    
    # Recommendations
    print("\n🔧 Recommendations:")
    
    if not test_results.get("config", False):
        print("   - Check environment variables and .env file configuration")
        print("   - Ensure POE_API_KEY is set correctly")
    
    if not test_results.get("sqlite", False):
        print("   - Install or update SQLite3")
        print("   - Check if aiosqlite is properly installed")
    
    if not test_results.get("history_init", False):
        print("   - Check database file permissions")
        print("   - Ensure the database directory is writable")
        print("   - Try running with sudo to test permission issues")
    
    if test_results.get("config", False) and not test_results.get("conversation_ops", {}).get("create_conversation", False):
        print("   - Database may be corrupted - try deleting and recreating")
        print("   - Check for disk space issues")
        print("   - Verify no other processes are locking the database")
    
    print("\n📞 If issues persist:")
    print("   - Share this diagnostic report in your issue")
    print("   - Include your Linux distribution and version")
    print("   - Include your Python version")
    print("   - Try running with different database paths")

async def main():
    """Main diagnostic function."""
    print("🐧 PyPoe Linux History Manager Diagnostic Tool")
    print("="*50)
    
    # System information
    print(f"Python version: {sys.version}")
    print(f"Platform: {sys.platform}")
    print(f"Working directory: {os.getcwd()}")
    print(f"User: {os.getenv('USER', 'Unknown')}")
    print(f"HOME: {os.getenv('HOME', 'Unknown')}")
    
    test_results = {}
    
    # Run diagnostic tests
    config = await test_config()
    test_results["config"] = config is not None
    
    test_results["sqlite"] = await check_sqlite_version()
    
    if config:
        HistoryManager = await test_history_manager_import()
        test_results["history_import"] = HistoryManager is not None
        
        if HistoryManager:
            history = await test_history_initialization(config, HistoryManager)
            test_results["history_init"] = history is not None
            
            if history:
                conversation_ops = await test_conversation_operations(history)
                test_results["conversation_ops"] = conversation_ops
                
                test_results["client_integration"] = await test_client_integration(config)
                test_results["web_interface"] = await test_web_interface_operations(config)
    
    # Generate final report
    await generate_report(test_results)

if __name__ == "__main__":
    asyncio.run(main()) 