"""
Setup Credentials for PyPoe

This script helps you set up your Poe API credentials interactively.
It will create a .env file in the project root with your API key.
"""

import os
import sys
from _path_utils import get_env_file_path

def setup_credentials():
    """Interactive setup for Poe API credentials."""
    print("PyPoe Credentials Setup")
    print("=" * 30)
    print()
    
    # Get the .env file path using shared utility
    env_path = get_env_file_path()
    
    print("To use PyPoe, you need a Poe API key.")
    print("You can get one from: https://poe.com/api_key")
    print("(Note: You need a Poe subscription to access the API)")
    print()
    
    # Check if .env already exists
    if os.path.exists(env_path):
        print(f"Found existing .env file at: {env_path}")
        response = input("Do you want to update it? (y/N): ").strip().lower()
        if response not in ['y', 'yes']:
            print("Setup cancelled.")
            return
        print()
    
    # Get API key from user
    api_key = input("Enter your Poe API key: ").strip()
    
    if not api_key:
        print("❌ No API key provided. Setup cancelled.")
        return
    
    # Validate API key format (basic check)
    if not api_key.startswith('sk-') or len(api_key) < 20:
        print("⚠️  Warning: This doesn't look like a valid Poe API key.")
        print("   Poe API keys typically start with 'sk-' and are longer.")
        response = input("Continue anyway? (y/N): ").strip().lower()
        if response not in ['y', 'yes']:
            print("Setup cancelled.")
            return
    
    # Create .env content
    env_content = f"""# PyPoe Configuration
# Get your API key from: https://poe.com/api_key
POE_API_KEY={api_key}

# Optional: Default bot to use
# DEFAULT_BOT=GPT-4-Turbo

# Optional: Enable history by default
# ENABLE_HISTORY=true
"""
    
    try:
        # Write .env file
        with open(env_path, 'w') as f:
            f.write(env_content)
        
        print(f"✅ Credentials saved to: {env_path}")
        print()
        print("Setup complete! You can now use PyPoe:")
        print("1. Try the basic example: python examples/basic_usage.py")
        print("2. Use the CLI: pypoe --help")
        print("3. Import in your code: from pypoe import PoeChatClient")

    except Exception as e:
        print(f"❌ Error saving credentials: {e}")
        print("You can manually create a .env file with:")
        print(f"POE_API_KEY={api_key}")

def main():
    """Main entry point."""
    if len(sys.argv) > 1 and sys.argv[1] in ['-h', '--help']:
        print(__doc__)
        return
    
    setup_credentials()

if __name__ == "__main__":
    main() 