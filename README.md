# PyPoe

A comprehensive Python client for interacting with Poe.com bots using the official Poe API. PyPoe provides three different interfaces to access AI models, all sharing the same conversation history database.

## 🎯 Use Cases

PyPoe offers **three ways** to interact with Poe AI models:

### 1. 🖥️ **Command Line Interface (CLI)**
Perfect for developers, automation, and terminal users:
```bash
# Single message
pypoe chat "Explain quantum computing" --bot GPT-4

# Interactive session  
pypoe interactive --bot Claude-3-Sonnet

# View conversation history
pypoe history --limit 10
```

### 2. 🌐 **Web Interface**
Modern browser-based chat with full history management:
- Two-panel layout: conversation sidebar + chat interface
- Search and filter conversations
- Statistics dashboard  
- Password protection for remote access
- Real-time streaming responses

### 3. 🤖 **Slack Bot**
Team collaboration via Slack workspace integration:
- Direct messages and channel mentions
- Multi-user support with usage tracking
- Model switching mid-conversation  
- Persistent conversation context

## 🗄️ Unified History Database

**All three interfaces share the same SQLite database** (`~/.pypoe/single_webchat_history.db`), which means:

✅ **Cross-Platform Continuity**: Start a conversation in CLI, continue in Slack, review in web  
✅ **Unified Search**: Search all conversations regardless of origin  
✅ **Centralized Management**: Delete, export, and organize from any interface  
✅ **Complete History**: View all your AI interactions in one place  

## 📦 Installation Options

Choose the installation that fits your needs:

### Option 1: Minimal CLI Only
```bash
git clone https://github.com/your-username/pypoe.git
cd pypoe  
pip install -e .
```
**Includes**: Command line interface only  
**Use for**: Automation scripts and minimal deployments

### Option 2: CLI + Web Interface
```bash
git clone https://github.com/your-username/pypoe.git
cd pypoe
pip install -e ".[web-ui]"
```
**Includes**: Command line tools + web interface  
**Use for**: Personal use with both terminal and browser access  
**Note**: You need to run `pypoe web` to start the web server when you want to use the browser interface

### Option 3: Complete Installation (All Features)
```bash
git clone https://github.com/your-username/pypoe.git  
cd pypoe
pip install -e ".[all]"
```
**Includes**: CLI + Web + Slack bot integration  
**Use for**: Team deployments with all interface options  
**Note**: Slack bot requires the web interface, so this is the only way to get Slack functionality

### Option 4: Development Mode
```bash
git clone https://github.com/your-username/pypoe.git
cd pypoe
pip install -e ".[dev]"
```
**Includes**: Everything + testing tools + development dependencies  
**Use for**: Contributing to PyPoe or custom development

## 🚀 Quick Start

### 1. Get Your API Key
1. Visit [poe.com/api_key](https://poe.com/api_key) (requires Poe subscription)
2. Copy your API key

### 2. Configure PyPoe
Create a `.env` file in the project root:
```bash
cp pypoe.env.example .env
```

Edit `.env` and add your API key:
```env
# Required
POE_API_KEY="your-poe-api-key"

# Optional: Web interface authentication
PYPOE_WEB_USERNAME="admin"  
PYPOE_WEB_PASSWORD="your-secure-password"

# Optional: Custom host for Tailscale/remote access
PYPOE_HOST="100.XX.XX.XX"  # Your Tailscale IP
PYPOE_PORT=8000
```

### 3. Test Your Setup
```bash
# Test CLI
pypoe chat "Hello!" --bot GPT-3.5-Turbo

# Test web interface  
pypoe web
# Visit http://localhost:8000

# Test Slack bot (requires additional Slack app setup)
pypoe slack-bot
```

## 📋 CLI Reference

### Chat Commands
```bash
# Single message
pypoe chat "What is machine learning?" --bot GPT-4-Turbo

# Interactive session
pypoe interactive --bot Claude-3-Sonnet --save-history

# Continue existing conversation
pypoe interactive --conversation-id <id>
```

### History Management
```bash
# List conversations
pypoe conversations --limit 20

# View specific conversation
pypoe messages <conversation-id>

# Export history
pypoe history --format json --limit 50

# Delete conversation
pypoe delete <conversation-id>
```

### Bot Management
```bash
# List available bots
pypoe bots

# Check status and configuration
pypoe status
```

### Web Interface
```bash
# Start local web server
pypoe web

# Start with authentication
pypoe web --web-username admin --web-password secret

# Start on Tailscale network
pypoe web --host 100.XX.XX.XX --web-username admin --web-password secret

# Custom port
pypoe web --port 3000
```

### Daemon Management (Background Services)
```bash
# Start web server as background daemon
pypoe daemon start

# Start with custom host/port
pypoe daemon start --host 0.0.0.0 --port 8001

# Check daemon status
pypoe daemon status

# View daemon logs
pypoe daemon logs

# Stop the daemon
pypoe daemon stop

# Restart the daemon
pypoe daemon restart
```

### Slack Bot
```bash
# Start Slack bot (requires Slack app configuration)
pypoe slack-bot --enable-history

# Socket mode for development
pypoe slack-bot --socket-mode

# HTTP mode for production
pypoe slack-bot --http-mode
```

## 🔄 Running Services in Background

PyPoe services can run in the background, allowing you to access them even after logging out from SSH sessions or closing terminals.

### 🌐 Web Interface Background Service

#### Method 1: PyPoe Daemon Commands (Recommended)
The easiest way to run PyPoe web server as a persistent daemon:

```bash
# Start the daemon
pypoe daemon start

# Start with custom configuration
pypoe daemon start --host 0.0.0.0 --port 8001

# Check status
pypoe daemon status

# View real-time logs
pypoe daemon logs

# Stop the daemon
pypoe daemon stop

# Restart the daemon
pypoe daemon restart
```

**Features:**
- ✅ Survives SSH logout and terminal closure
- ✅ Automatic logging to `~/.pypoe-web.log`
- ✅ Process management and error handling
- ✅ Environment variable integration (PYPOE_HOST, PYPOE_PORT)
- ✅ Works on macOS, Linux, and Windows
- ✅ Built into the main CLI for easy access

#### Method 2: Legacy Python Script (Alternative)
You can still use the original daemon script if preferred:

```bash
# Start the daemon
python scripts/setup/run_pypoe_daemon.py start

# Check status
python scripts/setup/run_pypoe_daemon.py status

# View logs
python scripts/setup/run_pypoe_daemon.py logs

# Stop the daemon
python scripts/setup/run_pypoe_daemon.py stop
```

#### Method 3: Using nohup (Simple)
For quick background execution:

```bash
# Start with nohup
nohup pypoe web --host 0.0.0.0 --port 8000 > ~/pypoe-web.log 2>&1 &

# Check if running
ps aux | grep pypoe

# Stop the process
pkill -f "pypoe web"

# View logs
tail -f ~/pypoe-web.log
```

#### Method 4: Using systemd (Linux Production)
For production Linux servers:

```bash
# Copy service file (adjust paths as needed)
sudo cp scripts/setup/pypoe-web.service /etc/systemd/system/

# Edit paths in service file
sudo nano /etc/systemd/system/pypoe-web.service

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable pypoe-web
sudo systemctl start pypoe-web

# Check status
sudo systemctl status pypoe-web

# View logs
sudo journalctl -u pypoe-web -f
```

### 🤖 Slack Bot Background Service

Run the Slack bot as a background service:

```bash
# Method 1: Using nohup
nohup pypoe slack-bot --enable-history > ~/pypoe-slack.log 2>&1 &

# Method 2: Using the daemon script pattern
# (Create similar script based on scripts/setup/run_pypoe_daemon.py)

# Check if running
ps aux | grep "pypoe slack-bot"

# Stop the process
pkill -f "pypoe slack-bot"
```

### 🌍 Network Access Options

When running in background, you can configure network access:

#### Local Access Only (Default)
```bash
pypoe web  # Accessible at http://localhost:8000
```

#### **All Interfaces Binding (Recommended for Network Access)**
```bash
# 1. Activate the pypoe-dev conda environment
conda activate pypoe-dev

# 2. Start backend binding to all interfaces (0.0.0.0) with authentication
pypoe web --host 0.0.0.0 --port 8000 --web-username YOUR_USERNAME --web-password YOUR_PASSWORD

# This makes the backend accessible from:
# - Localhost: http://localhost:8000
# - Tailscale: http://100.64.x.x:8000
# - Local Network: http://192.168.x.x:8000 or http://172.x.x.x:8000
```

> **⚠️ Security Note**: Replace `YOUR_USERNAME` and `YOUR_PASSWORD` with your actual credentials. Use strong passwords for network access.

#### Environment Configuration (Alternative)
```bash
# Set in .env file for automatic configuration
echo "PYPOE_HOST=0.0.0.0
PYPOE_PORT=8000
PYPOE_WEB_USERNAME=YOUR_USERNAME
PYPOE_WEB_PASSWORD=YOUR_PASSWORD" > .env

# Then simply run:
conda activate pypoe-dev
pypoe web
```

#### Tailscale Network Access (Legacy Method)
```bash
# Set Tailscale IP in environment
export PYPOE_HOST="100.XX.XX.XX"  # Your Tailscale IP
pypoe web --host $PYPOE_HOST --web-username admin --web-password secret
```

### 📊 Service Management Commands

```bash
# Check what PyPoe processes are running
ps aux | grep pypoe

# Kill all PyPoe processes
pkill -f pypoe

# View logs for different services
tail -f ~/.pypoe-web.log          # Web daemon logs
tail -f ~/pypoe-web.log            # nohup web logs  
tail -f ~/pypoe-slack.log          # Slack bot logs

# Monitor system resources
top -p $(pgrep -f pypoe)
```

### 🔐 Security Considerations for Background Services

- **Always use authentication** when binding to `0.0.0.0` or external IPs
- **Use strong passwords** for web interface protection
- **Prefer Tailscale** over public IP exposure
- **Monitor logs** regularly for security issues
- **Keep API keys secure** in environment files

## 🌐 Web Interface Features

- **Two-Panel Layout**: Conversation list + active chat
- **Real-time Streaming**: WebSocket-based responses
- **Search & Filter**: Find conversations by content or bot
- **Statistics Dashboard**: Usage analytics and metrics
- **Authentication**: Optional username/password protection
- **Network Access**: Configurable for Tailscale or local networks
- **Responsive Design**: Works on desktop and mobile

## 🤖 Slack Bot Setup

1. **Create Slack App** at [api.slack.com/apps](https://api.slack.com/apps)
2. **Configure Environment Variables**:
   ```env
   SLACK_BOT_TOKEN=xoxb-your-bot-token
   SLACK_SIGNING_SECRET=your-signing-secret  
   SLACK_APP_TOKEN=xapp-your-app-token  # For Socket Mode
   POE_API_KEY=your-poe-api-key
   ```
3. **Start the Bot**:
   ```bash
   pypoe slack-bot
   ```

### Slack Bot Commands
- `/poe help` - Show help message
- `/poe models` - List available AI models  
- `/poe chat <message>` - Send message to bot
- `/poe set-model <model>` - Switch AI model
- `/poe usage` - View usage statistics
- `/poe reset` - Reset conversation context

## 🔧 Configuration Options

### Environment Variables
```env
# Core Configuration
POE_API_KEY="your-api-key"                          # Required
DATABASE_PATH="~/.pypoe/single_webchat_history.db"  # Optional

# Web Interface  
PYPOE_HOST="localhost"                        # Default: localhost
PYPOE_PORT=8000                              # Default: 8000
PYPOE_WEB_USERNAME=""                        # Optional: enable auth
PYPOE_WEB_PASSWORD=""                        # Optional: auth password

# Slack Bot
SLACK_BOT_TOKEN="xoxb-..."                   # Required for Slack
SLACK_SIGNING_SECRET="..."                   # Required for Slack  
SLACK_APP_TOKEN="xapp-..."                   # Required for Socket Mode
SLACK_SOCKET_MODE="true"                     # true=dev, false=prod
```

### Command Line Overrides
All environment variables can be overridden via command line:
```bash
# Override host and authentication
pypoe web --host 0.0.0.0 --port 3000 --web-username admin --web-password secret

# Override database location  
pypoe chat "Hello" --database-path /custom/path/history.db
```

## 📊 Features Overview

| Feature | CLI | Web | Slack |
|---------|-----|-----|-------|
| Chat with AI models | ✅ | ✅ | ✅ |
| Conversation history | ✅ | ✅ | ✅ |
| Model switching | ✅ | ✅ | ✅ |
| Search conversations | ✅ | ✅ | ❌ |
| Real-time streaming | ✅ | ✅ | ❌ |
| Multi-user support | ❌ | ❌ | ✅ |
| Usage analytics | ✅ | ✅ | ✅ |
| Export conversations | ✅ | ✅ | ❌ |
| Authentication | ❌ | ✅ | ✅* |

*Slack authentication handled by Slack workspace permissions

## 🛠️ Development

### Running Tests
```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/

# Run specific test
pytest tests/test_client.py -v
```

### Project Structure
```
pypoe/
├── src/pypoe/             # Installable Python package
│   ├── core/              # Core functionality
│   │   ├── cli.py         # Command line entry point
│   │   ├── config.py      # Configuration management
│   │   ├── client.py      # Poe API client
│   │   ├── history.py     # Conversation history manager
│   │   └── logging_db.py  # Database logging utilities
│   ├── interfaces/        # Web and Slack interfaces
│   │   ├── web/           # Web interface (FastAPI)
│   │   ├── slack/         # Slack bot integration
│   │   └── cli/           # Interactive CLI (legacy, pending removal)
│   └── tests/             # Test suite
├── scripts/               # Ops scripts (daemon, health check, debug helpers)
├── examples/              # Sample SDK usage scripts
├── docs/                  # Documentation
└── ~/.pypoe/              # User data (SQLite history DB, .env override)
```

## 🔒 Security Notes

- **API Keys**: Never commit API keys to version control
- **Web Authentication**: Use strong passwords for remote access
- **Network Access**: Be careful when binding to `0.0.0.0` or public IPs
- **Database**: The SQLite database contains all conversation history

## 📝 License

[Your license here]

## 🤝 Contributing

1. Fork the repository
2. Install development dependencies: `pip install -e ".[dev]"`
3. Create a feature branch
4. Make your changes
5. Run tests: `pytest`
6. Submit a pull request

## 📚 Documentation

For detailed setup and configuration guides:

- **📖 [Complete Documentation](docs/README.md)** - Start here for comprehensive guides
- **🚀 [Setup Guide](docs/README_SETUP.md)** - Installation and configuration
- **🤖 [Slack Bot Guide](docs/README_SLACK.md)** - Slack integration setup
- **⚙️ [Daemon Guide](docs/README_DAEMON.md)** - Background service management

## 🆘 Support

- **Issues**: [GitHub Issues](https://github.com/AccelerationConsortium/pypoe/issues)
- **Documentation**: Check [docs/](docs/) for comprehensive guides
- **API Reference**: [Poe API Documentation](https://creator.poe.com/docs/quick-start)
