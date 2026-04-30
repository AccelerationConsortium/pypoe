"""
PyPoe Slack Bot Integration Module

A comprehensive Slack bot that integrates with Poe API to provide:
- Interactive model selection via Slack UI
- Token/compute point usage monitoring  
- Multi-turn conversations with persistent storage
- Error handling and rate limiting
- Admin controls and usage analytics
- Multiple conversation modes (DM, group, individual)

This module can be imported and used in various ways:
- As a standalone bot: python -m pypoe.slack_bot
- As part of a larger application: from pypoe.slack_bot import PyPoeSlackBot
- Via the CLI: pypoe slack-bot
"""

import asyncio
import os
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import logging
from dataclasses import dataclass, asdict

try:
    from slack_bolt.async_app import AsyncApp
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
    from slack_sdk.errors import SlackApiError
    SLACK_AVAILABLE = True
    SLACK_IMPORT_ERROR = None
except ImportError as exc:
    SLACK_AVAILABLE = False
    AsyncApp = None
    AsyncSocketModeHandler = None
    SlackApiError = Exception
    SLACK_IMPORT_ERROR = exc

from ...core.client import PoeChatClient
from ...core.history import HistoryManager
from ...core.config import get_config
from ...core.models import (
    CHAT_MODELS,
    DEFAULT_CHAT_MODEL,
    format_model_price_marker,
    get_model_price_markers,
)

# Configure logging
logger = logging.getLogger(__name__)

@dataclass
class SlackConversationContext:
    """Track Slack-specific conversation context"""
    conversation_id: str
    user_id: str
    channel_id: str
    channel_type: str  # 'im', 'public_channel', 'private_channel', 'group'
    chat_mode: str     # 'slack_dm', 'slack_channel_shared', 'slack_channel_individual'
    preferred_model: str = DEFAULT_CHAT_MODEL
    last_activity: datetime = None
    max_context_messages: int = 50  # Default message limit
    max_context_tokens: int = 12000  # Default token limit (conservative)
    
    def __post_init__(self):
        if self.last_activity is None:
            self.last_activity = datetime.now()

class PoeBotUsageTracker:
    """Track usage statistics."""
    
    def __init__(self):
        self.usage_data = {}
    
    def estimate_tokens(self, text: str) -> int:
        """Rough token estimation (1 token ≈ 4 characters)"""
        return len(text) // 4
    
    def track_usage(self, user_id: str, model: str, input_text: str, output_text: str):
        """Track usage for a user"""
        if user_id not in self.usage_data:
            self.usage_data[user_id] = {
                "total_messages": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "models_used": {},
                "daily_usage": {},
            }
        
        user_data = self.usage_data[user_id]
        today = datetime.now().strftime("%Y-%m-%d")
        
        input_tokens = self.estimate_tokens(input_text)
        output_tokens = self.estimate_tokens(output_text)
        # Update totals
        user_data["total_messages"] += 1
        user_data["total_input_tokens"] += input_tokens
        user_data["total_output_tokens"] += output_tokens
        
        # Update model usage
        if model not in user_data["models_used"]:
            user_data["models_used"][model] = 0
        user_data["models_used"][model] += 1
        
        # Update daily usage
        if today not in user_data["daily_usage"]:
            user_data["daily_usage"][today] = 0
        user_data["daily_usage"][today] += 1
    
    def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        """Get usage statistics for a user"""
        if user_id not in self.usage_data:
            return {
                "total_messages": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "models_used": {},
                "today_usage": 0,
            }
        
        user_data = self.usage_data[user_id]
        today = datetime.now().strftime("%Y-%m-%d")
        today_usage = user_data["daily_usage"].get(today, 0)
        
        return {
            **user_data,
            "today_usage": today_usage,
        }

class PyPoeSlackBot:
    """Main Slack bot class with persistent conversation storage"""
    
    def __init__(self, enable_history: bool = True):
        if not SLACK_AVAILABLE:
            raise ImportError(
                "Slack SDK not available. Install with: pip install slack-bolt slack-sdk"
            )
        
        # Initialize Slack app
        self.app = AsyncApp(
            token=os.environ.get("SLACK_BOT_TOKEN"),
            signing_secret=os.environ.get("SLACK_SIGNING_SECRET")
        )
        
        # Initialize PyPoe client
        self.config = get_config()
        self.poe_client = PoeChatClient(enable_history=False)  # We'll handle history ourselves
        
        # Use HistoryManager for persistent storage
        if enable_history:
            from pathlib import Path
            db_path = Path(self.config.database_path)
            self.history = HistoryManager(
                db_path=str(db_path),
                media_dir=str(db_path.parent / "slack_media"),
                enable_media=self.config.enable_media,
            )
        else:
            self.history = None
        
        # Conversation contexts (keyed by conversation_id)
        self.conversation_contexts: Dict[str, SlackConversationContext] = {}
        self.usage_tracker = PoeBotUsageTracker()
        
        # Available models
        self.available_models = []
        
        # Model-specific context limits
        self.model_context_limits = {
            # OpenAI Models
            "GPT-5.5": {"max_tokens": 100000, "max_messages": 200},
            "GPT-5.5-Pro": {"max_tokens": 100000, "max_messages": 200},
            "GPT-4-Turbo": {"max_tokens": 100000, "max_messages": 200},

            # Anthropic Models
            "Claude-Opus-4.7": {"max_tokens": 150000, "max_messages": 300},
            "Claude-Sonnet-4.6": {"max_tokens": 150000, "max_messages": 300},

            # Google Models
            "Gemini-3.1-Pro": {"max_tokens": 800000, "max_messages": 500},
            "Gemini-3-Flash": {"max_tokens": 800000, "max_messages": 500},

            # xAI Models
            "Grok-4": {"max_tokens": 100000, "max_messages": 200},

            # Other Models - Conservative defaults
            "Default": {"max_tokens": 12000, "max_messages": 40}
        }
        
        # Set up Slack event handlers
        self._setup_handlers()
    
    async def initialize(self):
        """Initialize the bot and fetch available models"""
        try:
            self.available_models = await self.poe_client.get_available_bots()
            if self.history:
                await self.history.initialize()
            logger.info(f"✅ Initialized with {len(self.available_models)} available models")
        except Exception as e:
            logger.error(f"❌ Failed to initialize: {e}")
            self.available_models = list(CHAT_MODELS)
    
    def _determine_conversation_strategy(self, channel_type: str, user_id: str, channel_id: str) -> tuple[str, str, str]:
        """
        Determine conversation strategy based on channel type and user preferences.
        
        Returns:
            (conversation_id, chat_mode, title)
        """
        if channel_type == "im":
            # Direct Message: Each user gets their own persistent conversation
            conversation_id = f"slack_dm_{user_id}"
            chat_mode = "slack_dm"
            title = f"Slack DM: @{user_id}"
            
        elif channel_type in ["public_channel", "private_channel", "group"]:
            # Group Channel: Two strategies possible
            
            # Strategy 1: Shared conversation (all users share context)
            conversation_id = f"slack_channel_{channel_id}"
            chat_mode = "slack_channel_shared"
            title = f"Slack Channel: {channel_id}"
            
            # Strategy 2: Individual conversations per user in channel (better privacy)
            # conversation_id = f"slack_channel_{channel_id}_{user_id}"
            # chat_mode = "slack_channel_individual"
            # title = f"Slack Channel: {channel_id} - @{user_id}"
            
        else:
            # Fallback
            conversation_id = f"slack_unknown_{user_id}_{channel_id}"
            chat_mode = "slack_unknown"
            title = f"Slack: @{user_id} in {channel_id}"
        
        return conversation_id, chat_mode, title
    
    async def _get_or_create_conversation_context(self, user_id: str, channel_id: str, channel_type: str) -> SlackConversationContext:
        """Get or create conversation context with database persistence."""
        
        conversation_id, chat_mode, title = self._determine_conversation_strategy(channel_type, user_id, channel_id)
        
        # Check if context already exists in memory
        if conversation_id in self.conversation_contexts:
            context = self.conversation_contexts[conversation_id]
            context.last_activity = datetime.now()
            return context
        
        # Check if conversation exists in database
        if self.history:
            try:
                conversations = await self.history.get_conversations()
                existing_conv = next((c for c in conversations if c['id'] == conversation_id), None)
                
                if not existing_conv:
                    # Create new conversation in database
                    await self.history.create_conversation(
                        title=title,
                        bot_name=DEFAULT_CHAT_MODEL,
                        chat_mode=chat_mode
                    )
                    # Note: We use our own conversation_id instead of the returned UUID
                    # This ensures consistent Slack-based IDs
                    
            except Exception as e:
                logger.error(f"Failed to check/create conversation in database: {e}")
        
        # Create context in memory
        context = SlackConversationContext(
            conversation_id=conversation_id,
            user_id=user_id,
            channel_id=channel_id,
            channel_type=channel_type,
            chat_mode=chat_mode
        )
        
        # Set appropriate context limits for the default model
        self._update_context_limits_for_model(context)
        
        self.conversation_contexts[conversation_id] = context
        return context
    
    def _setup_handlers(self):
        """Set up Slack event handlers"""
        
        @self.app.command("/poe")
        async def handle_poe_command(ack, command, respond):
            await ack()
            await self._handle_slash_command(command, respond)
        
        @self.app.event("app_mention")
        async def handle_mentions(event, say):
            await self._handle_mention(event, say)
        
        @self.app.event("message")
        async def handle_dm(event, say):
            # Only respond to DMs, not channel messages
            if event.get("channel_type") == "im":
                await self._handle_direct_message(event, say)
    
    async def _handle_slash_command(self, command, respond):
        """Handle /poe slash commands with conversation context"""
        user_id = command["user_id"]
        channel_id = command["channel_id"]
        channel_type = command.get("channel_type", "unknown")
        text = command.get("text", "").strip()

        async def respond_in_channel(message):
            """Publish slash-command output into Slack history."""
            if isinstance(message, dict):
                payload = {"response_type": "in_channel", **message}
            else:
                payload = {"response_type": "in_channel", "text": message}
            await respond(payload)
        
        try:
            command_text = f"/poe {text}".strip()
            await respond_in_channel(f"📝 <@{user_id}> ran `{command_text}`")

            # Get conversation context
            context = await self._get_or_create_conversation_context(user_id, channel_id, channel_type)
            
            if not text or text == "help":
                await respond_in_channel(self._get_help_message(context))
                return
            
            parts = text.split(" ", 1)
            cmd = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""
            
            if cmd == "models":
                await respond_in_channel(self._get_models_message())
            
            elif cmd == "set-model":
                if not args:
                    await respond_in_channel("❌ Please specify a model. Use `/poe models` to see available options.")
                    return
                await self._set_user_model(context, args, respond_in_channel)
            
            elif cmd == "chat":
                if not args:
                    await respond_in_channel("❌ Please provide a message. Example: `/poe chat Hello!`")
                    return
                await self._handle_chat_message(context, args, respond_in_channel)
            
            elif cmd == "usage":
                await respond_in_channel(self._get_usage_message(user_id))
            
            elif cmd == "reset":
                await self._reset_conversation(context, respond_in_channel)
            
            elif cmd == "context":
                await respond_in_channel(self._get_context_info(context))
            
            elif cmd == "stats":
                await respond_in_channel(await self._get_context_stats(context))
            
            else:
                await respond_in_channel(f"❌ Unknown command: `{cmd}`. Use `/poe help` for available commands.")
        
        except Exception as e:
            logger.error(f"Error handling command: {e}")
            await respond_in_channel(f"❌ Error: {str(e)}")
    
    async def _handle_mention(self, event, say):
        """Handle @poe_bot mentions in channels"""
        user_id = event["user"]
        channel_id = event["channel"]
        channel_type = event.get("channel_type", "public_channel")
        text = event.get("text", "")
        
        # Remove the bot mention from the text
        text = " ".join([word for word in text.split() if not word.startswith("<@")])
        
        if not text.strip():
            context = await self._get_or_create_conversation_context(user_id, channel_id, channel_type)
            await say(self._get_help_message(context))
            return
        
        context = await self._get_or_create_conversation_context(user_id, channel_id, channel_type)
        await self._handle_chat_message(context, text, say)
    
    async def _handle_direct_message(self, event, say):
        """Handle direct messages to the bot"""
        user_id = event["user"]
        channel_id = event["channel"]
        text = event.get("text", "")
        
        if not text.strip():
            context = await self._get_or_create_conversation_context(user_id, channel_id, "im")
            await say(self._get_help_message(context))
            return
        
        context = await self._get_or_create_conversation_context(user_id, channel_id, "im")
        await self._handle_chat_message(context, text, say)
    
    async def _handle_chat_message(self, context: SlackConversationContext, text: str, respond_func):
        """Handle a chat message with persistent conversation history"""
        try:
            # Update last activity
            context.last_activity = datetime.now()
            
            # Send "thinking" indicator
            await respond_func("🤖 Thinking...")
            
            # Get response from PyPoe with conversation history
            if self.history:
                # Load existing conversation history
                try:
                    existing_messages = await self.history.get_conversation_messages(context.conversation_id)
                    
                    # Convert to API format
                    conversation_messages = []
                    for msg in existing_messages:
                        conversation_messages.append({
                            'role': msg['role'],
                            'content': msg['content']
                        })
                    
                    # Add new user message
                    conversation_messages.append({
                        'role': 'user',
                        'content': text
                    })
                    
                    # Apply intelligent context truncation
                    conversation_messages = self._truncate_conversation_context(
                        conversation_messages, 
                        context.preferred_model
                    )
                    
                    # Save user message to database (always save, even if truncated from context)
                    await self.history.add_message(
                        conversation_id=context.conversation_id,
                        role="user",
                        content=text
                    )
                    
                except Exception as e:
                    logger.error(f"Failed to load conversation history: {e}")
                    # Fallback to single message
                    conversation_messages = [{'role': 'user', 'content': text}]
            else:
                conversation_messages = [{'role': 'user', 'content': text}]
            
            # Get bot response
            full_response = ""
            async for chunk in self.poe_client.send_conversation(
                messages=conversation_messages,
                bot_name=context.preferred_model,
                save_history=False  # We handle our own history
            ):
                full_response += chunk
            
            # Save bot response to database
            if self.history and full_response:
                await self.history.add_message(
                    conversation_id=context.conversation_id,
                    role="assistant",
                    content=full_response,
                    bot_name=context.preferred_model
                )
            
            # Track usage
            self.usage_tracker.track_usage(context.user_id, context.preferred_model, text, full_response)
            
            # Format response for Slack
            response_text = self._format_response_for_slack(
                full_response, 
                context.preferred_model, 
                context.chat_mode
            )
            
            await respond_func(response_text)
            
        except Exception as e:
            logger.error(f"Error handling chat message: {e}")
            await respond_func(f"❌ Sorry, I encountered an error: {str(e)}")
    
    async def _set_user_model(self, context: SlackConversationContext, model: str, respond_func):
        """Set the preferred model for a conversation context"""
        # Find the closest matching model
        model_lower = model.lower()
        matched_model = None
        
        for available_model in self.available_models:
            if model_lower in available_model.lower():
                matched_model = available_model
                break
        
        if not matched_model:
            available_list = "\n".join([f"• {model}" for model in self.available_models[:10]])
            await respond_func(
                f"❌ Model '{model}' not found.\n\n**Available models:**\n{available_list}\n\n"
                f"Use `/poe models` to see all {len(self.available_models)} available models."
            )
            return
        
        # Set the model
        old_model = context.preferred_model
        context.preferred_model = matched_model
        self._update_context_limits_for_model(context)
        
        await respond_func(
            f"✅ Model changed from **{old_model}** to **{matched_model}**\n"
            f"💰 Price marker: {format_model_price_marker(matched_model)}\n"
            f"📍 Context: {context.chat_mode}"
        )
    
    async def _reset_conversation(self, context: SlackConversationContext, respond_func):
        """Reset the conversation history for a context"""
        try:
            if self.history:
                # Delete conversation from database and recreate
                await self.history.delete_conversation(context.conversation_id)
                
                # Recreate conversation
                conversation_id, chat_mode, title = self._determine_conversation_strategy(
                    context.channel_type, context.user_id, context.channel_id
                )
                await self.history.create_conversation(
                    title=title,
                    bot_name=context.preferred_model,
                    chat_mode=chat_mode
                )
            
            await respond_func(f"✅ Conversation reset\n📍 Context: {context.chat_mode}")
            
        except Exception as e:
            logger.error(f"Error resetting conversation: {e}")
            await respond_func(f"❌ Error resetting conversation: {str(e)}")
    
    def _get_context_info(self, context: SlackConversationContext) -> str:
        """Get information about the current conversation context"""
        return f"""
📍 **Conversation Context**

**Type:** {context.chat_mode}
**User:** {context.user_id}
**Channel:** {context.channel_id}
**Conversation ID:** `{context.conversation_id}`
**Model:** {context.preferred_model}
**Last Activity:** {context.last_activity.strftime('%Y-%m-%d %H:%M:%S')}

**Context Limits:**
• Max Messages: {context.max_context_messages}
• Max Tokens: {context.max_context_tokens:,}

**Context Explanation:**
• `slack_dm`: Direct message with individual context
• `slack_channel_individual`: Channel message with per-user context
• `slack_channel_shared`: Channel message with shared context (all users)
"""
    
    async def _get_context_stats(self, context: SlackConversationContext) -> str:
        """Get detailed conversation statistics and context usage"""
        if not self.history:
            return "📊 **Context Stats**\n\nHistory disabled - no statistics available."
        
        try:
            # Get all messages for this conversation
            all_messages = await self.history.get_conversation_messages(context.conversation_id)
            
            if not all_messages:
                return f"""
📊 **Context Stats**

**Conversation:** `{context.conversation_id}`
**Model:** {context.preferred_model}

**Message Count:** 0
**Status:** New conversation

**Model Limits:**
• Max Messages: {context.max_context_messages}
• Max Tokens: {context.max_context_tokens:,}
"""
            
            # Convert to API format for token estimation
            api_messages = []
            for msg in all_messages:
                api_messages.append({
                    'role': msg['role'], 
                    'content': msg['content']
                })
            
            # Estimate tokens for full conversation
            total_tokens = sum(self._estimate_message_tokens(msg) for msg in api_messages)
            
            # See what would be included with current limits
            truncated_messages = self._truncate_conversation_context(api_messages, context.preferred_model)
            active_tokens = sum(self._estimate_message_tokens(msg) for msg in truncated_messages)
            
            # Count message types
            user_messages = len([m for m in all_messages if m['role'] == 'user'])
            assistant_messages = len([m for m in all_messages if m['role'] == 'assistant'])
            
            # Calculate percentages
            token_usage_pct = (active_tokens / context.max_context_tokens) * 100 if context.max_context_tokens > 0 else 0
            message_usage_pct = (len(truncated_messages) / context.max_context_messages) * 100 if context.max_context_messages > 0 else 0
            
            truncation_info = ""
            if len(truncated_messages) < len(all_messages):
                truncated_count = len(all_messages) - len(truncated_messages)
                truncation_info = f"\n⚠️ **{truncated_count} messages truncated** from context"
            
            return f"""
📊 **Context Stats**

**Conversation:** `{context.conversation_id}`
**Model:** {context.preferred_model}

**Total Messages:** {len(all_messages)} ({user_messages} user, {assistant_messages} assistant)
**Active Context:** {len(truncated_messages)} messages
**Total Tokens:** ≈{total_tokens:,}
**Active Tokens:** ≈{active_tokens:,} ({token_usage_pct:.1f}% of limit)

**Model Limits:**
• Max Messages: {context.max_context_messages} ({message_usage_pct:.1f}% used)
• Max Tokens: {context.max_context_tokens:,} ({token_usage_pct:.1f}% used)

**Status:** {"🟢 Within limits" if len(truncated_messages) == len(all_messages) else "🟡 Context truncated"}{truncation_info}

💡 Use `/poe reset` to clear history if context becomes too large
"""
            
        except Exception as e:
            logger.error(f"Error getting context stats: {e}")
            return f"❌ Error retrieving context statistics: {str(e)}"
    
    def _get_help_message(self, context: SlackConversationContext) -> str:
        """Get help message with context information"""
        return f"""
🤖 **PyPoe Slack Bot - Help**

**Current Context:** {context.chat_mode}

**Slash Commands:**
• `/poe help` - Show this help
• `/poe models` - List available AI models
• `/poe chat <message>` - Send a message to the bot
• `/poe set-model <model>` - Set your preferred model
• `/poe usage` - Check your token usage stats
• `/poe reset` - Reset conversation history
• `/poe context` - Show conversation context info
• `/poe stats` - Show detailed context statistics

**Direct Interaction:**
• `@poe_bot <message>` - Mention the bot in any channel
• Send direct messages to the bot

**Features:**
• 🧠 Access to the configured chat-only Poe models
• 💬 Multi-turn conversations with persistent context
• 📊 Usage tracking and compute point monitoring
• 🔄 Model switching mid-conversation
• 💾 Database-backed conversation history
• 👥 Smart context isolation (per-user or shared)
• ⚡ Intelligent context management (auto-truncation)
• 📈 Real-time context statistics and monitoring

**Current Status:** ✅ Connected to Poe API
**Your Model:** {context.preferred_model}
"""
    
    def _get_models_message(self) -> str:
        """Get available models message"""
        if not self.available_models:
            return "❌ No models available. Please check the bot configuration."

        def format_price_row(label: str, marker: str, width: int = 48) -> str:
            """Wrap long price markers with continuation aligned under '$'."""
            prefix = "    In:  " if label == "In" else "    Out: "
            continuation_prefix = " " * len(prefix)
            chunks = [marker[i:i + width] for i in range(0, len(marker), width)] or ["-"]
            lines = [f"{prefix}{chunks[0]}"]
            lines.extend(f"{continuation_prefix}{chunk}" for chunk in chunks[1:])
            return "\n".join(lines)
        
        # Group models by provider
        providers = {}
        for model in self.available_models:
            if "GPT" in model or "gpt" in model:
                provider = "OpenAI"
            elif "Claude" in model:
                provider = "Anthropic"
            elif "Gemini" in model or "PaLM" in model:
                provider = "Google"
            elif "Llama" in model:
                provider = "Meta"
            else:
                provider = "Other"
            
            if provider not in providers:
                providers[provider] = []
            providers[provider].append(model)
        
        message = f"🤖 **Available AI Models ({len(self.available_models)} total)**\n\n"
        
        for provider, models in providers.items():
            message += f"**{provider}:**\n"
            message += "```\n"
            for model in models[:5]:  # Limit to first 5 per provider
                input_marker, output_marker = get_model_price_markers(model)
                message += f"{model}\n"
                message += format_price_row("In", input_marker) + "\n"
                message += format_price_row("Out", output_marker) + "\n"
            message += "```\n"
            if len(models) > 5:
                message += f"• ... and {len(models) - 5} more\n"
            message += "\n"
        
        message += (
            "💡 Price markers use one `$` per $1.00 per 1M tokens "
            "(In/Out).\n"
            "💡 Use `/poe set-model <model-name>` to switch models"
        )
        return message
    
    def _get_usage_message(self, user_id: str) -> str:
        """Get usage statistics message"""
        stats = self.usage_tracker.get_user_stats(user_id)
        
        if stats["total_messages"] == 0:
            return "📊 **Your Usage Stats**\n\nNo messages sent yet. Try `/poe chat Hello!`"
        
        # Format top models
        top_models = sorted(
            stats["models_used"].items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:5]
        
        top_models_text = "\n".join([
            f"• {model}: {count} messages" 
            for model, count in top_models
        ])
        
        return f"""
📊 **Your Usage Stats**

**Total Activity:**
• Messages sent: {stats['total_messages']:,}
• Estimated input tokens: {stats['total_input_tokens']:,}
• Estimated output tokens: {stats['total_output_tokens']:,}
**Today's Usage:**
• Messages: {stats['today_usage']}

**Top Models Used:**
{top_models_text}

💡 *Each conversation context maintains separate history*
"""
    
    def _format_response_for_slack(self, response: str, model: str, chat_mode: str) -> str:
        """Format the AI response for Slack with context info"""
        # Truncate very long responses
        if len(response) > 3000:
            response = response[:2950] + "\n\n... *(response truncated)*"
        
        # Add context indicator for clarity
        context_indicator = {
            "slack_dm": "🔒 DM",
            "slack_channel_individual": "👤 Individual",
            "slack_channel_shared": "👥 Shared",
        }.get(chat_mode, "❓ Unknown")
        
        return f"🤖 **{model}** {context_indicator}\n\n{response}"
    
    def _estimate_message_tokens(self, message: Dict[str, str]) -> int:
        """Estimate tokens for a message (rough approximation)"""
        content = message.get('content', '')
        role = message.get('role', '')
        
        # Rough estimation: 1 token ≈ 4 characters for text
        # Add overhead for role, formatting, etc.
        base_tokens = len(content) // 4
        overhead_tokens = 10  # Role, formatting overhead
        
        return base_tokens + overhead_tokens
    
    def _get_model_limits(self, model_name: str) -> Dict[str, int]:
        """Get context limits for a specific model"""
        # Try exact match first
        if model_name in self.model_context_limits:
            return self.model_context_limits[model_name]
        
        # Try partial matches for model families
        for known_model, limits in self.model_context_limits.items():
            if known_model != "Default" and any(
                part in model_name for part in known_model.split("-")[:2]
            ):
                return limits
        
        # Fallback to conservative defaults
        return self.model_context_limits["Default"]
    
    def _truncate_conversation_context(self, messages: List[Dict[str, str]], model_name: str) -> List[Dict[str, str]]:
        """
        Intelligently truncate conversation context to fit model limits.
        
        Strategy:
        1. Always keep the most recent messages
        2. Try to preserve conversation flow
        3. Keep important context (user questions, model switches)
        4. Respect both token and message count limits
        """
        if not messages:
            return messages
        
        limits = self._get_model_limits(model_name)
        max_tokens = limits["max_tokens"]
        max_messages = limits["max_messages"]
        
        # If we're within limits, return as-is
        if len(messages) <= max_messages:
            total_tokens = sum(self._estimate_message_tokens(msg) for msg in messages)
            if total_tokens <= max_tokens:
                return messages
        
        # Need to truncate - use sliding window approach
        # Always keep the most recent messages, working backwards
        truncated_messages = []
        total_tokens = 0
        
        # Start from the end (most recent) and work backwards
        for message in reversed(messages):
            message_tokens = self._estimate_message_tokens(message)
            
            # Check if adding this message would exceed limits
            if (len(truncated_messages) >= max_messages or 
                total_tokens + message_tokens > max_tokens):
                break
            
            truncated_messages.insert(0, message)  # Insert at beginning
            total_tokens += message_tokens
        
        # Ensure we have at least some context
        if not truncated_messages and messages:
            # If even the most recent message exceeds limits, take it anyway
            # The API will handle the overflow
            truncated_messages = messages[-1:]
        
        # Log truncation for debugging
        if len(truncated_messages) < len(messages):
            logger.info(
                f"Context truncated for {model_name}: "
                f"{len(messages)} → {len(truncated_messages)} messages "
                f"(≈{total_tokens} tokens)"
            )
        
        return truncated_messages
    
    def _update_context_limits_for_model(self, context: SlackConversationContext):
        """Update context limits when model changes"""
        limits = self._get_model_limits(context.preferred_model)
        context.max_context_tokens = limits["max_tokens"]
        context.max_context_messages = limits["max_messages"]
    
    async def run(self):
        """Run the Slack bot"""
        await self.initialize()
        
        # Use Socket Mode for local development
        if os.environ.get("SLACK_SOCKET_MODE", "true").lower() == "true":
            handler = AsyncSocketModeHandler(self.app, os.environ.get("SLACK_APP_TOKEN"))
            await handler.start_async()
        else:
            # Use HTTP mode for production
            await self.app.async_start(port=int(os.environ.get("PORT", 3000)))
    
    async def close(self):
        """Clean up resources"""
        await self.poe_client.close()
        if self.history:
            await self.history.close()

async def main():
    """Main entry point"""
    import sys

    # Load the same .env candidates used by the web/CLI config before checking
    # Slack-specific environment variables.
    try:
        get_config()
    except ValueError:
        # get_config() still loads .env before validating POE_API_KEY. Keep
        # going so the required-variable report can show all missing values.
        pass

    # Check required environment variables
    required_vars = ["SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "POE_API_KEY"]
    if os.environ.get("SLACK_SOCKET_MODE", "true").lower() == "true":
        required_vars.append("SLACK_APP_TOKEN")
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        print(f"❌ Missing environment variables: {', '.join(missing_vars)}")
        print("\n📋 Setup Instructions:")
        print("1. Create a Slack app at https://api.slack.com/apps")
        print("2. Set environment variables:")
        print("   export SLACK_BOT_TOKEN=xoxb-your-bot-token")
        print("   export SLACK_SIGNING_SECRET=your-signing-secret")
        print("   export SLACK_APP_TOKEN=xapp-your-app-token  # For Socket Mode")
        print("   export POE_API_KEY=your-poe-api-key")
        print("3. Run: pypoe slack")
        return
    
    if not SLACK_AVAILABLE:
        print("❌ Slack SDK not installed. Install with:")
        print("   pip install slack-bolt slack-sdk aiohttp")
        if SLACK_IMPORT_ERROR:
            print(f"   Import error: {SLACK_IMPORT_ERROR}")
        return
    
    print("🚀 Starting PyPoe Slack Bot...")
    print("📋 Configuration:")
    print(f"   POE_API_KEY: {'✅ Set' if os.environ.get('POE_API_KEY') else '❌ Missing'}")
    print(f"   SLACK_BOT_TOKEN: {'✅ Set' if os.environ.get('SLACK_BOT_TOKEN') else '❌ Missing'}")
    print(f"   Socket Mode: {os.environ.get('SLACK_SOCKET_MODE', 'true')}")
    print("   Database: HistoryManager with media support")
    print("   Conversation Strategy: Individual contexts per user")
    print("   Context Management: Intelligent truncation with model-specific limits")
    
    bot = PyPoeSlackBot()
    
    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\n👋 Shutting down PyPoe Slack Bot...")
        await bot.close()
    except Exception as e:
        print(f"❌ Error running bot: {e}")
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main()) 