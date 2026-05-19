"""
Path utilities for PyPoe setup scripts.

Provides consistent .env file path resolution across all setup scripts.
"""

import os
from pathlib import Path

def get_project_root():
    """
    Get the PyPoe project root directory.
    
    Returns the absolute path to the project root directory where .env should be located.
    This works regardless of which setup script calls it.
    
    Returns:
        str: Absolute path to the project root directory
    """
    # Get the directory containing this file (scripts/setup/)
    setup_dir = os.path.dirname(os.path.abspath(__file__))

    # Go up 2 levels: setup/ -> scripts/ -> project_root/
    project_root = os.path.dirname(os.path.dirname(setup_dir))

    return project_root

def get_env_file_path():
    """
    Get the path to the .env file in the project root.
    
    Returns:
        str: Absolute path to the .env file
    """
    return os.path.join(get_project_root(), '.env')

def ensure_env_file_exists():
    """
    Check if the .env file exists, and provide helpful instructions if not.
    
    Returns:
        tuple: (exists: bool, env_path: str)
    """
    env_path = get_env_file_path()
    exists = os.path.exists(env_path)
    
    if not exists:
        print(f"No .env file found at: {env_path}")
        print("Please run 'python scripts/setup/setup_credentials.py' first to set up your API key.")
    
    return exists, env_path 