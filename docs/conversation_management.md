# Conversation and Message Management in PyPoe

This document explains how PyPoe handles conversations, messages, and maintains context continuity when interacting with Poe bots.

## Table of Contents

- [Overview](#overview)
- [Database Schema](#database-schema)
- [API Methods](#api-methods)
- [Conversation Context Flow](#conversation-context-flow)
- [Implementation Details](#implementation-details)
- [Usage Examples](#usage-examples)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

## Overview

PyPoe provides persistent conversation management with full context continuity, ensuring that AI bots remember previous messages within a conversation. This matches the behavior users expect from the official Poe web interface.

### Key Features

- **Persistent Storage**: Conversations and messages stored in SQLite database
- **Context Continuity**: Bots remember previous messages in the same conversation
- **Conversation Isolation**: Each conversation maintains separate context
- **Automatic History**: Messages automatically saved and retrieved
- **Bot Identity Tracking**: Conversations track which AI model was used

## Database Schema

PyPoe uses two main tables to store conversation data:

### `conversations` Table

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,              -- UUID (e.g., "a1b2c3d4-e5f6-7890...")
    title TEXT NOT NULL,              -- Human-readable title
    bot_name TEXT,                    -- AI model used (optional)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Fields:**
- `id`: Unique UUID identifier for the conversation
- `title`: User-friendly name (e.g., "Chat with GPT-4")
- `bot_name`: Which AI model is used (e.g., "GPT-4", "Claude-3.5-Sonnet")
- `created_at`: When conversation was started
- `updated_at`: Last modification time

### `messages` Table

```sql
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,    -- Links to conversations.id
    role TEXT NOT NULL,               -- 'user' or 'assistant'
    content TEXT NOT NULL,            -- Message content
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
);
```

**Fields:**
- `id`: Auto-incrementing message ID
- `conversation_id`: Links back to the conversation
- `role`: Either `"user"` or `"assistant"`
- `content`: The full message text (including chain-of-thought responses)
- `timestamp`: When the message was sent/received

### Data Storage Notes

- **No Message Metadata**: Response time, token counts, model parameters not stored
- **Flat Structure**: Simple text fields, no nested JSON or complex data types
- **Chain-of-Thought**: Stored identically to regular responses (no distinction)
- **Runtime Metadata**: Added by web interface (message counts, locking states, etc.)

## API Methods

PyPoe provides two main methods for sending messages to bots:

### `send_message()` - Smart Context-Aware Method

```python
async def send_message(
    self, 
    message: str, 
    bot_name: str = "GPT-3.5-Turbo",
    conversation_id: Optional[str] = None,
    save_history: bool = True
) -> AsyncGenerator[str, None]:
```

**Behavior:**
- **New Conversation**: If `conversation_id` is `None`, creates new conversation
- **Existing Conversation**: If `conversation_id` provided, automatically retrieves and includes conversation history
- **Context-Aware**: Maintains conversation continuity transparently
- **Backward Compatible**: Works for both single messages and continuing conversations

**Use Cases:**
- ✅ Web interface continuation of existing conversations
- ✅ CLI single-shot commands
- ✅ First message in new conversations
- ✅ Any scenario where you want automatic context handling

### `send_conversation()` - Explicit Full-Context Method

```python
async def send_conversation(
    self, 
    messages: List[Dict[str, str]], 
    bot_name: str = "GPT-3.5-Turbo",
    conversation_id: Optional[str] = None,
    save_history: bool = True
) -> AsyncGenerator[str, None]:
```

**Behavior:**
- **Explicit Control**: You provide the complete conversation array
- **Full Context**: Sends entire conversation history to bot
- **Manual Management**: You control exactly what context is included

**Use Cases:**
- ✅ Custom conversation management
- ✅ Slack bot with in-memory conversation arrays
- ✅ CLI interactive mode
- ✅ When you need precise control over context

## Conversation Context Flow

### How Context Continuity Works

1. **User sends message** to existing conversation
2. **PyPoe retrieves** conversation history from database
3. **Full context built** by combining history + new message
4. **Complete conversation sent** to Poe API via `fp.get_bot_response()`
5. **Bot receives full context** and can reference previous messages
6. **Response streamed back** and saved to database

### Message Flow Diagram

```
[User Input] → [Retrieve History] → [Build Context] → [Poe API] → [Bot Response] → [Save to DB]
     ↓              ↓                    ↓               ↓             ↓            ↓
"What's my name?" → [Prev: "I'm Alice"] → [Full Context] → [GPT-4] → "You're Alice" → [Database]
```

### Conversation Isolation

Each conversation maintains **separate, isolated context**:
- **Conversation A**: Alice introduction → "What's my name?" → "You're Alice" ✅
- **Conversation B**: Bob introduction → "What's my name?" → "You're Bob" ✅
- **No Cross-Talk**: Conversations cannot access each other's context

## Implementation Details

### Automatic Context Retrieval

When `send_message()` is called with a `conversation_id`, the following happens:

```python
# 1. Retrieve existing conversation history
existing_messages = await self.get_conversation_messages(conversation_id)

# 2. Convert to conversation format
conversation_messages = []
for msg in existing_messages:
    conversation_messages.append({
        'role': msg['role'],      # 'user' or 'assistant'
        'content': msg['content'] # Full message text
    })

# 3. Add new user message
conversation_messages.append({
    'role': 'user',
    'content': message
})

# 4. Send full context to Poe API
async for partial in self.send_conversation(
    messages=conversation_messages,
    bot_name=bot_name,
    conversation_id=conversation_id,
    save_history=False  # Prevent duplicates
):
    yield partial
```

### History Management

- **User Message**: Saved before sending to API
- **Bot Response**: Saved after receiving complete response
- **No Duplicates**: Careful handling prevents duplicate entries
- **Error Handling**: Graceful fallback if history retrieval fails

### Role Mapping

PyPoe handles role conversion between internal storage and Poe API:

```python
# Internal storage: 'assistant'
# Poe API expects: 'bot'

def _convert_role_for_api(self, role: str) -> str:
    if role == "assistant":
        return "bot"
    return role

def _convert_role_for_history(self, role: str) -> str:
    if role == "bot":
        return "assistant"
    return role
```

## Usage Examples

### Example 1: Starting a New Conversation

```python
from pypoe.core.client import PoeChatClient

client = PoeChatClient()

# First message - creates new conversation
async for chunk in client.send_message(
    message="Hello! My name is Alice.",
    bot_name="GPT-4",
    save_history=True
):
    print(chunk, end="")
```

### Example 2: Continuing an Existing Conversation

```python
# Get conversation ID from previous interaction
conversations = await client.get_conversations()
conversation_id = conversations[0]['id']

# Continue conversation - automatically includes context
async for chunk in client.send_message(
    message="What name did I tell you?",
    bot_name="GPT-4",
    conversation_id=conversation_id,
    save_history=True
):
    print(chunk, end="")
# Bot will respond: "You told me your name is Alice."
```

### Example 3: Manual Conversation Management

```python
# Build conversation manually
conversation = [
    {"role": "user", "content": "Hello! My name is Alice."},
    {"role": "assistant", "content": "Hello Alice! Nice to meet you."},
    {"role": "user", "content": "What's my name?"}
]

# Send with explicit context control
async for chunk in client.send_conversation(
    messages=conversation,
    bot_name="GPT-4",
    save_history=True
):
    print(chunk, end="")
```

### Example 4: Retrieving Conversation History

```python
# Get all conversations
conversations = await client.get_conversations()
for conv in conversations:
    print(f"Conversation: {conv['title']} ({conv['bot_name']})")
    
    # Get messages for this conversation
    messages = await client.get_conversation_messages(conv['id'])
    for msg in messages:
        role_emoji = "👤" if msg['role'] == 'user' else "🤖"
        print(f"  {role_emoji} {msg['role']}: {msg['content']}")
```

## Best Practices

### When to Use Each Method

| Scenario | Method | Reason |
|----------|--------|--------|
| Web interface | `send_message()` | Automatic context handling |
| CLI single command | `send_message()` | Simple one-shot interaction |
| Interactive CLI | `send_conversation()` | Manual conversation management |
| Slack bot | `send_conversation()` | In-memory conversation arrays |
| Custom context | `send_conversation()` | Precise control needed |

### Performance Considerations

- **Database Access**: Each `send_message()` with `conversation_id` queries database
- **Message Limits**: Poe API limits conversation length (~1000 messages)
- **Token Limits**: Very long conversations may hit model context limits
- **Caching**: Consider caching conversation history for high-frequency usage

### Error Handling

```python
try:
    async for chunk in client.send_message(
        message="Hello",
        conversation_id=conversation_id
    ):
        print(chunk, end="")
except Exception as e:
    if "conversation history" in str(e).lower():
        # Handle history retrieval failure
        print("Warning: Using fallback mode without context")
    else:
        # Handle other errors
        print(f"Error: {e}")
```

## Troubleshooting

### Common Issues

#### 1. Bot Doesn't Remember Context

**Symptoms**: Bot acts like each message is the first in conversation
**Causes**: 
- `conversation_id` not provided to `send_message()`
- Database corruption or missing messages
- Using `send_message()` without conversation context

**Solutions**:
```python
# ❌ Wrong - no conversation_id
await client.send_message("What's my name?")

# ✅ Correct - include conversation_id  
await client.send_message("What's my name?", conversation_id=conv_id)
```

#### 2. Duplicate Messages in History

**Symptoms**: Same message appears multiple times in conversation history
**Causes**: 
- Calling `send_conversation()` with `save_history=True` on existing messages
- Multiple saves due to error retry logic

**Solutions**:
- Use `save_history=False` when resending existing conversation
- Check conversation history before adding messages

#### 3. Conversation Not Found

**Symptoms**: Error when trying to continue conversation
**Causes**:
- Invalid or expired `conversation_id`
- Database corruption
- Conversation was deleted

**Solutions**:
```python
# Verify conversation exists
conversations = await client.get_conversations()
valid_ids = [c['id'] for c in conversations]
if conversation_id not in valid_ids:
    print("Conversation not found, creating new one")
    conversation_id = None
```

#### 4. Context Too Long

**Symptoms**: API errors about token limits or conversation length
**Causes**: 
- Very long conversation history
- Large messages in conversation
- Model context window exceeded

**Solutions**:
- Implement conversation trimming
- Use conversation summarization
- Start new conversation for long chats

### Debugging Tips

#### Enable Verbose Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# This will show database queries and API calls
```

#### Check Database Contents

```python
# Inspect conversation history
messages = await client.get_conversation_messages(conversation_id)
print(f"Conversation has {len(messages)} messages")
for i, msg in enumerate(messages):
    print(f"{i+1}. {msg['role']}: {msg['content'][:50]}...")
```

#### Test Context Continuity

```python
# Simple test to verify context works
conv_id = None

# Message 1
async for chunk in client.send_message("My name is TestUser"):
    pass

# Get conversation ID
conversations = await client.get_conversations()
conv_id = conversations[0]['id']

# Message 2 - should remember name
async for chunk in client.send_message("What's my name?", conversation_id=conv_id):
    print(chunk, end="")
# Should respond with "TestUser"
```

### Configuration Issues

#### Database Path

```python
# Check database location
client = PoeChatClient()
print(f"Database path: {client.history.get_db_path()}")

# Custom database path
from pypoe.core.config import Config
config = Config()
config.database_path = "/custom/path/conversations.db"
client = PoeChatClient(config=config)
```

#### History Disabled

```python
# Check if history is enabled
client = PoeChatClient(enable_history=True)
if not client.enable_history:
    print("History is disabled - no context continuity")
```

## Migration Notes

### From Old PyPoe Versions

If upgrading from versions before the conversation context fix:

1. **Database Schema**: Tables should auto-create with correct schema
2. **API Compatibility**: `send_message()` behavior changed but remains backward compatible
3. **Existing Code**: No changes needed - conversations will automatically gain context
4. **Performance**: Slight increase in database queries for existing conversations

### Database Migration

```python
# The database schema auto-migrates on first use
client = PoeChatClient()
await client._ensure_history_initialized()
print("Database schema updated")
```

## Enhanced Media Storage (NEW!) 🖼️📹

### Image and Video Generation Models

PyPoe includes enhanced support for AI models that generate images, videos, and other media content with intelligent storage and context management.

#### **Do Media Models Need Conversation History?**

**✅ When They DO Need History:**
- **Iterative refinement**: "Make it more colorful" referring to previous image
- **Style consistency**: "Create another image in the same style" 
- **Progressive edits**: Building on previous generations
- **Context-aware requests**: "Add a sunset to the landscape you just created"

**❌ When They DON'T Need History:**
- **Single prompt generations**: Independent image/video requests
- **Completely new subjects**: Unrelated to previous generations
- **Performance considerations**: Large media URLs can bloat context

#### **Supported Media Models**

**Image Generation:**
- DALL-E-3, FLUX.1-schnell, FLUX.1-dev
- Stable-Diffusion-XL, Imagen-3, Imagen-3-Fast

**Video Generation:**
- Runway-Gen-3, Veo-2, Kling-Pro-v1.5

#### **Enhanced Database Schema**

The HistoryManager provides comprehensive media handling:

```sql
-- Enhanced messages table
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    content_type TEXT DEFAULT 'text',  -- 'text', 'media', 'mixed'
    media_data TEXT,  -- JSON metadata
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Media files tracking
CREATE TABLE media_files (
    id INTEGER PRIMARY KEY,
    message_id INTEGER NOT NULL,
    file_hash TEXT UNIQUE,
    original_url TEXT,
    local_path TEXT,
    media_type TEXT,
    file_size INTEGER,
    width INTEGER,
    height INTEGER,
    duration REAL,  -- for videos
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### **Smart Media Context Management**

For media models, PyPoe implements intelligent conversation history:

- **Context Limitation**: Limits history to recent + important media messages
- **URL Detection**: Automatically detects image/video URLs in responses
- **Local Caching**: Downloads and stores media files locally
- **Metadata Extraction**: Tracks file size, dimensions, and other properties

#### **Usage Example**

```python
from pypoe.core.history import HistoryManager
from pypoe.core.client import PoeChatClient

# Use HistoryManager with media support
client = PoeChatClient()
client.history = HistoryManager(
    db_path="conversations.db",
    media_dir="media_cache"  # Optional: custom media directory
)

# Generate an image
conversation_id = await client.history.create_conversation(
    title="Image Generation",
    bot_name="DALL-E-3"
)

async for response in client.send_message(
    message="Create a sunset over mountains",
    bot_name="DALL-E-3",
    conversation_id=conversation_id
):
    print(response)  # Will include image URLs

# Refine the image (uses conversation context)
async for response in client.send_message(
    message="Make it more colorful and add birds",
    bot_name="DALL-E-3", 
    conversation_id=conversation_id
):
    print(response)  # Bot remembers the previous image
```

#### **Media Storage Benefits**

- 🖼️ **Local Caching**: Images/videos downloaded automatically
- 📊 **Rich Metadata**: Track file sizes, dimensions, creation dates
- 🔄 **Context Continuity**: "Make it more colorful" refers to previous image
- 🧹 **Cleanup Tools**: Remove orphaned media files
- 📈 **Storage Analytics**: Monitor media usage and disk space
- 🔗 **URL Backup**: Local copies prevent broken links

#### **Current PyPoe Implementation**

**The HistoryManager provides comprehensive media support:**

```sql
content TEXT NOT NULL  -- ✅ Media URLs with metadata tracking
```

**This provides:**
- 🗄️ Rich media metadata (dimensions, file type, size)
- 💾 Efficient storage with local caching  
- 🔗 Local backup prevents URL expiration
- 🖼️ Enhanced UX with inline media display
- 🔍 Media search and filtering capabilities

#### **Using Media Storage**

```python
# Standard approach with full media support
from pypoe.core.client import PoeChatClient
client = PoeChatClient()  # Uses HistoryManager with media support

# Custom media directory
from pypoe.core.history import HistoryManager
client = PoeChatClient()
client.history = HistoryManager("conversations.db", "media/")
```

#### **Media Storage Analytics**

```python
# Check media storage usage
stats = await client.history.get_media_stats()
print(f"📁 Total media files: {stats['total_files']}")
print(f"💾 Total storage: {stats['total_size_bytes'] / 1024 / 1024:.1f} MB")

# Breakdown by media type
for media_type, info in stats['by_type'].items():
    print(f"  {media_type}: {info['count']} files, {info['size'] / 1024 / 1024:.1f} MB")
```

#### **Media Cleanup**

```python
# Remove orphaned media files (no longer linked to messages)
await client.history.cleanup_orphaned_media()
print("🧹 Cleaned up orphaned media files")
```

---

## Summary

PyPoe's conversation management provides:

- ✅ **Full Context Continuity**: Bots remember conversation history
- ✅ **Persistent Storage**: SQLite database with conversations and messages
- ✅ **Smart API**: `send_message()` automatically handles context
- ✅ **Flexible Usage**: Both automatic and manual conversation management
- ✅ **Conversation Isolation**: Separate context for each conversation
- ✅ **Error Resilience**: Graceful fallbacks and robust error handling

This system ensures that PyPoe provides the same conversation experience as the official Poe web interface, with bots that remember context and maintain natural conversational flow. 