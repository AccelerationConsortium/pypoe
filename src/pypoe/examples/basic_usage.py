import asyncio
import sys
import os

from pypoe import PoeChatClient, HistoryManager
from pypoe.core.config import get_config
from pathlib import Path

async def main():
    """
    Basic usage example for PyPoe using the official Poe API.
    """
    print("PyPoe - Basic Usage Example")
    print("=" * 40)

    try:
        # Initialize the client with history enabled
        print("Initializing Poe client with history...")
        client = PoeChatClient(enable_history=True)
        
        # Get available bots
        bots = await client.get_available_bots()
        print(f"Available bots: {', '.join(bots)}")
        
        # Send a simple message
        print("\nSending message to GPT-3.5-Turbo...")
        message = "Hello! Can you explain what the Poe API is in one sentence?"
        
        print(f"User: {message}")
        print("Bot: ", end="", flush=True)
        
        async for chunk in client.send_message(message, bot_name="GPT-3.5-Turbo", save_history=True):
            print(chunk, end="", flush=True)
        print("\n")
        
        # Demonstrate multi-turn conversation
        print("Demonstrating multi-turn conversation...")
        conversation = [
            {"role": "user", "content": "What's 2+2?"},
            {"role": "bot", "content": "2+2 equals 4."},
            {"role": "user", "content": "What about 2+2+2?"}
        ]
        
        print("Multi-turn conversation:")
        for msg in conversation:
            print(f"{msg['role'].title()}: {msg['content']}")
        
        print("Bot: ", end="", flush=True)
        async for chunk in client.send_conversation(conversation, bot_name="GPT-3.5-Turbo", save_history=True):
            print(chunk, end="", flush=True)
        print("\n")
        
        # Show conversation history
        print("Conversation history:")
        conversations = await client.get_conversations()
        for conv in conversations[-2:]:  # Show last 2 conversations
            print(f"- {conv['title']} (ID: {conv['id']})")
        
        # Demonstrate direct HistoryManager usage
        print("\nDemonstrating direct HistoryManager usage...")
        
        config = get_config()
        media_dir = Path(config.database_path).parent / "media"
        
        manager = HistoryManager(
            db_path=str(config.database_path),
            media_dir=str(media_dir)
        )
        await manager.initialize()
        print(f"History database location: {manager.db_path}")
        
        # Show enhanced features if available
        if hasattr(manager, 'get_media_stats'):
            try:
                media_stats = await manager.get_media_stats()
                print(f"Enhanced storage: {media_stats.get('total_files', 0)} media files")
            except Exception:
                print("Enhanced storage: Available but no media files yet")
        else:
            print("Enhanced storage: Not available")
        
        # Clean up
        await client.close()
        print("\n✅ Example completed successfully!")
        
    except ValueError as e:
        print(f"\n❌ Configuration Error: {e}")
        print("\nTo fix this:")
        print("1. Run: python user_scripts/setup_credentials.py")
        print("2. Or manually create a .env file with your POE_API_KEY")
        print("3. Get your API key from: https://poe.com/api_key")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nTroubleshooting:")
        print("1. Make sure you have a Poe subscription")
        print("2. Verify your API key is correct")
        print("3. Check your internet connection")

if __name__ == "__main__":
    asyncio.run(main()) 