# PyPoe Web Server Daemon Guide

This guide shows you how to keep PyPoe web server running even after you log out from SSH sessions.

## 📋 Available Network Interfaces

When you run PyPoe with `PYPOE_HOST=0.0.0.0`, the web server will be accessible from:

### 🏠 **Local Access (same machine)**
- `http://localhost:8000`
- `http://127.0.0.1:8000`

### 🌐 **Tailscale Access (remote devices)**
- `http://100.x.x.x:8000` (your Tailscale IP)

### 🏢 **LAN Access (local network)**
- `http://x.x.x.x:8000` (your local network IP)

## 🚀 Method 1: Using Python Daemon Script (Recommended)

### Start the daemon
```bash
python scripts/setup/run_pypoe_daemon.py start
```

### Check status
```bash
python scripts/setup/run_pypoe_daemon.py status
```

### View logs
```bash
python scripts/setup/run_pypoe_daemon.py logs
```

### Stop the daemon
```bash
python scripts/setup/run_pypoe_daemon.py stop
```

### Restart the daemon
```bash
python scripts/setup/run_pypoe_daemon.py restart
```

### Features:
- ✅ Survives SSH logout
- ✅ Automatic logging
- ✅ Process management
- ✅ Error handling
- ✅ Cross-platform support (Windows, macOS, Linux)
- ✅ Environment variable validation
- ✅ Network interface detection

## 🔍 Health Monitoring

### Basic Health Check
```bash
python scripts/setup/pypoe_health_check.py
```

### Full System Check
```bash
python scripts/setup/pypoe_health_check.py --full
```

### JSON Output (for monitoring systems)
```bash
python scripts/setup/pypoe_health_check.py --json --full
```

### Health Check Features:
- ✅ Process status monitoring
- ✅ Web server health verification  
- ✅ API endpoint testing
- ✅ Log file analysis
- ✅ Environment validation
- ✅ Performance metrics
- ✅ JSON output for automation

### Example Health Check Output:
```
✅ Overall Status: PASS
📅 Check Time: 2025-01-27T10:30:00

📋 Check Results:
   ✅ Process: PyPoe process running (PID: 12345)
   ✅ Web Server: Web server responding (status: healthy)
   ✅ Logs: Log files OK
   ✅ Api Endpoints: API endpoints responding
   ✅ Environment: Environment OK
```

### Automated Monitoring with Cron:
```bash
# Check every 5 minutes, email on failure
*/5 * * * * cd /path/to/PyPoe && python scripts/setup/pypoe_health_check.py --json > /dev/null || echo "PyPoe health check failed" | mail -s "PyPoe Alert" admin@example.com

# Full check once per hour
0 * * * * cd /path/to/PyPoe && python scripts/setup/pypoe_health_check.py --full --json >> /var/log/pypoe-health.log
```

## 🔧 Method 2: Using nohup (Simple)

### Start with nohup
```bash
nohup pypoe web > ~/pypoe-web.log 2>&1 &
```

### Check if running
```bash
ps aux | grep pypoe
```

### Stop the process
```bash
pkill -f "pypoe web"
```

### View logs
```bash
tail -f ~/pypoe-web.log
```

## 🐧 Method 3: Using systemd (Linux only)

### 1. Create user and setup
```bash
# Create pypoe user (optional, can use your own user)
sudo useradd -m -s /bin/bash pypoe
sudo usermod -aG sudo pypoe

# Switch to pypoe user
sudo su - pypoe
```

### 2. Copy service file
```bash
# Copy the service file (adjust paths as needed)
sudo cp /path/to/PyPoe/scripts/setup/pypoe-web.service /etc/systemd/system/

# Edit the service file to match your paths
sudo nano /etc/systemd/system/pypoe-web.service
```

### 3. Enable and start service
```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable pypoe-web

# Start service
sudo systemctl start pypoe-web

# Check status
sudo systemctl status pypoe-web
```

### 4. Manage the service
```bash
# Start
sudo systemctl start pypoe-web

# Stop
sudo systemctl stop pypoe-web

# Restart
sudo systemctl restart pypoe-web

# View logs
sudo journalctl -u pypoe-web -f

# Check health (using our health check script)
python scripts/setup/pypoe_health_check.py --full
```

### Enhanced systemd Features:
- ✅ **Security hardening**: Comprehensive systemd security settings
- ✅ **Automatic restarts**: Service restarts on failure
- ✅ **Boot integration**: Starts automatically on system boot
- ✅ **Process isolation**: Enhanced security and resource protection
- ✅ **Graceful shutdown**: Proper SIGTERM/SIGKILL handling
- ✅ **Timeout management**: Configurable start/stop timeouts

## 🖥️ Method 4: Using screen/tmux (SSH sessions)

### Using screen
```bash
# Start a screen session
screen -S pypoe-web

# Run PyPoe web server
pypoe web

# Detach from screen: Ctrl+A, then D
# Reattach later: screen -r pypoe-web
```

### Using tmux
```bash
# Start a tmux session
tmux new-session -d -s pypoe-web

# Run PyPoe in the session
tmux send-keys -t pypoe-web 'pypoe web' Enter

# Attach to session: tmux attach-session -t pypoe-web
# Detach: Ctrl+B, then D
```

## 🛡️ Security Considerations

Since the server binds to `0.0.0.0`, it's accessible from all network interfaces:

### ✅ **Enabled Security Features:**
- 🔐 **Web Authentication**: Username/password protection
- 🌐 **Tailscale Network**: Encrypted mesh network
- 🏠 **Local Network**: Trusted home/office network

### 🔧 **Additional Security Tips:**
1. **Firewall**: Configure firewall to only allow port 8000 from trusted networks
2. **Strong Passwords**: Use strong web authentication credentials
3. **VPN Only**: Consider only allowing access via Tailscale
4. **Regular Updates**: Keep PyPoe and dependencies updated

### 🚨 **Firewall Configuration (Linux):**
```bash
# Allow port 8000 only from specific networks
sudo ufw allow from 100.64.0.0/10 to any port 8000  # Tailscale network
sudo ufw allow from 192.168.0.0/16 to any port 8000  # Local network
sudo ufw allow from 172.16.0.0/12 to any port 8000   # Local network
sudo ufw allow from 10.0.0.0/8 to any port 8000      # Local network
```

## 🔍 Troubleshooting

### Check if port is in use
```bash
# Check what's using port 8000
lsof -i :8000
netstat -tlnp | grep :8000
```

### Check PyPoe logs
```bash
# Using daemon script
python scripts/setup/run_pypoe_daemon.py logs

# Using systemd
sudo journalctl -u pypoe-web -f

# Using nohup
tail -f ~/pypoe-web.log
```

### Check network connectivity
```bash
# Test local access
curl -I http://localhost:8000

# Test Tailscale access
curl -I http://100.64.254.201:8000

# Test LAN access
curl -I http://172.31.34.149:8000
```

### Restart networking (if needed)
```bash
# Restart Tailscale
sudo tailscale down
sudo tailscale up

# Check Tailscale status
tailscale status
```

## 📝 Log Files

### Python Daemon Script
- **PID file**: `~/.pypoe-web.pid`
- **Log file**: `~/.pypoe-web.log`
- **Error log**: `~/.pypoe-web.error.log`

### systemd Service
- **Logs**: `journalctl -u pypoe-web`
- **Status**: `systemctl status pypoe-web`

### nohup
- **Log file**: `~/pypoe-web.log`

## 🎯 Quick Start for SSH Setup

1. **SSH into your server**
2. **Navigate to PyPoe directory**
3. **Run Tailscale setup**:
   ```bash
   python scripts/setup/setup_tailscale.py
   ```
4. **Start daemon**:
   ```bash
   python scripts/setup/run_pypoe_daemon.py start
   ```
5. **Verify it's running**:
   ```bash
   python scripts/setup/run_pypoe_daemon.py status
   ```
6. **Log out of SSH** - the web server keeps running!
7. **Access from anywhere** using the URLs shown above

## 🔄 Auto-start on Boot

### Using Python Daemon + Cron
```bash
# Add to crontab
crontab -e

# Add this line:
@reboot cd /path/to/PyPoe && python scripts/setup/run_pypoe_daemon.py start
```

### Using systemd (Linux)
```bash
# Enable service to start on boot
sudo systemctl enable pypoe-web
```

That's it! Your PyPoe web server will now be accessible from multiple interfaces and survive SSH logouts! 🎉 