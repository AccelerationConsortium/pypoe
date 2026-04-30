#!/usr/bin/env python3
"""
PyPoe Linux History Manager Troubleshooting Guide

This script helps identify and fix common Linux-specific issues with PyPoe's history manager.
It provides step-by-step diagnostics and automated fixes.

Usage:
    python scripts/linux_history_troubleshoot.py
"""

import asyncio
import os
import sys
import stat
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

# Add PyPoe to path if running standalone
if __name__ == "__main__":
    # scripts/linux_history_troubleshoot.py -> scripts/ -> repo root
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pypoe.core.models import DEFAULT_CHAT_MODEL

def print_section(title: str):
    """Print a formatted section header."""
    print(f"\n{'='*60}")
    print(f"🔍 {title}")
    print('='*60)

def print_step(step: str, status: str = None):
    """Print a diagnostic step with optional status."""
    if status:
        print(f"   {step} ... {status}")
    else:
        print(f"   {step}")

def print_fix(fix: str):
    """Print a fix suggestion."""
    print(f"🔧 FIX: {fix}")

def print_warning(warning: str):
    """Print a warning message."""
    print(f"⚠️  WARNING: {warning}")

def print_success(message: str):
    """Print a success message."""
    print(f"✅ {message}")

def print_error(message: str):
    """Print an error message."""
    print(f"❌ {message}")

async def check_permissions(config) -> Tuple[bool, List[str]]:
    """Check file and directory permissions."""
    print_section("Checking File Permissions")
    
    issues = []
    db_path = Path(config.database_path)
    db_dir = db_path.parent
    
    # Ensure directory exists
    print_step("Creating database directory if needed")
    try:
        db_dir.mkdir(parents=True, exist_ok=True)
        print_success(f"Directory exists: {db_dir}")
    except Exception as e:
        print_error(f"Cannot create directory: {e}")
        issues.append(f"Cannot create database directory: {e}")
        return False, issues
    
    # Check directory permissions
    print_step("Checking directory permissions")
    dir_stat = os.stat(db_dir)
    dir_perms = stat.filemode(dir_stat.st_mode)
    print(f"      Directory permissions: {dir_perms}")
    print(f"      Owner: UID {dir_stat.st_uid}, GID {dir_stat.st_gid}")
    print(f"      Current user: UID {os.getuid()}, GID {os.getgid()}")
    
    if not os.access(db_dir, os.W_OK):
        print_error("Directory is not writable")
        issues.append("Database directory is not writable")
        print_fix(f"chmod 755 {db_dir}")
    else:
        print_success("Directory is writable")
    
    # Check database file permissions if it exists
    if db_path.exists():
        print_step("Checking database file permissions")
        file_stat = os.stat(db_path)
        file_perms = stat.filemode(file_stat.st_mode)
        print(f"      File permissions: {file_perms}")
        
        if not os.access(db_path, os.R_OK | os.W_OK):
            print_error("Database file is not readable/writable")
            issues.append("Database file is not accessible")
            print_fix(f"chmod 644 {db_path}")
        else:
            print_success("Database file is accessible")
    else:
        print_step("Database file does not exist yet (this is normal for new installations)")
    
    return len(issues) == 0, issues

async def check_sqlite_functionality() -> Tuple[bool, List[str]]:
    """Test SQLite functionality."""
    print_section("Testing SQLite Functionality")
    
    issues = []
    
    # Test basic SQLite
    print_step("Testing SQLite import")
    try:
        import sqlite3
        import aiosqlite
        print_success(f"SQLite version: {sqlite3.sqlite_version}")
        print_success(f"aiosqlite available")
    except ImportError as e:
        print_error(f"SQLite import failed: {e}")
        issues.append(f"SQLite not available: {e}")
        return False, issues
    
    # Test database creation in temp directory
    print_step("Testing database creation")
    temp_db = "/tmp/pypoe_test.db"
    try:
        async with aiosqlite.connect(temp_db) as db:
            await db.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, data TEXT)")
            await db.execute("INSERT INTO test (data) VALUES (?)", ("test",))
            await db.commit()
            
            cursor = await db.execute("SELECT * FROM test")
            rows = await cursor.fetchall()
            if rows:
                print_success("SQLite operations work correctly")
            else:
                print_error("SQLite operations failed")
                issues.append("SQLite operations not working")
        
        # Cleanup
        os.unlink(temp_db)
        
    except Exception as e:
        print_error(f"SQLite test failed: {e}")
        issues.append(f"SQLite functionality issue: {e}")
    
    return len(issues) == 0, issues

async def check_history_manager_compatibility() -> Tuple[bool, List[str]]:
    """Check history manager method compatibility."""
    print_section("Checking History Manager Compatibility")
    
    issues = []
    
    try:
        from pypoe.core import HistoryManager
        print_success(f"HistoryManager imported from: {HistoryManager.__module__}")
        
        # Check required methods
        required_methods = [
            'initialize', 'create_conversation', 'add_message', 
            'get_conversations', 'get_conversation_messages'
        ]
        
        for method in required_methods:
            if hasattr(HistoryManager, method):
                print_success(f"Method {method} available")
            else:
                print_error(f"Method {method} missing")
                issues.append(f"Missing method: {method}")
        
        # Test signature compatibility
        print_step("Testing method signatures")
        manager = HistoryManager(db_path="/tmp/test_compat.db")
        
        # Test create_conversation signature
        import inspect
        create_sig = inspect.signature(manager.create_conversation)
        print(f"      create_conversation signature: {create_sig}")
        
        add_sig = inspect.signature(manager.add_message)
        print(f"      add_message signature: {add_sig}")
        
        print_success("Method signatures compatible")
        
    except Exception as e:
        print_error(f"History manager compatibility issue: {e}")
        issues.append(f"Compatibility issue: {e}")
    
    return len(issues) == 0, issues

async def test_full_workflow(config) -> Tuple[bool, List[str]]:
    """Test the complete PyPoe workflow."""
    print_section("Testing Complete PyPoe Workflow")
    
    issues = []
    
    try:
        from pypoe.core.client import PoeChatClient
        
        print_step("Creating PyPoe client")
        client = PoeChatClient(config=config, enable_history=True)
        print_success("Client created")
        
        print_step("Initializing history")
        await client._ensure_history_initialized()
        print_success("History initialized")
        
        print_step("Creating test conversation")
        conv_id = await client.history.create_conversation(
            title="Linux Troubleshoot Test",
            bot_name=DEFAULT_CHAT_MODEL,
            chat_mode="chatbot"
        )
        print_success(f"Conversation created: {conv_id[:8]}...")
        
        print_step("Adding test message")
        await client.history.add_message(
            conversation_id=conv_id,
            role="user",
            content="Linux troubleshooting test message",
            bot_name=DEFAULT_CHAT_MODEL
        )
        print_success("Message added")
        
        print_step("Retrieving conversations")
        conversations = await client.get_conversations()
        print_success(f"Retrieved {len(conversations)} conversations")
        
        print_step("Retrieving messages")
        messages = await client.get_conversation_messages(conv_id)
        print_success(f"Retrieved {len(messages)} messages")
        
        print_step("Testing web interface creation")
        from pypoe.interfaces.web.app import WebApp
        webapp = WebApp(config=config)
        print_success("Web interface created successfully")
        
    except Exception as e:
        print_error(f"Workflow test failed: {e}")
        issues.append(f"Workflow failure: {e}")
        import traceback
        traceback.print_exc()
    
    return len(issues) == 0, issues

def suggest_fixes(all_issues: List[str]):
    """Suggest fixes for identified issues."""
    print_section("Recommended Fixes")
    
    if not all_issues:
        print_success("No issues found! PyPoe should be working correctly.")
        return
    
    print("Based on the diagnostic results, here are the recommended fixes:\n")
    
    for i, issue in enumerate(all_issues, 1):
        print(f"{i}. {issue}")
    
    print("\n🔧 AUTOMATIC FIXES YOU CAN TRY:")
    
    # Permission fixes
    if any("permission" in issue.lower() or "writable" in issue.lower() for issue in all_issues):
        print("\n📁 Permission Issues:")
        print("   • Run: chmod 755 ~/.pypoe")
        print("   • Run: chmod 644 ~/.pypoe/*.db (if database exists)")
        print("   • Or try running PyPoe with different database path:")
        print("     export DATABASE_PATH=/tmp/pypoe_test.db")
    
    # SQLite issues
    if any("sqlite" in issue.lower() for issue in all_issues):
        print("\n🗄️  SQLite Issues:")
        print("   • Update SQLite: sudo apt update && sudo apt install sqlite3")
        print("   • Reinstall aiosqlite: pip install --force-reinstall aiosqlite")
    
    # Method compatibility issues
    if any("method" in issue.lower() or "compatibility" in issue.lower() for issue in all_issues):
        print("\n🔄 Compatibility Issues:")
        print("   • Update PyPoe: pip install -e . --force-reinstall")
        print("   • Clear Python cache: find . -name '*.pyc' -delete")
        print("   • Restart your application completely")
    
    print("\n🐛 If issues persist:")
    print("   • Try a different database location: export DATABASE_PATH=/tmp/pypoe.db")
    print("   • Check disk space: df -h")
    print("   • Check for other processes using the database: lsof ~/.pypoe/*.db")
    print("   • Run with debug output: PYTHONPATH=. python -v")

async def main():
    """Main troubleshooting function."""
    print("🐧 PyPoe Linux History Manager Troubleshooter")
    print("=" * 50)
    print(f"Platform: {sys.platform}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"User: {os.getenv('USER')}")
    print(f"Working directory: {os.getcwd()}")
    
    # Load config
    try:
        from pypoe.core.config import get_config
        config = get_config()
        print_success(f"Config loaded, database path: {config.database_path}")
    except Exception as e:
        print_error(f"Failed to load config: {e}")
        return
    
    all_issues = []
    
    # Run all diagnostic checks
    checks = [
        ("File Permissions", check_permissions(config)),
        ("SQLite Functionality", check_sqlite_functionality()),
        ("History Manager Compatibility", check_history_manager_compatibility()),
        ("Full Workflow", test_full_workflow(config))
    ]
    
    for check_name, check_coro in checks:
        try:
            success, issues = await check_coro
            if success:
                print_success(f"{check_name}: All checks passed")
            else:
                print_error(f"{check_name}: Issues found")
                all_issues.extend(issues)
        except Exception as e:
            print_error(f"{check_name}: Check failed with error: {e}")
            all_issues.append(f"{check_name} check failed: {e}")
    
    # Provide recommendations
    suggest_fixes(all_issues)
    
    if all_issues:
        print(f"\n❌ Found {len(all_issues)} issues that need attention.")
        sys.exit(1)
    else:
        print("\n🎉 All checks passed! PyPoe should be working correctly on Linux.")

if __name__ == "__main__":
    asyncio.run(main()) 