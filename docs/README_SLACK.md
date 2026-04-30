# PyPoe Slack Bot Setup Guide

Simple guide for setting up the PyPoe Slack bot for local development and testing.

## 🔒 **Local Development Setup**

### Step 1: Create Your Private Test Workspace
1. Go to https://slack.com/create
2. Create a new workspace with your personal email
3. Name it "PyPoe Testing" or similar

### Step 2: Create Slack App in Test Workspace
1. Go to https://api.slack.com/apps
2. Click **"Create New App"** → **"From scratch"**
3. **App Name**: `PyPoe-tests`
4. **Workspace**: Select your NEW test workspace
5. Click **"Create App"**

### Step 3: Configure Your Slack App (Socket Mode)

#### A. Enable Socket Mode (Easier for Local Development)
1. Go to **"Socket Mode"** in left sidebar
2. Toggle **"Enable Socket Mode"** to **ON**
3. Under "App Token", click **"Generate Token and Scopes"**
4. **Token Name**: `pypoe-socket`
5. **Add scope**: `connections:write`
6. Click **"Generate"**
7. **Copy the App Token** (starts with `xapp-`)

#### B. Set Bot Permissions
1. Go to **"OAuth & Permissions"**
2. Under **"Bot Token Scopes"**, add these permissions:
   - `app_mentions:read` - Read when bot is mentioned
   - `channels:history` - Read channel message history
   - `channels:read` - View basic channel info
   - `chat:write` - Send messages
   - `commands` - Use slash commands
   - `groups:history` - Read private channel history
   - `im:history` - Read direct message history
   - `im:read` - View direct message info
   - `im:write` - Send direct messages
   - `mpim:history` - Read group DM history

#### C. Enable Direct Messaging
1. Go to **"App Home"** in left sidebar
2. Scroll to **"Show Tabs"**
3. ✅ Check **"Allow users to send Slash commands and messages from the messages tab"**
4. Click **"Save Changes"**

#### D. Install to Test Workspace
1. Go back to **"OAuth & Permissions"**
2. Click **"Install to Workspace"**
3. Click **"Allow"**
4. **Copy the Bot User OAuth Token** (starts with `xoxb-`)

#### E. Get Signing Secret
1. Go to **"Basic Information"**
2. Under **"App Credentials"**
3. **Copy the Signing Secret**

### Step 4: Set Up Environment

Create environment file:
```bash
# Copy template and edit
cp pypoe.env.example .env
```

Edit `.env` with your values:
```bash
# Poe API Key (get from poe.com/api_key)
POE_API_KEY=your-poe-api-key

# Slack Bot Token (from OAuth & Permissions)
SLACK_BOT_TOKEN=xoxb-your-bot-token

# Slack Signing Secret (from Basic Information)
SLACK_SIGNING_SECRET=your-signing-secret

# Slack App Token (for Socket Mode development)
SLACK_APP_TOKEN=xapp-your-app-token

# Use Socket Mode for local development
SLACK_SOCKET_MODE=true

# Optional settings
ENABLE_HISTORY=true
```

### Step 5: Install PyPoe with Slack Integration

First, install PyPoe with full functionality (Slack bot requires the web interface):

```bash
# Install PyPoe with complete functionality (Slack + Web + CLI)
pip install -e ".[all]"
```

This will automatically install all required dependencies:
- `slack-bolt` - Slack app framework
- `slack-sdk` - Slack SDK for Python
- `gunicorn` & `uvicorn` - ASGI servers (for future HTTP mode)

### Step 6: Run Your Bot Locally

```bash
# Load environment and run
source .env && pypoe slack-bot
```

You should see:
```
🚀 Starting PyPoe Slack Bot...
📋 Configuration:
   POE_API_KEY: ✅ Set
   SLACK_BOT_TOKEN: ✅ Set
   Socket Mode: True
   History Enabled: True
⚡️ Bolt app is running!
```

**Keep this terminal running** - your bot is now online!

### Step 7: Test in Slack

In your test workspace:

1. **Invite bot to channel**: `/invite @pypoe-tests`

2. **Test commands**:
   - `@pypoe-tests hello`
   - `/poe help`
   - `/poe models`
   - `/poe chat Tell me a joke`

3. **Test Direct Messages**:
   - Click on **PyPoe-tests** in your workspace
   - Send: `hello`

---

## 🎯 **Available Commands**

### Slash Commands
- `/poe help` - Show help message
- `/poe models` - List available AI models
- `/poe chat <message>` - Send a message to the AI
- `/poe set-model <model>` - Switch to a different model
- `/poe usage` - Check your usage statistics
- `/poe reset` - Reset conversation history

### Direct Mentions
- `@pypoe hello` - Start a conversation
- `@pypoe <message>` - Send any message

### Direct Messages
- Send any message directly to the bot

---

## 🔧 **Troubleshooting**

### Bot Not Responding?
1. **Check environment variables are set**
2. **Ensure bot is invited to channel**: `/invite @pypoe-tests`
3. **Check bot logs** in your terminal for error messages
4. **Restart the bot** after changing Slack app permissions

### Direct Message Issues?
1. **Reload Slack client**: `Ctrl+R` (Windows/Linux) or `Cmd+R` (Mac)
2. **Check App Home settings**: "Allow users to send messages" must be enabled
3. **Reinstall app** after permission changes
4. **Try mentioning bot in channel first**: `@pypoe-tests hello`

### Socket Mode Issues
- Make sure Socket Mode is enabled in Slack app
- Verify SLACK_APP_TOKEN is correct
- Try restarting the bot

### Common Errors

**"Messaging has been turned off"**
- Enable App Home messaging in Slack app settings
- Reload Slack client after changes

**"Import errors"**
```bash
# Install PyPoe with Slack integration
pip install -e ".[slack]"

# Or verify installation
pip show pypoe slack-bolt slack-sdk
```

**"Bot doesn't respond"**
- Check all environment variables are set correctly
- Make sure the bot is running (terminal shows "Bolt app is running!")
- Verify bot is invited to the channel

---

## 📊 **Usage Analytics**

The bot tracks:
- **Messages sent per user**
- **Models used**
- **Daily usage statistics**
- **Estimated compute points**

Access via `/poe usage` command or check bot logs in your terminal.

---

## 🎉 **You're Ready!**

### To run your bot:
```bash
source .env && pypoe slack-bot
```

### To stop your bot:
Press `Ctrl+C` in the terminal

### Need Help?
- Test functionality: `python tests/test_slack_bot.py`
- Check bot status: `pypoe slack-bot --help`
- Validate setup: Ensure all environment variables are set

---

## 📚 **Additional Resources**

- [Poe API Documentation](https://creator.poe.com/docs/quick-start)
- [Slack API Documentation](https://api.slack.com/start/overview)

**Happy chatting with your PyPoe Slack bot!** 🤖✨ 