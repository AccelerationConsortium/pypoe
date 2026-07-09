// NB: do NOT declare `const PYPOE_BASE` here — app.js already declares it at
// top level, and classic <script> tags share one global lexical scope, so a
// second top-level declaration throws "Identifier 'PYPOE_BASE' has already been
// declared" and aborts whichever script loads second. Read window.PYPOE_BASE
// (set by the inline head script) directly instead.

// Status Bar Management
class StatusBar {
    constructor() {
        this.statusData = null;
        this.updateInterval = null;
        this.isInitialized = false;
        
        // Initialize when DOM is ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.init());
        } else {
            this.init();
        }
    }
    
    async init() {
        if (this.isInitialized) return;
        this.isInitialized = true;
        
        await this.loadStatus();
        this.startAutoRefresh();
    }
    
    async loadStatus() {
        try {
            const response = await fetch((window.PYPOE_BASE || "") + '/api/account/status');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            
            this.statusData = await response.json();
            this.updateUI();
            
        } catch (error) {
            console.error('Failed to load status:', error);
            this.showError();
        }
    }
    
    updateUI() {
        if (!this.statusData) return;
        
        this.updateApiKeyStatus();
        this.updateConnectivityStatus();
        this.updateStorageStatus();
        this.updateTimestamp();
    }
    
    updateApiKeyStatus() {
        const element = document.getElementById('status-api-key');
        if (!element) return;
        
        const status = this.statusData.api_key_status;
        let text = 'API: ';
        let className = 'status-item';
        
        switch (status) {
            case 'valid':
                text += 'Valid';
                className += ' status-success';
                break;
            case 'invalid':
                text += 'Invalid';
                className += ' status-error';
                break;
            case 'quota_exceeded':
                text += 'Quota Exceeded';
                className += ' status-error';
                break;
            case 'not_configured':
                text += 'Not Configured';
                className += ' status-warning';
                break;
            case 'error':
                text += 'Error';
                className += ' status-error';
                break;
            default:
                text += 'Unknown';
                className += ' status-warning';
        }
        
        element.textContent = text;
        element.parentElement.className = className;
    }
    
    updateConnectivityStatus() {
        const element = document.getElementById('status-connectivity');
        if (!element) return;
        
        const connectivity = this.statusData.connectivity;
        let text = 'Connection: ';
        let className = 'status-item';
        
        if (connectivity.status === 'connected') {
            text += 'Connected';
            if (connectivity.response_time_ms) {
                text += ` (${connectivity.response_time_ms}ms)`;
            }
            className += ' status-success';
        } else if (connectivity.status === 'error') {
            text += 'Error';
            className += ' status-error';
        } else {
            text += 'Unknown';
            className += ' status-warning';
        }
        
        element.textContent = text;
        element.parentElement.className = className;
    }
    
    updateStorageStatus() {
        const element = document.getElementById('status-storage');
        if (!element) return;
        
        const storage = this.statusData.storage_usage;
        let text = 'Storage: ';
        let className = 'status-item';
        
        if (storage && !storage.error) {
            const sizeMB = storage.database_size_mb || 0;
            text += `${sizeMB.toFixed(1)} MB`;
            
            // Add warning for large databases
            if (sizeMB > 100) {
                className += ' status-warning';
            } else if (sizeMB > 500) {
                className += ' status-error';
            }
        } else {
            text += 'N/A';
        }
        
        element.textContent = text;
        element.parentElement.className = className;
    }
    
    updateTimestamp() {
        const element = document.getElementById('status-last-update');
        if (!element) return;
        
        const now = new Date();
        const timeString = now.toLocaleTimeString([], { 
            hour: '2-digit', 
            minute: '2-digit',
            second: '2-digit'
        });
        
        element.textContent = timeString;
    }
    
    showError() {
        // Show error state in all status items
        const items = document.querySelectorAll('#status-bar .status-item');
        items.forEach(item => {
            item.className = 'status-item status-error';
        });
        
        const elements = [
            'status-api-key',
            'status-connectivity', 
            'status-usage',
            'status-storage'
        ];
        
        elements.forEach(id => {
            const element = document.getElementById(id);
            if (element) {
                element.textContent = element.textContent.split(':')[0] + ': Error';
            }
        });
        
        const timestampEl = document.getElementById('status-last-update');
        if (timestampEl) {
            timestampEl.textContent = 'Error';
        }
    }
    
    startAutoRefresh() {
        // Refresh every 30 seconds
        this.updateInterval = setInterval(() => {
            this.loadStatus();
        }, 30000);
    }
    
    stopAutoRefresh() {
        if (this.updateInterval) {
            clearInterval(this.updateInterval);
            this.updateInterval = null;
        }
    }
    
    // Manual refresh method
    async refresh() {
        await this.loadStatus();
    }
}

// Global status bar instance
window.StatusBar = StatusBar;

// Auto-initialize
const statusBar = new StatusBar(); 