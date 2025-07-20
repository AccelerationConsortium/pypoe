"""
Database logging system for PyPoe.
Logs network events and system changes to SQLite databases in ~/.pypoe/
"""

import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional


class PyPoeLogger:
    def __init__(self):
        self.pypoe_dir = Path.home() / '.pypoe'
        self.pypoe_dir.mkdir(exist_ok=True)
        
        self.network_db_path = self.pypoe_dir / 'network_logs.db'
        self.system_db_path = self.pypoe_dir / 'system_logs.db'
        
        self._init_databases()
    
    def _init_databases(self):
        """Initialize database schemas if they don't exist."""
        # Initialize network logs database
        with sqlite3.connect(self.network_db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS network_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,  -- 'detection', 'connection', 'disconnection', 'status_change'
                    network_type TEXT,         -- 'tailscale', 'compsci_vpn', 'compsci_wifi', 'local'
                    ip_address TEXT,
                    interface_name TEXT,
                    status TEXT,               -- 'active', 'detected', 'disconnected'
                    frontend_url TEXT,
                    backend_url TEXT,
                    metadata TEXT,             -- JSON string for additional data
                    hostname TEXT,
                    session_id TEXT
                )
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_network_timestamp ON network_events(timestamp)
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_network_type ON network_events(network_type)
            ''')
        
        # Initialize system logs database
        with sqlite3.connect(self.system_db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS system_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,  -- 'startup', 'shutdown', 'config_change', 'feature_toggle', 'metric_update'
                    component TEXT,            -- 'backend', 'frontend', 'database', 'network'
                    action TEXT,               -- 'start', 'stop', 'update', 'change'
                    old_value TEXT,            -- JSON string of previous state
                    new_value TEXT,            -- JSON string of new state
                    user_agent TEXT,
                    session_id TEXT,
                    metadata TEXT              -- JSON string for additional data
                )
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_system_timestamp ON system_events(timestamp)
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_system_component ON system_events(component)
            ''')
    
    def log_network_event(
        self, 
        event_type: str,
        network_type: Optional[str] = None,
        ip_address: Optional[str] = None,
        interface_name: Optional[str] = None,
        status: Optional[str] = None,
        frontend_url: Optional[str] = None,
        backend_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        hostname: Optional[str] = None,
        session_id: Optional[str] = None
    ):
        """Log a network-related event."""
        with sqlite3.connect(self.network_db_path) as conn:
            conn.execute('''
                INSERT INTO network_events (
                    timestamp, event_type, network_type, ip_address, interface_name,
                    status, frontend_url, backend_url, metadata, hostname, session_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(),
                event_type,
                network_type,
                ip_address,
                interface_name,
                status,
                frontend_url,
                backend_url,
                json.dumps(metadata) if metadata else None,
                hostname,
                session_id
            ))
    
    def log_system_event(
        self,
        event_type: str,
        component: str,
        action: str,
        old_value: Optional[Any] = None,
        new_value: Optional[Any] = None,
        user_agent: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log a system-related event."""
        with sqlite3.connect(self.system_db_path) as conn:
            conn.execute('''
                INSERT INTO system_events (
                    timestamp, event_type, component, action, old_value, new_value,
                    user_agent, session_id, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(),
                event_type,
                component,
                action,
                json.dumps(old_value) if old_value is not None else None,
                json.dumps(new_value) if new_value is not None else None,
                user_agent,
                session_id,
                json.dumps(metadata) if metadata else None
            ))
    
    def get_network_logs(
        self, 
        limit: int = 100, 
        network_type: Optional[str] = None,
        since: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve network logs with optional filtering."""
        query = "SELECT * FROM network_events WHERE 1=1"
        params = []
        
        if network_type:
            query += " AND network_type = ?"
            params.append(network_type)
        
        if since:
            query += " AND timestamp > ?"
            params.append(since)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        with sqlite3.connect(self.network_db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_system_logs(
        self, 
        limit: int = 100, 
        component: Optional[str] = None,
        since: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve system logs with optional filtering."""
        query = "SELECT * FROM system_events WHERE 1=1"
        params = []
        
        if component:
            query += " AND component = ?"
            params.append(component)
        
        if since:
            query += " AND timestamp > ?"
            params.append(since)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        with sqlite3.connect(self.system_db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_network_summary(self) -> Dict[str, Any]:
        """Get a summary of network activity."""
        with sqlite3.connect(self.network_db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # Count events by network type
            cursor = conn.execute('''
                SELECT network_type, COUNT(*) as count 
                FROM network_events 
                WHERE network_type IS NOT NULL 
                GROUP BY network_type
            ''')
            network_counts = {row['network_type']: row['count'] for row in cursor.fetchall()}
            
            # Recent activity (last 24 hours)
            cursor = conn.execute('''
                SELECT COUNT(*) as count 
                FROM network_events 
                WHERE datetime(timestamp) > datetime('now', '-1 day')
            ''')
            recent_activity = cursor.fetchone()['count']
            
            # Last detection for each network type
            cursor = conn.execute('''
                SELECT network_type, MAX(timestamp) as last_seen, status, ip_address
                FROM network_events 
                WHERE event_type = 'detection' AND network_type IS NOT NULL
                GROUP BY network_type
            ''')
            last_seen = {row['network_type']: {
                'timestamp': row['last_seen'],
                'status': row['status'],
                'ip_address': row['ip_address']
            } for row in cursor.fetchall()}
            
            return {
                'network_counts': network_counts,
                'recent_activity': recent_activity,
                'last_seen': last_seen,
                'total_events': sum(network_counts.values())
            }


# Global logger instance
logger = PyPoeLogger() 