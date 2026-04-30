#!/usr/bin/env python3
"""
PyPoe Health Check Script

Comprehensive health monitoring for PyPoe web server daemon.
Can be used with monitoring systems like Nagios, Zabbix, or cron jobs.

Usage:
    python scripts/setup/pypoe_health_check.py          # Basic health check
    python scripts/setup/pypoe_health_check.py --full   # Full system check
    python scripts/setup/pypoe_health_check.py --json   # JSON output for monitoring
"""

import os
import sys
import json
import time
import requests
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

# Configuration
DAEMON_NAME = "pypoe-web"
PID_FILE = Path.home() / f".{DAEMON_NAME}.pid"
LOG_FILE = Path.home() / f".{DAEMON_NAME}.log"
ERROR_LOG_FILE = Path.home() / f".{DAEMON_NAME}.error.log"
HEALTH_CHECK_URL = "http://localhost:8000/api/health"
CONFIG_URL = "http://localhost:8000/api/config"

class HealthChecker:
    def __init__(self):
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "overall_status": "unknown",
            "checks": {}
        }
    
    def check_process_running(self) -> Dict[str, Any]:
        """Check if PyPoe process is running"""
        check_result = {
            "status": "fail",
            "message": "",
            "details": {}
        }
        
        try:
            if not PID_FILE.exists():
                check_result["message"] = "PID file not found"
                return check_result
            
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            
            # Check if process is still running
            os.kill(pid, 0)
            
            # Get process info
            try:
                result = subprocess.run(['ps', '-p', str(pid), '-o', 'pid,ppid,etime,rss,cpu'], 
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')
                    if len(lines) > 1:
                        headers = lines[0].split()
                        values = lines[1].split()
                        process_info = dict(zip(headers, values))
                        check_result["details"]["process_info"] = process_info
            except Exception:
                pass
            
            check_result["status"] = "pass"
            check_result["message"] = f"PyPoe process running (PID: {pid})"
            check_result["details"]["pid"] = pid
            
        except (ValueError, ProcessLookupError, OSError):
            check_result["message"] = "Process not running or PID file stale"
        except Exception as e:
            check_result["message"] = f"Error checking process: {e}"
        
        return check_result
    
    def check_web_server_health(self) -> Dict[str, Any]:
        """Check if web server is responding"""
        check_result = {
            "status": "fail",
            "message": "",
            "details": {}
        }
        
        try:
            start_time = time.time()
            response = requests.get(HEALTH_CHECK_URL, timeout=10)
            response_time = time.time() - start_time
            
            check_result["details"]["response_time"] = round(response_time, 3)
            check_result["details"]["status_code"] = response.status_code
            
            if response.status_code == 200:
                data = response.json()
                check_result["status"] = "pass" if data.get("status") == "healthy" else "fail"
                check_result["message"] = f"Web server responding (status: {data.get('status')})"
                check_result["details"]["server_data"] = data
            else:
                check_result["message"] = f"Web server returned status {response.status_code}"
                
        except requests.exceptions.Timeout:
            check_result["message"] = "Web server timeout (>10s)"
        except requests.exceptions.ConnectionError:
            check_result["message"] = "Cannot connect to web server"
        except Exception as e:
            check_result["message"] = f"Error checking web server: {e}"
        
        return check_result
    
    def check_log_files(self) -> Dict[str, Any]:
        """Check log file status and recent errors"""
        check_result = {
            "status": "pass",
            "message": "Log files OK",
            "details": {}
        }
        
        issues = []
        
        # Check log file existence and size
        for log_name, log_path in [("main", LOG_FILE), ("error", ERROR_LOG_FILE)]:
            if log_path.exists():
                stat = log_path.stat()
                check_result["details"][f"{log_name}_log"] = {
                    "exists": True,
                    "size_mb": round(stat.st_size / 1024 / 1024, 2),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                }
                
                # Check for large log files (>100MB)
                if stat.st_size > 100 * 1024 * 1024:
                    issues.append(f"{log_name} log file is large ({stat.st_size / 1024 / 1024:.1f}MB)")
                
                # Check for recent errors in error log
                if log_name == "error" and stat.st_size > 0:
                    try:
                        # Read last 1000 characters
                        with open(log_path, 'r') as f:
                            f.seek(max(0, stat.st_size - 1000))
                            recent_content = f.read()
                            
                        # Count recent error patterns
                        error_patterns = ["ERROR", "CRITICAL", "Exception", "Traceback"]
                        recent_errors = sum(recent_content.count(pattern) for pattern in error_patterns)
                        
                        if recent_errors > 0:
                            check_result["details"]["recent_errors"] = recent_errors
                            if recent_errors > 10:
                                issues.append(f"Many recent errors in log ({recent_errors})")
                    except Exception:
                        pass
            else:
                check_result["details"][f"{log_name}_log"] = {"exists": False}
                issues.append(f"{log_name} log file missing")
        
        if issues:
            check_result["status"] = "warn"
            check_result["message"] = "; ".join(issues)
        
        return check_result
    
    def check_api_endpoints(self) -> Dict[str, Any]:
        """Check critical API endpoints"""
        check_result = {
            "status": "pass",
            "message": "API endpoints responding",
            "details": {}
        }
        
        endpoints = [
            ("/api/health", "Health check"),
            ("/api/conversations", "Conversations"),
            ("/api/bots", "Available bots"),
            ("/api/stats", "Statistics")
        ]
        
        failed_endpoints = []
        
        for endpoint, description in endpoints:
            try:
                url = f"http://localhost:8000{endpoint}"
                response = requests.get(url, timeout=5)
                check_result["details"][endpoint] = {
                    "status": response.status_code,
                    "response_time": round(response.elapsed.total_seconds(), 3)
                }
                
                if response.status_code not in [200, 401]:  # 401 is OK if auth is enabled
                    failed_endpoints.append(f"{description} ({response.status_code})")
                    
            except Exception as e:
                check_result["details"][endpoint] = {"error": str(e)}
                failed_endpoints.append(f"{description} (error)")
        
        if failed_endpoints:
            check_result["status"] = "fail"
            check_result["message"] = f"Failed endpoints: {', '.join(failed_endpoints)}"
        
        return check_result
    
    def check_environment(self) -> Dict[str, Any]:
        """Check environment configuration"""
        check_result = {
            "status": "pass",
            "message": "Environment OK",
            "details": {}
        }
        
        # Check required environment variables
        required_vars = ["POE_API_KEY"]
        optional_vars = ["PYPOE_HOST", "PYPOE_PORT", "PYPOE_WEB_USERNAME", "PYPOE_WEB_PASSWORD"]
        
        missing_required = []
        
        for var in required_vars:
            if os.environ.get(var):
                check_result["details"][var] = "set"
            else:
                check_result["details"][var] = "missing"
                missing_required.append(var)
        
        for var in optional_vars:
            check_result["details"][var] = "set" if os.environ.get(var) else "not_set"
        
        if missing_required:
            check_result["status"] = "fail"
            check_result["message"] = f"Missing required environment variables: {', '.join(missing_required)}"
        
        return check_result
    
    def run_health_check(self, full_check: bool = False) -> Dict[str, Any]:
        """Run all health checks"""
        print("🔍 Running PyPoe health check...")
        
        # Basic checks
        self.results["checks"]["process"] = self.check_process_running()
        self.results["checks"]["web_server"] = self.check_web_server_health()
        
        if full_check:
            print("🔍 Running full system check...")
            self.results["checks"]["logs"] = self.check_log_files()
            self.results["checks"]["api_endpoints"] = self.check_api_endpoints()
            self.results["checks"]["environment"] = self.check_environment()
        
        # Determine overall status
        statuses = [check["status"] for check in self.results["checks"].values()]
        if "fail" in statuses:
            self.results["overall_status"] = "fail"
        elif "warn" in statuses:
            self.results["overall_status"] = "warn"
        else:
            self.results["overall_status"] = "pass"
        
        return self.results
    
    def print_results(self, json_output: bool = False):
        """Print health check results"""
        if json_output:
            print(json.dumps(self.results, indent=2))
            return
        
        # Human-readable output
        status_icons = {"pass": "✅", "warn": "⚠️", "fail": "❌", "unknown": "❓"}
        
        print(f"\n{status_icons[self.results['overall_status']]} Overall Status: {self.results['overall_status'].upper()}")
        print(f"📅 Check Time: {self.results['timestamp']}")
        print("\n📋 Check Results:")
        
        for check_name, check_result in self.results["checks"].items():
            status = check_result["status"]
            message = check_result["message"]
            print(f"   {status_icons[status]} {check_name.title()}: {message}")
            
            # Show details for failed checks
            if status in ["fail", "warn"] and check_result.get("details"):
                for key, value in check_result["details"].items():
                    if isinstance(value, dict):
                        print(f"      • {key}: {json.dumps(value, indent=8)}")
                    else:
                        print(f"      • {key}: {value}")
        
        # Exit code for monitoring systems
        if self.results["overall_status"] == "fail":
            sys.exit(2)
        elif self.results["overall_status"] == "warn":
            sys.exit(1)
        else:
            sys.exit(0)

def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="PyPoe Health Check")
    parser.add_argument("--full", action="store_true", help="Run full system check")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    
    args = parser.parse_args()
    
    checker = HealthChecker()
    results = checker.run_health_check(full_check=args.full)
    checker.print_results(json_output=args.json)

if __name__ == "__main__":
    main() 