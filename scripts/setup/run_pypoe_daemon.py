#!/usr/bin/env python3
"""
PyPoe Daemon Runner

This script helps you run PyPoe web server as a daemon that keeps running
even after you log out from SSH sessions.

Usage:
    python scripts/setup/run_pypoe_daemon.py start    # Start the daemon
    python scripts/setup/run_pypoe_daemon.py stop     # Stop the daemon
    python scripts/setup/run_pypoe_daemon.py restart  # Restart the daemon
    python scripts/setup/run_pypoe_daemon.py status   # Check daemon status
    python scripts/setup/run_pypoe_daemon.py logs     # View daemon logs
"""

import os
import sys
import signal
import subprocess
import time
import platform
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict

# Configuration
DAEMON_NAME = "pypoe-web"
PID_FILE = Path.home() / f".{DAEMON_NAME}.pid"
LOG_FILE = Path.home() / f".{DAEMON_NAME}.log"
ERROR_LOG_FILE = Path.home() / f".{DAEMON_NAME}.error.log"

def get_tailscale_ip() -> Optional[str]:
    """Get the current machine's Tailscale IP address"""
    try:
        result = subprocess.run(['tailscale', 'ip'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            # Get the IPv4 address (first line, usually)
            lines = result.stdout.strip().split('\n')
            for line in lines:
                line = line.strip()
                if line and not ':' in line:  # IPv4 (no colons)
                    return line
            # If no IPv4 found, use first line
            if lines:
                return lines[0].strip()
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

def get_network_interfaces() -> Dict[str, str]:
    """Get all network interfaces and their IP addresses"""
    interfaces = {}
    
    try:
        # Use different commands based on platform
        if platform.system() == "Windows":
            result = subprocess.run(['ipconfig'], capture_output=True, text=True, timeout=10)
            # Parse Windows ipconfig output (simplified)
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                current_adapter = None
                for line in lines:
                    line = line.strip()
                    if 'adapter' in line.lower() and ':' in line:
                        current_adapter = line.split('adapter')[1].split(':')[0].strip()
                    elif 'IPv4 Address' in line and current_adapter:
                        parts = line.split(':')
                        if len(parts) > 1:
                            ip = parts[1].strip()
                            if not ip.startswith('127.') and not ip.startswith('169.254.'):
                                interfaces[current_adapter] = ip
        else:
            # Unix-like systems
            result = subprocess.run(['ifconfig'], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                current_interface = None
                for line in result.stdout.split('\n'):
                    # Look for interface names (start of line, end with :)
                    if line and not line.startswith('\t') and not line.startswith(' ') and ':' in line:
                        current_interface = line.split(':')[0].strip()
                    # Look for inet addresses
                    elif current_interface and 'inet ' in line and 'netmask' in line:
                        parts = line.strip().split()
                        for i, part in enumerate(parts):
                            if part == 'inet' and i + 1 < len(parts):
                                ip = parts[i + 1]
                                # Skip certain interfaces
                                if not ip.startswith('127.') and not ip.startswith('169.254.'):
                                    interfaces[current_interface] = ip
                                break
    except Exception:
        pass
    
    return interfaces

def get_access_urls() -> Dict[str, str]:
    """Get all access URLs for the current machine"""
    urls = {}
    
    # Always include localhost
    urls['Local (localhost)'] = 'http://localhost:8000'
    urls['Local (127.0.0.1)'] = 'http://127.0.0.1:8000'
    
    # Get Tailscale IP
    tailscale_ip = get_tailscale_ip()
    if tailscale_ip:
        urls['Tailscale'] = f'http://{tailscale_ip}:8000'
    
    # Get other network interfaces
    interfaces = get_network_interfaces()
    for interface, ip in interfaces.items():
        if ip != tailscale_ip:  # Don't duplicate Tailscale IP
            urls[f'LAN ({interface})'] = f'http://{ip}:8000'
    
    return urls

def print_access_urls():
    """Print all access URLs"""
    print("🌐 Access the web interface at:")
    urls = get_access_urls()
    for name, url in urls.items():
        print(f"   • {name}: {url}")

def print_header():
    """Print header"""
    print("=" * 50)
    print("🚀 PyPoe Web Server Daemon Manager")
    print("=" * 50)

def is_running():
    """Check if daemon is running"""
    if not PID_FILE.exists():
        return False, None
    
    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())
        
        # Check if process is still running
        os.kill(pid, 0)
        return True, pid
    except (ValueError, ProcessLookupError, OSError):
        # PID file exists but process is not running
        PID_FILE.unlink(missing_ok=True)
        return False, None

def start_daemon():
    """Start the PyPoe web server daemon"""
    print_header()
    
    # Check if already running
    running, pid = is_running()
    if running:
        print(f"✅ PyPoe web server is already running (PID: {pid})")
        return
    
    print("🚀 Starting PyPoe web server daemon...")
    
    # Set working directory to PyPoe project root.
    # This script is in scripts/setup/, so go up two levels to reach the repo root.
    pypoe_root = Path(__file__).parent.parent.parent
    cwd = pypoe_root.resolve()
    
    print(f"📁 Working directory: {cwd}")
    
    # Load environment from .env file in the project root
    from dotenv import load_dotenv
    env_file = cwd / ".env"
    if env_file.exists():
        print(f"🔧 Loading environment from: {env_file}")
        load_dotenv(env_file)
    else:
        print(f"⚠️  No .env file found at: {env_file}")
    
    # Create log files
    LOG_FILE.touch()
    ERROR_LOG_FILE.touch()
    
    # Get the port from environment or use default
    port = os.environ.get('PYPOE_PORT', '8000')
    
    # Validate required environment variables
    if not os.environ.get('POE_API_KEY'):
        print("⚠️  Warning: POE_API_KEY not set in environment")
        print("   The web server may not function properly without it")
        print("   Get your API key from: https://poe.com/api_key")
        print(f"   Place it in a .env file in: {cwd}")
        print()
    else:
        print("✅ POE_API_KEY found in environment")
    
    # Start the process in background
    try:
        with open(LOG_FILE, 'a') as log_file, open(ERROR_LOG_FILE, 'a') as error_file:
            # Write startup message
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_file.write(f"\n=== PyPoe Web Server Started: {timestamp} ===\n")
            log_file.flush()
            
            # Create process arguments
            kwargs = {
                'cwd': cwd,
                'stdout': log_file,
                'stderr': error_file,
                'stdin': subprocess.DEVNULL,
                'env': os.environ.copy(),  # Explicitly pass the current environment
            }
            
            # Add process group creation for Unix systems
            if platform.system() != "Windows":
                kwargs['preexec_fn'] = os.setsid
            
            # Start pypoe web in background, explicitly setting host and port
            process = subprocess.Popen(
                ['pypoe', 'web', '--host', '0.0.0.0', '--port', port],
                **kwargs
            )
            
            # Save PID
            with open(PID_FILE, 'w') as f:
                f.write(str(process.pid))
            
            # Give it a moment to start
            time.sleep(2)
            
            # Check if it's still running
            if process.poll() is None:
                print(f"✅ PyPoe web server started successfully!")
                print(f"📁 PID: {process.pid}")
                print(f"📁 PID file: {PID_FILE}")
                print(f"📁 Log file: {LOG_FILE}")
                print(f"📁 Error log: {ERROR_LOG_FILE}")
                print()
                print_access_urls()
                print()
                print("💡 Use these commands:")
                print("   python scripts/setup/run_pypoe_daemon.py status   # Check status")
                print("   python scripts/setup/run_pypoe_daemon.py logs     # View logs")
                print("   python scripts/setup/run_pypoe_daemon.py stop     # Stop daemon")
            else:
                print("❌ Failed to start PyPoe web server")
                print(f"📁 Check error log: {ERROR_LOG_FILE}")
                PID_FILE.unlink(missing_ok=True)
                
    except Exception as e:
        print(f"❌ Error starting daemon: {e}")
        PID_FILE.unlink(missing_ok=True)

def stop_daemon():
    """Stop the PyPoe web server daemon"""
    print_header()
    
    running, pid = is_running()
    if not running:
        print("⚠️  PyPoe web server is not running")
        return
    
    print(f"🛑 Stopping PyPoe web server daemon (PID: {pid})...")
    
    try:
        # Try graceful shutdown first
        os.kill(pid, signal.SIGTERM)
        
        # Wait for process to stop
        for _ in range(10):  # Wait up to 10 seconds
            time.sleep(1)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
        else:
            # Force kill if still running
            print("🔨 Force killing process...")
            os.kill(pid, signal.SIGKILL)
        
        # Clean up PID file
        PID_FILE.unlink(missing_ok=True)
        
        # Log shutdown
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, 'a') as log_file:
            log_file.write(f"\n=== PyPoe Web Server Stopped: {timestamp} ===\n")
        
        print("✅ PyPoe web server stopped successfully")
        
    except ProcessLookupError:
        print("⚠️  Process was already stopped")
        PID_FILE.unlink(missing_ok=True)
    except Exception as e:
        print(f"❌ Error stopping daemon: {e}")

def restart_daemon():
    """Restart the PyPoe web server daemon"""
    print_header()
    print("🔄 Restarting PyPoe web server daemon...")
    stop_daemon()
    time.sleep(2)
    start_daemon()

def status_daemon():
    """Check daemon status"""
    print_header()
    
    running, pid = is_running()
    if running:
        print(f"✅ PyPoe web server is running (PID: {pid})")
        
        # Show process info
        try:
            result = subprocess.run(['ps', '-p', str(pid), '-o', 'pid,ppid,etime,cmd'], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                print("\n📊 Process Information:")
                print(result.stdout)
        except Exception:
            pass
        
        print_access_urls()
        
    else:
        print("❌ PyPoe web server is not running")
    
    print(f"\n📁 Files:")
    print(f"   • PID file: {PID_FILE} {'✅' if PID_FILE.exists() else '❌'}")
    print(f"   • Log file: {LOG_FILE} {'✅' if LOG_FILE.exists() else '❌'}")
    print(f"   • Error log: {ERROR_LOG_FILE} {'✅' if ERROR_LOG_FILE.exists() else '❌'}")

def show_logs():
    """Show daemon logs"""
    print_header()
    
    if not LOG_FILE.exists():
        print("❌ No log file found")
        return
    
    print(f"📋 Showing last 50 lines of {LOG_FILE}:")
    print("-" * 50)
    
    try:
        result = subprocess.run(['tail', '-n', '50', str(LOG_FILE)], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print(result.stdout)
        else:
            print("❌ Failed to read log file")
    except Exception as e:
        print(f"❌ Error reading log file: {e}")
    
    print("-" * 50)
    print(f"📁 Full log file: {LOG_FILE}")
    print(f"📁 Error log file: {ERROR_LOG_FILE}")

def main():
    """Main function"""
    if len(sys.argv) != 2:
        print("Usage: python scripts/setup/run_pypoe_daemon.py {start|stop|restart|status|logs}")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == 'start':
        start_daemon()
    elif command == 'stop':
        stop_daemon()
    elif command == 'restart':
        restart_daemon()
    elif command == 'status':
        status_daemon()
    elif command == 'logs':
        show_logs()
    else:
        print(f"❌ Unknown command: {command}")
        print("Available commands: start, stop, restart, status, logs")
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)
 