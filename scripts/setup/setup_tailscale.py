#!/usr/bin/env python3
"""
PyPoe Tailscale Setup Script

This script helps you set up PyPoe to work with Tailscale for remote access.
It will:
1. Check if Tailscale is installed
2. Check if Tailscale is running
3. Get your Tailscale IP address
4. Configure PyPoe environment variables
5. Test the connection

Perfect for accessing your PyPoe web interface from anywhere on your Tailscale network!
"""

import os
import sys
import subprocess
import platform
from pathlib import Path
from typing import Optional, Tuple, Dict

def print_header():
    """Print a nice header"""
    print("=" * 60)
    print("PyPoe Tailscale Setup")
    print("=" * 60)
    print("This script will help you set up PyPoe for remote access via Tailscale.")
    print()

def check_tailscale_installed() -> bool:
    """Check if Tailscale is installed"""
    try:
        result = subprocess.run(['tailscale', '--version'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            version = result.stdout.strip()
            print(f"Tailscale is installed: {version}")
            return True
        else:
            print("Tailscale command failed")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("Tailscale is not installed or not in PATH")
        return False

def install_tailscale_instructions():
    """Provide installation instructions for Tailscale"""
    system = platform.system().lower()
    
    print("\nTailscale Installation Instructions:")
    print("-" * 40)
    
    if system == "darwin":  # macOS
        print("For macOS:")
        print("1. Download from: https://tailscale.com/download/mac")
        print("2. Or install via Homebrew: brew install tailscale")
        print("3. Or install via Mac App Store")
    elif system == "linux":
        print("For Linux:")
        print("1. Visit: https://tailscale.com/download/linux")
        print("2. Or use curl: curl -fsSL https://tailscale.com/install.sh | sh")
    elif system == "windows":
        print("For Windows:")
        print("1. Download from: https://tailscale.com/download/windows")
        print("2. Or install via winget: winget install tailscale.tailscale")
    else:
        print("Visit https://tailscale.com/download for your platform")
    
    print("\nAfter installation, run this script again!")

def check_tailscale_status() -> Tuple[bool, Optional[str]]:
    """Check if Tailscale is running and get status"""
    try:
        result = subprocess.run(['tailscale', 'status'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            status_lines = result.stdout.strip().split('\n')
            if status_lines and not any('not logged in' in line.lower() for line in status_lines):
                print("Tailscale is running and connected")
                return True, result.stdout
            else:
                print("Tailscale is installed but not logged in")
                return False, result.stdout
        else:
            print("Tailscale status check failed")
            return False, None
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"Failed to check Tailscale status: {e}")
        return False, None

def get_tailscale_ip() -> Optional[str]:
    """Get the Tailscale IP address"""
    try:
        result = subprocess.run(['tailscale', 'ip'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            # Get the IPv4 address (first line, usually)
            lines = result.stdout.strip().split('\n')
            for line in lines:
                line = line.strip()
                if line and not ':' in line:  # IPv4 (no colons)
                    print(f"Tailscale IPv4: {line}")
                    return line
            # If no IPv4 found, use first line
            if lines:
                ip = lines[0].strip()
                print(f"Tailscale IP: {ip}")
                return ip
        print("Failed to get Tailscale IP")
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"Failed to get Tailscale IP: {e}")
        return None

def start_tailscale():
    """Help user start Tailscale"""
    print("\nStarting Tailscale...")
    print("We'll try to start Tailscale for you.")
    
    system = platform.system().lower()
    
    try:
        if system == "darwin":  # macOS
            print("Starting Tailscale on macOS...")
            # Try to start via launchctl
            subprocess.run(['sudo', 'launchctl', 'load', '/Library/LaunchDaemons/com.tailscale.tailscaled.plist'], 
                         check=False)
            # Also try the direct command
            subprocess.run(['sudo', 'tailscaled'], check=False, timeout=5)
        elif system == "linux":
            print("Starting Tailscale on Linux...")
            subprocess.run(['sudo', 'systemctl', 'start', 'tailscaled'], check=False)
        else:
            print("Please start Tailscale manually on your system")
            return False
        
        print("Attempted to start Tailscale daemon")
        return True
        
    except Exception as e:
        print(f"Could not start Tailscale automatically: {e}")
        print("Please start Tailscale manually:")
        if system == "darwin":
            print("  - Open Tailscale app from Applications")
            print("  - Or run: sudo tailscaled")
        elif system == "linux":
            print("  - Run: sudo systemctl start tailscaled")
        return False

def login_tailscale():
    """Help user log in to Tailscale"""
    print("\nLogging in to Tailscale...")
    print("This will open a browser window for authentication.")
    
    try:
        # Start the login process
        result = subprocess.run(['tailscale', 'up'], 
                              capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            print("Tailscale login successful!")
            return True
        else:
            print(f"Tailscale login failed: {result.stderr}")
            print("\nManual login steps:")
            print("1. Run: tailscale up")
            print("2. Follow the browser instructions")
            print("3. Run this script again")
            return False
            
    except subprocess.TimeoutExpired:
        print("Login process timed out")
        print("Please complete the login manually:")
        print("1. Run: tailscale up")
        print("2. Follow the browser instructions")
        print("3. Run this script again")
        return False
    except Exception as e:
        print(f"Error during login: {e}")
        return False

def find_env_file() -> Optional[Path]:
    """Find the appropriate .env file"""
    possible_paths = [
        Path.cwd() / ".env",
        Path.home() / ".pypoe" / ".env",
    ]
    
    for path in possible_paths:
        if path.exists():
            print(f"Found existing env file: {path}")
            return path
    
    # Create a new one in the project root
    env_path = Path.cwd() / ".env"
    print(f"Will create new env file: {env_path}")
    return env_path

def update_env_file(tailscale_ip: str) -> bool:
    """Update the .env file with Tailscale configuration"""
    env_path = find_env_file()
    
    try:
        # Read existing content
        existing_content = {}
        if env_path.exists():
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        existing_content[key.strip()] = value.strip()
        
        # Update with Tailscale settings - use 0.0.0.0 to bind to all interfaces
        existing_content['PYPOE_HOST'] = '0.0.0.0'
        existing_content['PYPOE_PORT'] = existing_content.get('PYPOE_PORT', '8000')
        
        # Write back to file
        with open(env_path, 'w') as f:
            f.write("# PyPoe Configuration\n")
            f.write("# Generated by setup_tailscale.py\n\n")
            
            # POE API Key
            if 'POE_API_KEY' in existing_content:
                f.write(f"POE_API_KEY={existing_content['POE_API_KEY']}\n")
            else:
                f.write("# POE_API_KEY=your_poe_api_key_here\n")
            
            f.write("\n# Database\n")
            f.write(f"DATABASE_PATH={existing_content.get('DATABASE_PATH', 'pypoe_history.db')}\n")
            
            f.write("\n# Web Interface (Network Access Configuration)\n")
            f.write(f"PYPOE_HOST={existing_content['PYPOE_HOST']}\n")
            f.write(f"PYPOE_PORT={existing_content['PYPOE_PORT']}\n")
            
            # Web authentication
            if 'PYPOE_WEB_USERNAME' in existing_content:
                f.write(f"PYPOE_WEB_USERNAME={existing_content['PYPOE_WEB_USERNAME']}\n")
            if 'PYPOE_WEB_PASSWORD' in existing_content:
                f.write(f"PYPOE_WEB_PASSWORD={existing_content['PYPOE_WEB_PASSWORD']}\n")
            
            f.write("\n# Network Access (Tailscale + Local)\n")
            f.write("# PYPOE_HOST=0.0.0.0 allows access from:\n")
            f.write("# - Local: http://localhost:8000 or http://127.0.0.1:8000\n")
            f.write(f"# - Tailscale: http://{tailscale_ip}:8000\n")
            f.write("# - LAN: http://YOUR_LOCAL_IP:8000\n")
        
        print(f"Updated environment file: {env_path}")
        return True
        
    except Exception as e:
        print(f"Failed to update env file: {e}")
        return False

def set_current_session_env(tailscale_ip: str):
    """Set environment variables for current session"""
    os.environ['PYPOE_HOST'] = '0.0.0.0'
    os.environ['PYPOE_PORT'] = os.environ.get('PYPOE_PORT', '8000')
    
    print("Set environment variables for current session:")
    print(f"   PYPOE_HOST=0.0.0.0 (binds to all interfaces)")
    print(f"   PYPOE_PORT={os.environ['PYPOE_PORT']}")

def test_connection(tailscale_ip: str, port: str = "8000"):
    """Test if the connection setup would work"""
    print(f"\nTesting connection setup...")
    print(f"Web interface will be accessible at:")
    print(f"  • Local: http://localhost:{port}")
    print(f"  • Local: http://127.0.0.1:{port}")
    print(f"  • Tailscale: http://{tailscale_ip}:{port}")
    
    # Check if port is available on all interfaces
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', int(port)))
        sock.close()
        
        if result == 0:
            print(f"Port {port} is already in use")
        else:
            print(f"Port {port} is available")
            
    except Exception as e:
        print(f"ℹ️  Could not test port availability: {e}")

def print_next_steps(tailscale_ip: str, port: str = "8000"):
    """Print what to do next"""
    print("\n" + "=" * 60)
    print("Tailscale Setup Complete!")
    print("=" * 60)
    print("\nNext Steps:")
    print("1. Start PyPoe web interface:")
    print("   pypoe web")
    print()
    print("2. Access from multiple locations:")
    print(f"   • Local access: http://localhost:{port}")
    print(f"   • Local access: http://127.0.0.1:{port}")
    print(f"   • Tailscale access: http://{tailscale_ip}:{port}")
    print(f"   • LAN access: http://YOUR_LOCAL_IP:{port}")
    print()
    print("3. Optional: Set up web authentication for security:")
    print("   python scripts/setup/setup_webui.py")
    print()
    print("Tips:")
    print("- Server binds to 0.0.0.0 for maximum accessibility")
    print("- Make sure Tailscale is running on devices you want to access from")
    print("- Your Tailscale IP might change if you reinstall Tailscale")
    print("- Run this script again if you need to update the IP")
    print()
    print("Troubleshooting:")
    print("- If connection fails, check Tailscale status: tailscale status")
    print("- Verify IP address: tailscale ip")
    print("- Check firewall settings on your system")
    print("- For security, consider enabling web authentication")

def get_network_interfaces() -> Dict[str, str]:
    """Get all network interfaces and their IP addresses"""
    interfaces = {}
    
    try:
        # Get all network interfaces
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
    except Exception as e:
        print(f"Could not detect network interfaces: {e}")
    
    return interfaces

def print_network_info(tailscale_ip: str):
    """Print network interface information"""
    print("\nAvailable Network Interfaces:")
    print("-" * 40)
    
    interfaces = get_network_interfaces()
    
    # Always show localhost
    print("Localhost (same machine):")
    print("   • http://localhost:8000")
    print("   • http://127.0.0.1:8000")
    print()
    
    # Show Tailscale
    print("Tailscale (remote access):")
    print(f"   • http://{tailscale_ip}:8000")
    print()
    
    # Show other interfaces
    if interfaces:
        print("Other Network Interfaces:")
        for interface, ip in interfaces.items():
            if ip != tailscale_ip:  # Don't duplicate Tailscale IP
                print(f"   • {interface}: http://{ip}:8000")
    else:
        print("Other Network Interfaces:")
        print("   • Could not detect automatically")
    
    print()
    print("The server binds to 0.0.0.0:8000, so it's accessible from all interfaces above")

def main():
    """Main setup function"""
    print_header()
    
    # Step 1: Check if Tailscale is installed
    if not check_tailscale_installed():
        install_tailscale_instructions()
        return 1
    
    # Step 2: Check if Tailscale is running
    is_running, status = check_tailscale_status()
    
    if not is_running:
        print("\nTailscale needs to be started and logged in...")
        
        # Try to start Tailscale
        if start_tailscale():
            print("Waiting a moment for Tailscale to start...")
            import time
            time.sleep(2)
            
            # Check status again
            is_running, status = check_tailscale_status()
        
        # If still not running, try to log in
        if not is_running:
            if not login_tailscale():
                print("\nCould not set up Tailscale automatically.")
                print("Please set up Tailscale manually and run this script again.")
                return 1
    
    # Step 3: Get Tailscale IP
    tailscale_ip = get_tailscale_ip()
    if not tailscale_ip:
        print("Could not get Tailscale IP address")
        return 1
    
    # Step 4: Update configuration
    print(f"\nConfiguring PyPoe for Tailscale IP: {tailscale_ip}")
    
    if not update_env_file(tailscale_ip):
        print("Failed to update configuration file")
        return 1
    
    # Step 5: Set current session environment
    set_current_session_env(tailscale_ip)
    
    # Step 6: Test the setup
    port = os.environ.get('PYPOE_PORT', '8000')
    test_connection(tailscale_ip, port)
    
    # Step 7: Print next steps
    print_next_steps(tailscale_ip, port)
    
    # Step 8: Print network interface information
    print_network_info(tailscale_ip)
    
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nSetup cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1) 