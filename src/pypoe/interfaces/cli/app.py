#!/usr/bin/env python3
"""
PyPoe CLI Application

Main CLI interface for PyPoe chat functionality.
Provides commands for chatting, viewing history, and managing conversations.
"""

import asyncio
import argparse
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

from ...core.client import PoeChatClient
from ...core.config import get_config
from ...core.models import DEFAULT_CHAT_MODEL


class PyPoeCLI:
    """PyPoe Command Line Interface."""
    
    def __init__(self):
        self.config = get_config()
        self.client = None
        
    async def _get_client(self) -> PoeChatClient:
        """Get or create a client instance."""
        if self.client is None:
            self.client = PoeChatClient(config=self.config, enable_history=True)
        return self.client
    
    async def _close_client(self):
        """Close the client connection."""
        if self.client:
            await self.client.close()
            self.client = None
    
    def _format_timestamp(self, timestamp: str) -> str:
        """Format timestamp for display."""
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            return timestamp
    
    def _truncate_text(self, text: str, max_length: int = 50) -> str:
        """Truncate text for display."""
        if len(text) <= max_length:
            return text
        return text[:max_length-3] + "..."
    
    async def list_conversations(self, show_details: bool = False) -> None:
        """List all conversations with topics and metadata."""
        client = await self._get_client()
        
        try:
            conversations = await client.get_conversations()
            
            if not conversations:
                print("📭 No conversations found.")
                print("💡 Use 'pypoe-cli chat' to start a new conversation.")
                return
            
            print(f"📚 Found {len(conversations)} conversation(s):")
            print("=" * 80)
            
            for i, conv in enumerate(conversations, 1):
                conv_id = conv['id']
                title = conv.get('title', 'No title')
                topic = conv.get('topic', 'No topic')
                bot_name = conv.get('bot_name', 'Unknown bot')
                created_at = self._format_timestamp(conv.get('created_at', ''))
                msg_count = conv.get('message_count', 0)
                
                # Basic info
                print(f"{i:2d}. 📝 {title}")
                print(f"    🆔 ID: {conv_id}")
                print(f"    🏷️  Topic: {topic}")
                print(f"    🤖 Bot: {bot_name}")
                print(f"    📅 Created: {created_at}")
                print(f"    💬 Messages: {msg_count}")
                
                if show_details:
                    # Get latest message preview
                    try:
                        messages = await client.get_conversation_messages(conv_id)
                        if messages:
                            last_msg = messages[-1]
                            preview = self._truncate_text(last_msg['content'])
                            role_icon = "👤" if last_msg['role'] == 'user' else "🤖"
                            print(f"    💭 Last: {role_icon} {preview}")
                    except Exception as e:
                        print(f"    ⚠️  Error loading messages: {e}")
                
                print()
                
        finally:
            await self._close_client()
    
    async def show_conversation(self, conv_id: str) -> None:
        """Show detailed conversation history."""
        client = await self._get_client()
        
        try:
            # Get conversation details
            conversations = await client.get_conversations()
            conversation = next((c for c in conversations if c['id'] == conv_id), None)
            
            if not conversation:
                print(f"❌ Conversation with ID '{conv_id}' not found.")
                print("💡 Use 'pypoe-cli list' to see available conversations.")
                return
            
            # Display conversation metadata
            print("=" * 80)
            print(f"📝 Title: {conversation.get('title', 'No title')}")
            print(f"🏷️ Topic: {conversation.get('topic', 'No topic')}")
            print(f"🤖 Bot: {conversation.get('bot_name', 'Unknown')}")
            print(f"🔄 Mode: {conversation.get('chat_mode', 'chatbot')}")
            print(f"📅 Created: {self._format_timestamp(conversation.get('created_at', ''))}")
            print(f"🆔 ID: {conv_id}")
            print("=" * 80)
            
            # Get and display messages
            messages = await client.get_conversation_messages(conv_id)
            
            if not messages:
                print("💬 No messages in this conversation.")
                print("💡 Use 'pypoe-cli chat --conv-id' to start chatting.")
                return
            
            print(f"💬 Conversation History ({len(messages)} messages):")
            print("-" * 80)
            
            for i, msg in enumerate(messages, 1):
                role_icon = "👤" if msg['role'] == 'user' else "🤖"
                role_name = "You" if msg['role'] == 'user' else msg.get('bot_name', 'Assistant')
                timestamp = self._format_timestamp(msg.get('timestamp', ''))
                
                print(f"\n{i:2d}. {role_icon} {role_name} • {timestamp}")
                print("-" * 40)
                
                # Format message content
                content = msg['content']
                if len(content) > 500:
                    print(content[:500] + "\n... [content truncated] ...")
                else:
                    print(content)
                    
        finally:
            await self._close_client()
    
    async def start_chat(self, conv_id: Optional[str] = None, bot_name: str = DEFAULT_CHAT_MODEL,
                        title: Optional[str] = None) -> None:
        """Start or continue a chat conversation."""
        client = await self._get_client()
        
        try:
            is_new_conversation = False
            # Handle existing conversation
            if conv_id:
                conversations = await client.get_conversations()
                conversation = next((c for c in conversations if c['id'] == conv_id), None)

                if not conversation:
                    print(f"❌ Conversation with ID '{conv_id}' not found.")
                    return

                bot_name = conversation.get('bot_name', bot_name)
                topic = conversation.get('topic', 'No topic')
                conv_title = conversation.get('title', 'Untitled')

                print("=" * 60)
                print(f"💬 Continuing chat: {conv_title}")
                print(f"🏷️ Topic: {topic}")
                print(f"🤖 Bot: {bot_name}")
                print(f"🆔 ID: {conv_id}")
                print("=" * 60)

            else:
                is_new_conversation = True
                # Create new conversation
                if not title:
                    title = f"CLI Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}"

                conv_id = await client.create_conversation(
                    title=title,
                    bot_name=bot_name,
                    chat_mode="chatbot"
                )
                
                print("=" * 60)
                print(f"💬 New chat started: {title}")
                print(f"🤖 Bot: {bot_name}")
                print(f"🆔 ID: {conv_id}")
                print("=" * 60)
            
            print("Type your message and press Enter. Type 'quit', 'exit', or 'q' to end the chat.")
            print("Press Ctrl+C anytime to exit.")
            print()
            
            # Chat loop
            message_count = 0
            while True:
                try:
                    # Get user input
                    message = input("👤 You: ").strip()
                    
                    if message.lower() in ['quit', 'exit', 'q', '/quit', '/exit']:
                        print("👋 Chat ended!")
                        break
                    
                    if not message:
                        continue
                    
                    message_count += 1
                    print(f"🤖 {bot_name}: ", end='', flush=True)

                    # Generate topic from first message of a freshly created conversation
                    if message_count == 1 and is_new_conversation:
                        asyncio.create_task(
                            client.generate_and_update_topic(conv_id, message)
                        )
                    
                    # Send message and stream response
                    response = ""
                    async for chunk in client.send_message(
                        message=message,
                        bot_name=bot_name,
                        conversation_id=conv_id,
                        save_history=True
                    ):
                        response += chunk
                        print(chunk, end='', flush=True)
                    
                    print()  # New line after response
                    print()  # Extra spacing
                    
                except KeyboardInterrupt:
                    print("\n👋 Chat ended!")
                    break
                except EOFError:
                    print("\n👋 Chat ended!")
                    break
                except Exception as e:
                    print(f"\n❌ Error: {e}")
                    print("💡 Try again or type 'quit' to exit.")
                    
        finally:
            await self._close_client()
    
    async def delete_conversation(self, conv_id: str, confirm: bool = False) -> None:
        """Delete a conversation."""
        client = await self._get_client()
        
        try:
            # Check if conversation exists
            conversations = await client.get_conversations()
            conversation = next((c for c in conversations if c['id'] == conv_id), None)
            
            if not conversation:
                print(f"❌ Conversation with ID '{conv_id}' not found.")
                return
            
            title = conversation.get('title', 'Untitled')
            topic = conversation.get('topic', 'No topic')
            
            # Confirm deletion
            if not confirm:
                print(f"🗑️  Delete conversation: {title}")
                print(f"🏷️ Topic: {topic}")
                print(f"🆔 ID: {conv_id}")
                response = input("⚠️  Are you sure? Type 'yes' to confirm: ").strip().lower()
                if response != 'yes':
                    print("❌ Deletion cancelled.")
                    return
            
            # Delete conversation
            await client.delete_conversation(conv_id)
            print(f"✅ Conversation '{title}' deleted successfully.")
            
        finally:
            await self._close_client()
    
    async def select_interactive(self) -> None:
        """Interactive conversation selection and viewing."""
        client = await self._get_client()
        
        try:
            conversations = await client.get_conversations()
            
            if not conversations:
                print("📭 No conversations found.")
                print("💡 Use 'pypoe-cli chat' to start a new conversation.")
                return
            
            while True:
                print("\n📚 Select a conversation:")
                print("=" * 60)
                
                # Display conversations with numbers
                for i, conv in enumerate(conversations, 1):
                    topic = conv.get('topic', 'No topic')
                    title = conv.get('title', 'No title')
                    bot = conv.get('bot_name', 'Unknown bot')
                    msg_count = conv.get('message_count', 0)
                    created = self._format_timestamp(conv.get('created_at', ''))
                    
                    print(f"{i:2d}. 📝 {self._truncate_text(title, 35)}")
                    print(f"    🏷️ {topic} | 🤖 {bot} | 💬 {msg_count} msgs")
                    print(f"    📅 {created} | 🆔 {conv['id'][:8]}...")
                    print()
                
                print("Commands:")
                print("  [number] - View conversation history")
                print("  c[number] - Continue chatting in conversation")
                print("  q - Quit")
                
                try:
                    choice = input(f"\nEnter choice (1-{len(conversations)}, c1-c{len(conversations)}, or q): ").strip()
                    
                    if choice.lower() == 'q':
                        print("👋 Goodbye!")
                        break
                    
                    # Handle chat command (c1, c2, etc.)
                    if choice.lower().startswith('c') and len(choice) > 1:
                        try:
                            choice_num = int(choice[1:])
                            if 1 <= choice_num <= len(conversations):
                                selected_conv = conversations[choice_num - 1]
                                print(f"\n🚀 Starting chat with: {selected_conv.get('title', 'Untitled')}")
                                await self.start_chat(conv_id=selected_conv['id'])
                                # Refresh conversations list after chatting
                                conversations = await client.get_conversations()
                                continue
                            else:
                                print(f"❌ Please enter c1 to c{len(conversations)}")
                        except ValueError:
                            print("❌ Invalid format. Use c1, c2, etc.")
                        continue
                    
                    # Handle view command (just number)
                    try:
                        choice_num = int(choice)
                        if 1 <= choice_num <= len(conversations):
                            selected_conv = conversations[choice_num - 1]
                            await self.show_conversation(selected_conv['id'])
                            
                            # Ask what to do next
                            print("\nWhat would you like to do?")
                            print("  c - Continue chatting in this conversation")
                            print("  b - Back to conversation list")
                            print("  q - Quit")
                            
                            next_action = input("Choice: ").strip().lower()
                            if next_action == 'c':
                                await self.start_chat(conv_id=selected_conv['id'])
                                conversations = await client.get_conversations()
                            elif next_action == 'q':
                                print("👋 Goodbye!")
                                break
                            # 'b' or anything else goes back to list
                        else:
                            print(f"❌ Please enter a number between 1 and {len(conversations)}")
                    except ValueError:
                        print("❌ Please enter a valid number, c[number], or 'q'")
                        
                except KeyboardInterrupt:
                    print("\n👋 Goodbye!")
                    break
                    
        finally:
            await self._close_client()


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        prog='pypoe-cli',
        description='PyPoe Command Line Interface - Chat with AI models and manage conversations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  pypoe-cli chat                           # Start new chat with default bot
  pypoe-cli chat --bot "Claude-Sonnet-4.6" # Start chat with specific bot
  pypoe-cli chat --conv-id "conv_123"      # Continue existing conversation
  pypoe-cli list                           # List all conversations
  pypoe-cli list --details                 # List with message previews
  pypoe-cli show --conv-id "conv_123"      # Show conversation history
  pypoe-cli select                         # Interactive conversation browser
  pypoe-cli delete --conv-id "conv_123"    # Delete conversation
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Chat command
    chat_parser = subparsers.add_parser('chat', help='Start or continue a chat')
    chat_parser.add_argument('--conv-id', help='Conversation ID to continue')
    chat_parser.add_argument('--bot', default=DEFAULT_CHAT_MODEL, help=f'Bot to chat with (default: {DEFAULT_CHAT_MODEL})')
    chat_parser.add_argument('--title', help='Title for new conversation')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List all conversations')
    list_parser.add_argument('--details', action='store_true', help='Show message previews')
    
    # Show command
    show_parser = subparsers.add_parser('show', help='Show conversation history')
    show_parser.add_argument('--conv-id', required=True, help='Conversation ID to show')
    
    # Select command
    subparsers.add_parser('select', help='Interactive conversation selection')
    
    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a conversation')
    delete_parser.add_argument('--conv-id', required=True, help='Conversation ID to delete')
    delete_parser.add_argument('--yes', action='store_true', help='Skip confirmation')
    
    return parser


async def main():
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    cli = PyPoeCLI()
    
    try:
        if args.command == 'chat':
            await cli.start_chat(
                conv_id=args.conv_id,
                bot_name=args.bot,
                title=args.title
            )
        elif args.command == 'list':
            await cli.list_conversations(show_details=args.details)
        elif args.command == 'show':
            await cli.show_conversation(args.conv_id)
        elif args.command == 'select':
            await cli.select_interactive()
        elif args.command == 'delete':
            await cli.delete_conversation(args.conv_id, confirm=args.yes)
            
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main()) 