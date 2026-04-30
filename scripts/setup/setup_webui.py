"""
Setup Web UI Credentials for PyPoe

This script helps you set up username and password for the PyPoe web interface.
It will update your .env file with web authentication credentials.

Perfect for Tailscale deployments where you want password-protected access
to your PyPoe web interface from other devices on your network.
"""

import os
import sys
import getpass
import ipaddress
import subprocess
from _path_utils import get_env_file_path, ensure_env_file_exists

def get_tailscale_ip():
    """Try to detect the Tailscale IP address automatically."""
    try:
        # Run tailscale ip to get the IP
        result = subprocess.run(['tailscale', 'ip'], capture_output=True, text=True)
        if result.returncode == 0:
            ip = result.stdout.strip()
            if ip:
                return ip
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None

def validate_ip_address(ip):
    """Validate that the provided IP address is valid."""
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False

def setup_webui_credentials():
    """Interactive setup for PyPoe Web UI credentials."""
    print("PyPoe Web UI Setup")
    print("=" * 25)
    print()
    
    print("Setting up authentication for PyPoe web interface.")
    print("This is recommended for remote access via Tailscale or other networks.")
    print()
    
    # Check if .env exists using shared utility
    exists, env_path = ensure_env_file_exists()
    if not exists:
        return
    
    # Read existing .env content
    try:
        with open(env_path, 'r') as f:
            existing_content = f.read()
    except Exception as e:
        print(f"❌ Error reading .env file: {e}")
        return
    
    print("Web UI Authentication Setup")
    print("-" * 30)
    
    # Get username
    username = input("Enter web UI username (default: admin): ").strip()
    if not username:
        username = "admin"
    
    # Get password
    print(f"Enter password for user '{username}':")
    password = getpass.getpass("Password: ").strip()
    
    if not password:
        print("❌ Password cannot be empty. Setup cancelled.")
        return
    
    # Confirm password
    confirm_password = getpass.getpass("Confirm password: ").strip()
    
    if password != confirm_password:
        print("❌ Passwords don't match. Setup cancelled.")
        return
    
    print()
    print("Network Configuration")
    print("-" * 20)
    
    # Try to detect Tailscale IP
    tailscale_ip = get_tailscale_ip()
    if tailscale_ip:
        print(f"🎉 Detected Tailscale IP: {tailscale_ip}")
        use_tailscale = input("Use this IP for web server? (Y/n): ").strip().lower()
        if use_tailscale in ['', 'y', 'yes']:
            host_ip = tailscale_ip
        else:
            host_ip = None
    else:
        print("Tailscale IP not detected automatically.")
        host_ip = None
    
    # Manual IP entry if needed
    if not host_ip:
        print("Enter the IP address to bind the web server to:")
        print("- For local access only: 127.0.0.1 or localhost")
        print("- For network access: your Tailscale IP (100.x.x.x) or LAN IP")
        print("- For all interfaces: 0.0.0.0")
        
        host_input = input("Host IP (default: 127.0.0.1): ").strip()
        if not host_input:
            host_ip = "127.0.0.1"
        else:
            if host_input == "localhost":
                host_ip = "127.0.0.1"
            elif validate_ip_address(host_input):
                host_ip = host_input
            else:
                print(f"❌ Invalid IP address: {host_input}")
                return
    
    # Get port
    port_input = input("Web server port (default: 8000): ").strip()
    if port_input:
        try:
            port = int(port_input)
            if not (1 <= port <= 65535):
                raise ValueError("Port out of range")
        except ValueError:
            print("❌ Invalid port number. Using default 8000.")
            port = 8000
    else:
        port = 8000
    
    print()
    print("Configuration Summary")
    print("-" * 20)
    print(f"Username: {username}")
    print(f"Password: {'*' * len(password)}")
    print(f"Host: {host_ip}")
    print(f"Port: {port}")
    print(f"Access URL: http://{host_ip}:{port}")
    print()
    
    confirm = input("Save this configuration? (Y/n): ").strip().lower()
    if confirm not in ['', 'y', 'yes']:
        print("Setup cancelled.")
        return
    
    # Update .env file
    try:
        # Remove existing web UI settings if they exist
        lines = existing_content.split('\n')
        filtered_lines = []
        
        for line in lines:
            if not any(line.startswith(prefix) for prefix in [
                'PYPOE_WEB_USERNAME=',
                'PYPOE_WEB_PASSWORD=',
                'PYPOE_HOST=',
                'PYPOE_PORT='
            ]):
                filtered_lines.append(line)
        
        # Add web UI configuration
        if not existing_content.endswith('\n') and existing_content.strip():
            filtered_lines.append('')
        
        filtered_lines.extend([
            '# Web UI Authentication',
            f'PYPOE_WEB_USERNAME={username}',
            f'PYPOE_WEB_PASSWORD={password}',
            '',
            '# Web Server Configuration', 
            f'PYPOE_HOST={host_ip}',
            f'PYPOE_PORT={port}',
            ''
        ])
        
        # Write updated content
        with open(env_path, 'w') as f:
            f.write('\n'.join(filtered_lines))
        
        print(f"✅ Web UI configuration saved to: {env_path}")
        print()
        print("Setup complete! You can now start the web interface:")
        print(f"   pypoe web")
        print()
        print(f"Access it at: http://{host_ip}:{port}")
        if host_ip.startswith('100.'):
            print("💡 Make sure Tailscale is running on devices you want to access from")
        print()
        print("Command examples:")
        print(f"   pypoe web                    # Use settings from .env")
        print(f"   pypoe web --host {host_ip}    # Override host")
        print(f"   pypoe web --port {port}      # Override port")

    except Exception as e:
        print(f"❌ Error updating .env file: {e}")
        print("You can manually add these lines to your .env file:")
        print(f"PYPOE_WEB_USERNAME={username}")
        print(f"PYPOE_WEB_PASSWORD={password}")
        print(f"PYPOE_HOST={host_ip}")
        print(f"PYPOE_PORT={port}")

def main():
    """Main entry point."""
    if len(sys.argv) > 1 and sys.argv[1] in ['-h', '--help']:
        print(__doc__)
        return
    
    setup_webui_credentials()

if __name__ == "__main__":
    main() 