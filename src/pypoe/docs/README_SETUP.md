# PyPoe Complete Setup Guide

This comprehensive guide will walk you through setting up PyPoe from installation to deployment, covering all interfaces and deployment scenarios.

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation Options](#installation-options)
3. [Basic Configuration](#basic-configuration)
4. [Interface Setup](#interface-setup)
5. [Advanced Configuration](#advanced-configuration)
6. [Deployment Options](#deployment-options)
7. [Troubleshooting](#troubleshooting)

## 🚀 Prerequisites

Before you begin, ensure you have:

### Required
- **Python 3.8+** (Recommended: Python 3.10+)
- **Poe API Key** from [poe.com/api_key](https://poe.com/api_key) (requires Poe subscription)
- **Git** for cloning the repository

### Optional (for specific features)
- **Slack workspace** (for Slack bot integration)
- **Tailscale** (for remote access)
- **Linux/systemd** (for production deployment)

### System Requirements
- **Minimum**: 512MB RAM, 100MB disk space
- **Recommended**: 1GB RAM, 500MB disk space
- **Network**: Internet connection for API calls

## 📦 Installation Options

Choose the installation that fits your needs:

### Option 1: Minimal CLI Only
Perfect for automation and minimal deployments:
```bash
git clone https://github.com/your-username/pypoe.git
cd pypoe
pip install -e .
```
**Includes**: Command line interface only
**Use cases**: Scripts, automation, terminal-only environments

### Option 2: CLI + Web Interface
Best for personal use:
```bash
git clone https://github.com/your-username/pypoe.git
cd pypoe
pip install -e ".[web-ui]"
```
**Includes**: CLI + Web interface + Slack bot capability
**Use cases**: Personal use, local development, browser access

### Option 3: Complete Installation
For team deployments:
```bash
git clone https://github.com/your-username/pypoe.git
cd pypoe
pip install -e ".[all]"
```
**Includes**: Everything (CLI + Web + Slack + production tools)
**Use cases**: Team deployments, production environments

### Option 4: Development Mode
For contributors and custom development:
```bash
git clone https://github.com/your-username/pypoe.git
cd pypoe
pip install -e ".[dev]"
```
**Includes**: Everything + testing tools + development dependencies
**Use cases**: Contributing to PyPoe, custom development

## ⚙️ Basic Configuration

### Step 1: Get Your Poe API Key

1. **Visit** [poe.com/api_key](https://poe.com/api_key)
2. **Sign up** for a Poe subscription (required for API access)
3. **Copy** your API key (starts with `sk-`)

### Step 2: Set Up Environment File

PyPoe looks for configuration in these locations (in order):
1. Project root: `.env`
2. User home: `~/.pypoe/.env`
3. Current directory: `.env`
4. Scripts directory: `src/pypoe/scripts/pypoe.env`

**Quick Setup (Recommended)**:
```bash
# Copy the example file
cp src/pypoe/scripts/pypoe.env.example .env

# Edit with your API key
nano .env
```

**Manual Setup**:
```bash
# Create .env file
cat > .env << EOF
# Required: Your Poe API key
POE_API_KEY=your-poe-api-key-here

# Optional: Default bot to use
DEFAULT_BOT=GPT-4-Turbo

# Optional: Enable history by default
ENABLE_HISTORY=true
EOF
```

**Interactive Setup**:
```bash
# Interactive setup script
python src/pypoe/scripts/setup/setup_credentials.py
```

### Step 3: Test Your Setup

```bash
# Test CLI
pypoe chat "Hello, world!" --bot GPT-3.5-Turbo

# Test configuration
pypoe --help
```

If this works, you're ready to go! If not, see [Troubleshooting](#troubleshooting).

## 🖥️ Interface Setup

### Command Line Interface (CLI)

The CLI is included in all installation options and requires no additional setup.

**Basic Usage**:
```bash
# Single message
pypoe chat "Explain quantum computing" --bot GPT-4

# Interactive session
pypoe interactive --bot Claude-3-Sonnet

# View history
pypoe history --limit 10
```

**CLI Configuration**:
```bash
# Set default bot
export DEFAULT_BOT=GPT-4-Turbo

# Enable history by default
export ENABLE_HISTORY=true

# Custom database location
export DATABASE_PATH=/custom/path/pypoe_history.db
```

### Web Interface

The web interface provides a modern browser-based chat experience.

**Quick Start**:
```bash
# Start web server (local access only)
pypoe web

# Access at: http://localhost:8000
```

**Configuration Options**:
```bash
# Start with custom host/port
pypoe web --host 0.0.0.0 --port 8080

# Enable authentication
pypoe web --web-username admin --web-password secret

# Start as background daemon
python src/pypoe/scripts/setup/run_pypoe_daemon.py start
```

**Environment Variables**:
```env
# Web interface settings
PYPOE_HOST=localhost              # Default: localhost
PYPOE_PORT=8000                  # Default: 8000
PYPOE_WEB_USERNAME=admin         # Optional: enable authentication
PYPOE_WEB_PASSWORD=secret        # Optional: authentication password
```

**Setup Script**:
```bash
# Interactive web setup
python src/pypoe/scripts/setup/setup_webui.py
```

### Slack Bot Integration

For team collaboration via Slack. See [README_SLACK.md](README_SLACK.md) for detailed setup.

**Quick Overview**:
1. Create Slack app at [api.slack.com/apps](https://api.slack.com/apps)
2. Configure bot permissions and tokens
3. Add environment variables:
   ```env
   SLACK_BOT_TOKEN=xoxb-your-bot-token
   SLACK_SIGNING_SECRET=your-signing-secret
   SLACK_APP_TOKEN=xapp-your-app-token
   ```
4. Start bot: `pypoe slack-bot`

## 🔧 Advanced Configuration

### Database Configuration

PyPoe uses SQLite for conversation history:

```env
# Custom database location
DATABASE_PATH=/path/to/your/pypoe_history.db

# Enable history by default
ENABLE_HISTORY=true
```

**Database Management**:
```bash
# View database location
pypoe config

# Export conversations
pypoe export --format json --output conversations.json

# Clear history
pypoe clear-history --confirm
```

### Network Access Configuration

#### Local Access Only (Default)
```bash
pypoe web  # Accessible at http://localhost:8000
```

#### Network Access (Tailscale/LAN)
```bash
# Manual configuration
pypoe web --host 0.0.0.0 --port 8000 --web-username admin --web-password secret

# Environment configuration
export PYPOE_HOST=0.0.0.0
export PYPOE_PORT=8000
export PYPOE_WEB_USERNAME=admin
export PYPOE_WEB_PASSWORD=secret
pypoe web

# Tailscale setup script
python src/pypoe/scripts/setup/setup_tailscale.py
```

**Access URLs** when using `--host 0.0.0.0`:
- **Local**: `http://localhost:8000`
- **LAN**: `http://YOUR_LOCAL_IP:8000` 
- **Tailscale**: `http://YOUR_TAILSCALE_IP:8000`

### Security Configuration

**Authentication Setup**:
```env
# Web interface authentication
PYPOE_WEB_USERNAME=your_username
PYPOE_WEB_PASSWORD=your_secure_password
```

**API Key Security**:
- Never commit API keys to version control
- Use environment files with restricted permissions: `chmod 600 .env`
- Consider using separate API keys for different environments

**Network Security**:
- Use authentication when binding to `0.0.0.0`
- Prefer Tailscale over public IP exposure
- Monitor access logs for unusual activity

## 🚀 Deployment Options

### Local Development

**Quick Start**:
```bash
# Start web interface
pypoe web

# Start Slack bot
pypoe slack-bot
```

### Background Services

#### Method 1: Python Daemon (Recommended)
```bash
# Start daemon
python src/pypoe/scripts/setup/run_pypoe_daemon.py start

# Check status
python src/pypoe/scripts/setup/run_pypoe_daemon.py status

# View logs
python src/pypoe/scripts/setup/run_pypoe_daemon.py logs

# Stop daemon
python src/pypoe/scripts/setup/run_pypoe_daemon.py stop
```

#### Method 2: nohup (Simple)
```bash
# Start with nohup
nohup pypoe web --host 0.0.0.0 --port 8000 > ~/pypoe-web.log 2>&1 &

# Stop
pkill -f "pypoe web"
```

#### Method 3: CLI Daemon Commands
```bash
# Built-in daemon management
pypoe daemon start
pypoe daemon status
pypoe daemon stop
pypoe daemon logs
```

### Production Deployment (Linux)

#### systemd Service
```bash
# Copy service file
sudo cp src/pypoe/scripts/setup/pypoe-web.service /etc/systemd/system/

# Edit paths in service file
sudo nano /etc/systemd/system/pypoe-web.service

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable pypoe-web
sudo systemctl start pypoe-web

# Check status
sudo systemctl status pypoe-web
```

#### Docker Deployment
```bash
# Build Docker image
docker build -t pypoe .

# Run container
docker run -d \
  --name pypoe-web \
  -p 8000:8000 \
  -e POE_API_KEY=your-api-key \
  -e PYPOE_HOST=0.0.0.0 \
  -v $(pwd)/users:/app/users \
  pypoe
```

### Remote Access Setup

#### Tailscale (Recommended)
```bash
# Install Tailscale
curl -fsSL https://tailscale.com/install.sh | sh

# Set up PyPoe for Tailscale
python src/pypoe/scripts/setup/setup_tailscale.py

# Start PyPoe
pypoe web
```

#### SSH Tunneling
```bash
# Local port forwarding
ssh -L 8000:localhost:8000 user@remote-server

# Remote port forwarding
ssh -R 8000:localhost:8000 user@remote-server
```

## 🏥 Health Monitoring

### Built-in Health Checks
```bash
# Basic health check
python src/pypoe/scripts/setup/pypoe_health_check.py

# Full system check
python src/pypoe/scripts/setup/pypoe_health_check.py --full

# JSON output for monitoring
python src/pypoe/scripts/setup/pypoe_health_check.py --json --full
```

### Automated Monitoring
```bash
# Cron job for health monitoring
*/5 * * * * cd /path/to/PyPoe && python src/pypoe/scripts/setup/pypoe_health_check.py --json > /dev/null || echo "PyPoe down" | mail admin@example.com
```

## 🔍 Troubleshooting

### Common Issues

#### Installation Problems
```bash
# Python version issues
python --version  # Must be 3.8+

# Dependency conflicts
pip install --upgrade pip
pip install -e ".[all]" --force-reinstall

# Virtual environment recommended
python -m venv pypoe-env
source pypoe-env/bin/activate  # Linux/macOS
pypoe-env\Scripts\activate     # Windows
pip install -e ".[all]"
```

#### Configuration Issues
```bash
# Check environment variables
pypoe config

# Validate API key
pypoe chat "test" --bot GPT-3.5-Turbo

# Check .env file location
python -c "from pypoe.core.config import get_config; print(get_config())"
```

#### Network Issues
```bash
# Check port availability
lsof -i :8000
netstat -tlnp | grep :8000

# Test local connection
curl -I http://localhost:8000

# Check firewall settings
sudo ufw status  # Ubuntu
sudo iptables -L  # Generic Linux
```

#### Database Issues
```bash
# Check database location
pypoe config | grep database

# Reset database
pypoe clear-history --confirm

# Check permissions
ls -la users/history/pypoe_history.db
```

### Debug Mode

```bash
# Enable debug logging
export PYPOE_DEBUG=true
pypoe web

# Verbose output
pypoe chat "test" --verbose

# Check logs
tail -f ~/.pypoe-web.log
```

### Getting Help

1. **Check logs** for error messages
2. **Review configuration** with `pypoe config`
3. **Test basic functionality** with `pypoe chat "test"`
4. **Search issues** on GitHub
5. **Create issue** with logs and configuration details

### Diagnostic Commands

```bash
# System information
python src/pypoe/scripts/setup/pypoe_health_check.py --full

# Network connectivity
python src/pypoe/scripts/setup/debug_networking.py

# Environment validation
python src/pypoe/scripts/setup/validate_environment.py
```

## 📚 Additional Resources

- **[README_SLACK.md](README_SLACK.md)** - Slack bot setup guide
- **[README_DAEMON.md](README_DAEMON.md)** - Background service setup
- **[Main README.md](../../../README.md)** - Project overview and features
- **[Poe API Documentation](https://creator.poe.com/docs/quick-start)** - Official API docs

## ✅ Quick Setup Checklist

- [ ] Python 3.8+ installed
- [ ] PyPoe cloned and installed
- [ ] Poe API key obtained
- [ ] Environment file created
- [ ] Basic CLI test successful
- [ ] Web interface configured (if needed)
- [ ] Slack bot set up (if needed)
- [ ] Background service configured (if needed)
- [ ] Network access configured (if needed)
- [ ] Health monitoring set up (for production)

## 🎉 Next Steps

Once setup is complete:

1. **Explore features** with `pypoe --help`
2. **Try different interfaces** (CLI, web, Slack)
3. **Configure advanced options** as needed
4. **Set up monitoring** for production use
5. **Share with your team** and enjoy AI-powered conversations!

---

**Need help?** Check the troubleshooting section above or create an issue on GitHub with your configuration details and error logs. 