# PyPoe Conversation History & Management

This directory contains your PyPoe conversation database (`pypoe_history.db`) and serves as the central hub for all your AI conversations across CLI, Web, and Slack interfaces.

## 🗄️ **Unified History Database**

**All three PyPoe interfaces share the same SQLite database:**
- **CLI conversations** (`pypoe chat`, `pypoe interactive`)
- **Web interface chats** (browser-based)
- **Slack bot interactions** (team conversations)

✅ **Cross-Platform Continuity**: Start in CLI, continue in Web, review in Slack  
✅ **Unified Search**: Find all conversations regardless of origin  
✅ **Centralized Management**: Delete, export, organize from any interface  

---

## 🤖 **Model Selection & Conversation Management**

### **CLI Interface**

#### **Model Selection:**
```bash
# Choose model for single message
pypoe chat "Hello!" --bot GPT-4

# Choose model for interactive session
pypoe interactive --bot Claude-3-Sonnet --save-history

# Continue existing conversation with specific model
pypoe interactive --conversation-id abc123 --bot GPT-4-Turbo
```

#### **Conversation Continuity:**
```bash
# 1. Start a conversation (PyPoe shows the conversation ID)
pypoe interactive --bot GPT-4 --save-history
> "What's quantum physics?"
> "Can you explain more?"
> exit                    # 📝 NOTE: Conversation is SAVED!

# 2. Find your conversation ID
pypoe conversations      # Lists all conversations with IDs

# 3. Continue the SAME conversation later (even after exit!)
pypoe interactive --conversation-id abc123def --bot GPT-4
> "Can you give me examples?"  # Continues where you left off!

# 4. View specific conversation messages
pypoe messages abc123def
```

#### **🚨 Important: Exiting vs. Continuing**
- **`exit` or `Ctrl+C`**: Saves conversation and ends the session
- **Later resumption**: Use `--conversation-id` to continue exactly where you left off
- **All context preserved**: The AI remembers your entire conversation history

---

### **Web Interface**

#### **Model Selection & Conversations:**
- **New Chat**: Select bot from dropdown when creating conversation
- **Continue Chat**: Click any conversation from sidebar to resume
- **Switch Models**: Change bot selection mid-conversation
- **Separate Topics**: Create new conversations for different topics

#### **Smart Conversation Management:**
- **Sidebar Lists All Conversations**: See titles, bots, message counts
- **Search & Filter**: Find conversations by content or bot type
- **Instant Switching**: Click any conversation to continue
- **Model Switching**: Change bot mid-conversation (preserves context)
- **Always Saved**: Every message automatically saved

---

### **Slack Bot**

#### **Model Management:**
```slack
/poe set-model GPT-4          # Switch your preferred model
/poe chat Hello!              # Uses your current model
/poe reset                    # Start fresh conversation
/poe models                   # List available models
```

#### **Per-User Sessions:**
- **Individual Context**: Each user has their own conversation thread
- **Persistent Memory**: Bot remembers your conversation until reset
- **Model Preferences**: Your model choice saved per user
- **Team Isolation**: Your conversations separate from other team members

---

## 🔄 **Model Switching Mid-Conversation**

### **What Happens When You Switch Models:**

**Example: CLI Model Switching**
```bash
# Start with GPT-4
pypoe interactive --conversation-id abc123 --bot GPT-4
> "Explain machine learning"
GPT-4: "Machine learning is a subset of AI..."
> exit

# Later: Continue SAME conversation with Claude
pypoe interactive --conversation-id abc123 --bot Claude-3-Sonnet  
> "Can you give me practical examples?"
Claude: "Based on the machine learning explanation above..."  # 🎯 Sees GPT-4's response!
```

**Example: Web Interface Model Switching**
1. Start conversation with GPT-4: "What's blockchain?"
2. Change bot dropdown to Claude-3-Sonnet
3. Continue: "How is it different from traditional databases?"
4. Claude sees the entire conversation history with GPT-4

**Example: Slack Model Switching**
```slack
/poe set-model GPT-4
User: "What's machine learning?"
GPT-4: "Machine learning is..."

/poe set-model Claude-3-Sonnet  
User: "Give me examples"  
Claude: "Building on what was explained about machine learning..."  # 🎯 Full context!
```

---

## 📊 **Conversation Behavior by Interface**

| Scenario | CLI | Web | Slack |
|----------|-----|-----|--------|
| **Single Message** | New conversation each time | Manual choice | Continues session |
| **Interactive Session** | Same conversation until exit | Same conversation until closed | Same conversation until reset |
| **After Exit/Close** | ✅ Can continue with `--conversation-id` | ✅ Can continue by clicking sidebar | ✅ Continues automatically |
| **New Topic** | New session OR continue existing | Create new OR continue existing | Continue OR `/poe reset` |
| **Model Switch** | ✅ Preserves conversation context | ✅ Preserves conversation context | ✅ Preserves conversation context |

---

## 🎯 **Best Practices**

### **For Separate Topics:**
```bash
# CLI: Start new interactive sessions for different topics
pypoe interactive --bot GPT-4 --save-history    # Topic 1: Science
pypoe interactive --bot Claude-3 --save-history  # Topic 2: Writing

# Web: Create new conversations for each topic
# Use "New Chat" button for fresh topics

# Slack: Reset between major topic changes
/poe reset
```

### **For Continuing Conversations:**
```bash
# CLI: Always save conversation IDs for later
pypoe conversations                           # Find your conversation
pypoe interactive --conversation-id abc123   # Continue where you left off

# Web: Just click the conversation in the sidebar
# Slack: Just keep chatting (remembers automatically)
```

### **For Model Comparison:**
```bash
# CLI: Switch models within same conversation
pypoe interactive --conversation-id abc123 --bot GPT-4
> "Explain quantum computing"
> exit

pypoe interactive --conversation-id abc123 --bot Claude-3-Sonnet
> "How would you explain this differently?"  # Compare responses!

# Web: Use model dropdown to switch mid-conversation
# Slack: Use /poe set-model to switch and compare
```

### **For Organization:**
- **Use descriptive titles** when creating new conversations
- **Web interface** provides the best overview and search capabilities  
- **Regular cleanup**: Delete old conversations you no longer need
- **Export important conversations** before deleting

---

## 📁 **Database Structure**

Your conversation history is stored in `pypoe_history.db` with this structure:

```sql
-- Conversations: Each chat session
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,           -- Unique conversation ID
    title TEXT,                   -- "Chat with GPT-4", etc.
    bot_name TEXT,               -- Last used bot
    created_at DATETIME,         -- When conversation started
    updated_at DATETIME          -- Last message time
);

-- Messages: Individual chat messages
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,       -- Message ID
    conversation_id TEXT,         -- Links to conversations.id
    role TEXT,                   -- 'user' or 'assistant'
    content TEXT,                -- The actual message
    timestamp DATETIME           -- When message was sent
);
```

---

## 🔍 **Finding and Managing Conversations**

### **CLI Commands:**
```bash
# List all conversations
pypoe conversations --limit 20

# View specific conversation messages  
pypoe messages <conversation-id>

# Export history
pypoe history --format json --limit 50

# Delete conversation
pypoe delete <conversation-id>

# Get conversation ID from interactive session
pypoe interactive --save-history  # Shows ID when starting
```

### **Web Interface:**
- **Sidebar**: Browse all conversations visually
- **Search**: Find conversations by content
- **Filter**: Show only specific bot conversations
- **Statistics**: View message counts and usage analytics
- **Export**: Download conversations as text files

### **Viewing All Your Data:**
The **web interface provides the best overview** of all your conversations:
```bash
pypoe web --port 8000
# Visit http://localhost:8000
# See ALL conversations from CLI, Web, and Slack in one place!
```

---

## 🚨 **Important Notes**

### **Conversation Persistence:**
- **CLI**: Conversations persist after `exit` - use `--conversation-id` to continue
- **Web**: Conversations always persist - click sidebar to continue  
- **Slack**: Conversations persist until `/poe reset`

### **Model Memory:**
- **Each model sees the full conversation history** when switched mid-chat
- **Context is preserved** across model changes
- **Database stores all messages** regardless of which model created them

### **Cross-Interface Access:**
- **Start in CLI, continue in Web**: All conversations appear in web sidebar
- **Slack conversations**: Also visible in web interface
- **Shared database**: One source of truth for all your AI conversations

### **Data Location:**
- **Database**: `~/.pypoe/single_webchat_history.db`
- **Backup**: Copy this file to backup all conversations
- **Migration**: Move this file to transfer conversations between machines

---

## 🆘 **Troubleshooting**

### **Can't Find Conversation ID:**
```bash
pypoe conversations                    # Lists all with IDs
pypoe history --format table          # Enhanced view with message counts
```

### **Conversation Not Continuing:**
- **CLI**: Ensure you're using `--conversation-id abc123`
- **Web**: Click the correct conversation in sidebar
- **Slack**: Check if you accidentally used `/poe reset`

### **Missing History:**
- **Check**: `pypoe status` to verify history is enabled
- **CLI**: Use `--save-history` flag for new conversations
- **Database**: Verify `~/.pypoe/single_webchat_history.db` exists

### **View Everything:**
```bash
pypoe web
# Open http://localhost:8000
# See ALL your conversations in one organized interface!
```

---

## 💡 **Pro Tips**

1. **Use Web Interface for Overview**: Best way to see all your conversations
2. **CLI for Quick Tasks**: Fast responses with `pypoe chat`
3. **Slack for Team Collaboration**: Shared AI assistant for your workspace
4. **Save Important Conversation IDs**: Keep a note of important discussion IDs
5. **Regular Exports**: Backup important conversations before cleanup
6. **Model Experimentation**: Switch models mid-conversation to compare responses

Remember: **Your conversation history is shared across all interfaces**, making PyPoe a truly unified AI interaction platform! 🚀 