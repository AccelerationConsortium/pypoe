#!/usr/bin/env python3
"""
Quick PyPoe Troubleshooting for Linux Server
Run this when web interface loads but can't access chat history.
"""

import sys
import os
import sqlite3
import requests
from pathlib import Path
from pypoe.core.config import get_config

def check_environment():
    """Quick environment check"""
    print("🔍 Quick Environment Check")
    print("-" * 30)
    
    # Check if we're in PyPoe directory
    project_files = ["pyproject.toml", "src/pypoe", "users/"]
    found = [f for f in project_files if Path(f).exists()]
    print(f"📁 PyPoe files found: {found}")
    
    # Check Python path
    try:
        from pypoe.core.config import get_config
        print("✅ PyPoe modules importable")
        return True
    except ImportError as e:
        print(f"❌ Cannot import PyPoe: {e}")
        print("💡 Try: export PYTHONPATH=$PWD/src:$PYTHONPATH")
        return False

def check_config():
    """Check PyPoe configuration"""
    print("\n🔍 Configuration Check")
    print("-" * 30)
    
    try:
        from pypoe.core.config import get_config
        config = get_config()
        print(f"Config loaded from: {config.config_path}")
        print(f"Database: {config.database_path}")
        print(f"API Key set: {'Yes' if config.api_key else 'No'}")
        
    except ImportError:
        print("Could not import pypoe config")
    except Exception as e:
        print(f"Config error: {e}")

def check_web_server():
    """Check if web server is running and responsive"""
    print("\n🔍 Web Server Check")
    print("-" * 30)
    
    ports = [8000, 5173, 3000]
    for port in ports:
        try:
            response = requests.get(f"http://localhost:{port}", timeout=2)
            print(f"✅ Port {port}: {response.status_code}")
            
            # Test API endpoints
            if port == 8000:
                try:
                    api_response = requests.get(f"http://localhost:{port}/api/health", timeout=2)
                    print(f"   📡 API Health: {api_response.status_code}")
                    
                    conv_response = requests.get(f"http://localhost:{port}/api/conversations", timeout=2)
                    print(f"   📡 API Conversations: {conv_response.status_code}")
                    
                    if conv_response.status_code == 200:
                        convs = conv_response.json()
                        print(f"   💬 API returned {len(convs)} conversations")
                    
                except Exception as e:
                    print(f"   ❌ API error: {e}")
            
            return True
            
        except requests.exceptions.ConnectionError:
            print(f"⚪ Port {port}: Not running")
        except Exception as e:
            print(f"❌ Port {port}: Error - {e}")
    
    return False

def check_browser_console():
    """Instructions for checking browser console"""
    print("\n🔍 Browser Debug Instructions")
    print("-" * 30)
    print("1. Open browser developer tools (F12)")
    print("2. Go to Console tab")
    print("3. Look for JavaScript errors (red text)")
    print("4. Go to Network tab")
    print("5. Try accessing chat history")
    print("6. Look for failed API requests (red status codes)")
    print("\nCommon issues:")
    print("- 401/403: Authentication issues")
    print("- 500: Server error")
    print("- CORS errors: Network configuration")

def generate_commands():
    """Generate useful debugging commands"""
    print("\n💡 Debugging Commands")
    print("-" * 30)
    
    commands = [
        "# Check if web server is running",
        "ps aux | grep pypoe",
        "",
        "# Check port usage",
        "netstat -tlnp | grep :8000",
        "lsof -i :8000",
        "",
        "# Test API directly",
        "curl -v http://localhost:8000/api/health",
        "curl -v http://localhost:8000/api/conversations",
        "",
        "# Check logs",
        "tail -f ~/.pypoe-web.log",
        "",
        "# Restart web server",
        "pkill -f 'pypoe web'",
        "pypoe web --host 0.0.0.0 --port 8000",
        "",
        "# Check database directly",
        "sqlite3 users/history/pypoe_history.db 'SELECT COUNT(*) FROM conversations;'",
        "sqlite3 users/history/pypoe_history.db '.tables'",
    ]
    
    for cmd in commands:
        print(cmd)

def main():
    """Run quick diagnostics"""
    print("🩺 PyPoe Quick Troubleshooting")
    print("=" * 40)
    
    # Basic checks
    env_ok = check_environment()
    if not env_ok:
        print("\n❌ Environment issues found. Fix these first.")
        return 1
    
    config_ok = check_config()
    if not config_ok:
        print("\n❌ Configuration issues found.")
        return 1
    
    web_ok = check_web_server()
    if not web_ok:
        print("\n❌ Web server not running or not responding.")
        print("💡 Start with: pypoe web --host 0.0.0.0 --port 8000")
    
    check_browser_console()
    generate_commands()
    
    print("\n📋 Summary")
    print("-" * 30)
    if env_ok and config_ok and web_ok:
        print("✅ Basic checks passed")
        print("💡 Check browser console for JavaScript errors")
    else:
        print("❌ Issues found - see output above")
    
    return 0

if __name__ == "__main__":
    sys.exit(main()) 