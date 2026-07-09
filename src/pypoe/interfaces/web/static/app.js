const PYPOE_BASE = (typeof window !== "undefined" && window.PYPOE_BASE) || "";

class PyPoeApp {
    constructor() {
        this.currentConversationId = null;
        this.websocket = null;
        this.conversations = [];
        this.stats = {};
        this.currentConversation = null;
        this.streamingContent = '';
        this.messageTimeout = null;

        // Group/debate fan-out state. Reset on every user_message frame.
        this.currentGroupRow = null;          // DOM element wrapping the row of columns
        this.currentGroupColumns = {};        // model_name -> column DOM element
        this.currentGroupContent = {};        // model_name -> accumulated text
        this.pendingGroupColumns = new Set(); // model_names with start but no end
        
        this.initializeElements();
        this.bindEvents();
        this.loadInitialData().then(() => {
            // Initialize mode description after data is loaded
            setTimeout(() => {
                this.updateCurrentBotDisplay();
            }, 100); // Small delay to ensure DOM is ready
        });
    }
    
    initializeElements() {
        // Chat elements
        this.conversationsList = document.getElementById('conversations-list');
        this.messagesContainer = document.getElementById('messages-container');
        this.messageInput = document.getElementById('message-input');
        this.sendBtn = document.getElementById('send-btn');
        this.currentChatTitle = document.getElementById('current-chat-title');
        this.currentBotName = document.getElementById('current-bot-name');
        this.newChatBtn = document.getElementById('new-chat-btn');
        
        // Global header elements
        this.globalChatMode = document.getElementById('global-chat-mode');
        this.globalBotSelect = document.getElementById('global-bot-select');
        
        // Sidebar elements
        this.searchInput = document.getElementById('search-input');
        this.botFilter = document.getElementById('bot-filter');
        this.totalConversationsEl = document.getElementById('total-conversations');
        this.totalMessagesEl = document.getElementById('total-messages');
        
        // Modal elements
        this.newChatModal = document.getElementById('new-chat-modal');

        // Narrow-screen sidebar drawer
        this.sidebarEl = document.getElementById('sidebar');
        this.sidebarToggle = document.getElementById('sidebar-toggle');
        this.sidebarBackdrop = document.getElementById('sidebar-backdrop');
        // Matches the @media (max-width: 768px) block in style.css that
        // turns the sidebar into a drawer. Keep in sync if that changes.
        this._narrowMq = window.matchMedia('(max-width: 768px)');
    }
    
    bindEvents() {
        // Chat functionality
        this.sendBtn.addEventListener('click', () => this.sendMessage());
        this.messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });
        this.newChatBtn.addEventListener('click', () => this.showNewChatModal());
        
        // Welcome page new chat button
        const welcomeNewChatBtn = document.getElementById('welcome-new-chat-btn');
        if (welcomeNewChatBtn) {
            welcomeNewChatBtn.addEventListener('click', () => this.showNewChatModal());
        }
        
        // Sidebar functionality
        this.searchInput.addEventListener('input', () => this.debounceSearch());
        this.botFilter.addEventListener('change', () => this.filterConversations());
        
        // Global header functionality
        if (this.globalChatMode) {
            this.globalChatMode.addEventListener('change', () => {
                this.updateChatMode();
                this.updateLockingLogic();
            });
        }
        
        if (this.globalBotSelect) {
            this.globalBotSelect.addEventListener('change', () => {
                this.updateSelectedBot();
                this.updateLockingLogic();
            });
        }
        
        // Auto-resize textarea
        this.messageInput.addEventListener('input', () => this.autoResizeTextarea());
        
        // Global keyboard shortcuts for chat navigation
        document.addEventListener('keydown', (e) => {
            // Esc always closes the drawer if it's open, regardless of focus.
            if (e.key === 'Escape' && this._isSidebarOpen()) {
                e.preventDefault();
                this._closeSidebar();
                return;
            }
            // Other shortcuts: only handle when not typing in input
            if (document.activeElement !== this.messageInput && document.activeElement !== this.searchInput) {
                if (e.key === 'Home') {
                    e.preventDefault();
                    this.scrollChatToTop();
                } else if (e.key === 'End') {
                    e.preventDefault();
                    this.scrollToBottom();
                }
            }
        });

        // Sidebar drawer (narrow screens). The toggle button + backdrop are
        // always in the DOM; CSS hides them on wide screens.
        if (this.sidebarToggle) {
            this.sidebarToggle.addEventListener('click', () => this._toggleSidebar());
        }
        if (this.sidebarBackdrop) {
            this.sidebarBackdrop.addEventListener('click', () => this._closeSidebar());
        }
        // If the viewport grows past the breakpoint while the drawer is open,
        // drop the .open class so it doesn't linger when the layout switches
        // back to permanently-visible mode.
        const mqHandler = (e) => { if (!e.matches) this._closeSidebar(); };
        if (this._narrowMq.addEventListener) {
            this._narrowMq.addEventListener('change', mqHandler);
        } else if (this._narrowMq.addListener) {
            this._narrowMq.addListener(mqHandler);   // Safari < 14
        }
    }

    _isNarrow() {
        return !!(this._narrowMq && this._narrowMq.matches);
    }

    _isSidebarOpen() {
        return !!(this.sidebarEl && this.sidebarEl.classList.contains('open'));
    }

    _openSidebar() {
        if (!this.sidebarEl) return;
        this.sidebarEl.classList.add('open');
        if (this.sidebarBackdrop) this.sidebarBackdrop.classList.add('visible');
        if (this.sidebarToggle) this.sidebarToggle.setAttribute('aria-expanded', 'true');
    }

    _closeSidebar() {
        if (!this.sidebarEl) return;
        this.sidebarEl.classList.remove('open');
        if (this.sidebarBackdrop) this.sidebarBackdrop.classList.remove('visible');
        if (this.sidebarToggle) this.sidebarToggle.setAttribute('aria-expanded', 'false');
    }

    _toggleSidebar() {
        if (this._isSidebarOpen()) {
            this._closeSidebar();
        } else {
            this._openSidebar();
        }
    }
    
    async loadInitialData() {
        try {
            // Load conversations for sidebar
            const response = await fetch(PYPOE_BASE + '/api/conversations');
            this.conversations = await response.json();
            this.renderConversationsSidebar();
            
            // Load stats for sidebar
            await this.loadStats();
            this.populateBotFilter();
            
            // Update locking logic for initial state
            this.updateLockingLogic();
        } catch (error) {
            console.error('Error loading initial data:', error);
        }
    }
    
    async loadStats() {
        try {
            const response = await fetch(PYPOE_BASE + '/api/stats');
            this.stats = await response.json();
            this.updateStats();
        } catch (error) {
            console.error('Error loading stats:', error);
        }
    }

    updateStats() {
        if (this.totalConversationsEl) {
            this.totalConversationsEl.textContent = this.stats.total_conversations || 0;
        }
        if (this.totalMessagesEl) {
            this.totalMessagesEl.textContent = this.stats.total_messages || 0;
        }
    }
    
    _formatConvTime(value) {
        if (!value) return '';
        const d = new Date(value);
        if (Number.isNaN(d.getTime())) return value;
        return d.toLocaleString([], {
            month: 'short', day: 'numeric',
            hour: '2-digit', minute: '2-digit',
        });
    }

    _conversationItemHtml(conv) {
        const topic = conv.topic ? this.escapeHtml(conv.topic) : this.escapeHtml(conv.title || 'Untitled');
        const models = Array.isArray(conv.bot_names) && conv.bot_names.length
            ? conv.bot_names.map(b => this.escapeHtml(b)).join(' · ')
            : this.escapeHtml(conv.bot_name || '');
        const time = this._formatConvTime(conv.updated_at || conv.created_at);
        return `
            <div class="conversation-item" data-id="${conv.id}">
                <div class="conversation-info">
                    <div class="conv-topic">${topic}</div>
                    <div class="conv-meta">
                        <span class="conv-models" title="${models}">${models}</span>
                        <span class="conv-time">${time}</span>
                    </div>
                </div>
                <button class="delete-btn" data-id="${conv.id}" title="Delete">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        `;
    }

    renderConversationsSidebar() {
        if (!this.conversationsList) return;

        if (this.conversations.length === 0) {
            this.conversationsList.innerHTML = `
                <div class="empty-conversations">
                    <p>No conversations yet</p>
                    <p>Click "New Chat" to start</p>
                </div>
            `;
            return;
        }

        this.conversationsList.innerHTML = this.conversations
            .map(conv => this._conversationItemHtml(conv))
            .join('');
        
        // Bind conversation events
        this.bindConversationEvents();
    }
    
    async selectConversation(conversationId, retryCount = 0) {
        try {
            this.currentConversationId = conversationId;
            
            // Update active conversation in sidebar
            this.conversationsList.querySelectorAll('.conversation-item').forEach(item => {
                item.classList.toggle('active', item.dataset.id === conversationId);
            });
            
            // Load conversation details
            const conv = this.conversations.find(c => c.id === conversationId);
            if (conv) {
                this.currentConversation = conv;
                this.currentChatTitle.textContent = conv.topic || conv.title;
                this.currentBotName.textContent = `Bot: ${conv.bot_name} | Mode: ${conv.chat_mode || 'chatbot'}`;
                if (this.globalBotSelect) {
                    this.globalBotSelect.value = conv.bot_name;
                }
                if (this.globalChatMode && conv.chat_mode) {
                    this.globalChatMode.value = conv.chat_mode;
                    this.updateChatMode(); // Update the label when conversation is selected
                }
            }
            
            // Update locking logic based on new state
            this.updateLockingLogic();
            
            // Load messages
            await this.loadConversationMessages(conversationId);
            
            // Enable input
            this.enableInput();
            
            // Setup websocket
            await this.setupWebSocket(conversationId);
            
        } catch (error) {
            console.error('Error selecting conversation:', error);
            
            // Retry logic for new conversations that might not be immediately available
            if (retryCount < 3 && error.message && error.message.includes('not found')) {
                console.log(`Retrying conversation selection (attempt ${retryCount + 1}/3)...`);
                await new Promise(resolve => setTimeout(resolve, 1000 * (retryCount + 1)));
                return this.selectConversation(conversationId, retryCount + 1);
            }
        }
    }
    
    async loadConversationMessages(conversationId) {
        try {
            const response = await fetch(`${PYPOE_BASE}/api/conversation/${conversationId}/messages`);
            const messages = await response.json();

            this.messagesContainer.innerHTML = '';

            // For debate conversations, pin a topic + roles banner at the
            // top of the chat. The banner is editable and PATCHes the
            // conversation on save.
            if (this.currentConversation?.chat_mode === 'debate') {
                this.messagesContainer.appendChild(this._renderDebateBanner());
            }

            // For group/debate conversations, lay every turn out as a row
            // with one column for the user and one column per model. A
            // user message opens a new row with pre-created placeholders;
            // following assistant messages fill those placeholders.
            const multi = this._isMultiMode();
            const bots = this.currentConversation?.bot_names || [];
            let openRow = null;
            let userCell = null;
            let openBotCells = {};  // model_name -> placeholder DOM node

            const newRow = () => {
                const row = document.createElement('div');
                row.className = 'turn-row multi with-user';
                row.style.setProperty('--bot-count', String(bots.length));

                const u = document.createElement('div');
                u.className = 'message user group-user-cell placeholder';
                row.appendChild(u);
                userCell = u;

                openBotCells = {};
                bots.forEach(bot => {
                    const ph = document.createElement('div');
                    ph.className = 'message assistant group-column placeholder';
                    ph.dataset.model = bot;
                    row.appendChild(ph);
                    openBotCells[bot] = ph;
                });

                this.messagesContainer.appendChild(row);
                return row;
            };

            const fillUserCell = (msg) => {
                userCell.classList.remove('placeholder');
                userCell.innerHTML = '';
                const avatar = document.createElement('div');
                avatar.className = 'message-avatar';
                avatar.innerHTML = '<i class="fas fa-user"></i>';
                const wrapper = document.createElement('div');
                wrapper.className = 'message-wrapper';
                const contentDiv = document.createElement('div');
                contentDiv.className = 'message-content';
                const processed = this.processContentForDisplay(msg.content);
                if (processed !== msg.content) {
                    contentDiv.innerHTML = processed;
                } else {
                    contentDiv.textContent = msg.content;
                }
                wrapper.appendChild(contentDiv);
                if (msg.timestamp) {
                    const meta = document.createElement('div');
                    meta.className = 'message-metadata user-metadata';
                    meta.innerHTML = `<span class="timestamp">${this.formatTime(msg.timestamp)}</span>`;
                    wrapper.appendChild(meta);
                }
                userCell.appendChild(avatar);
                userCell.appendChild(wrapper);
            };

            for (const msg of messages) {
                if (multi && msg.role === 'user') {
                    openRow = newRow();
                    fillUserCell(msg);
                } else if (multi && msg.role === 'assistant' && msg.model_name) {
                    if (!openRow) openRow = newRow();
                    const placeholder = openBotCells[msg.model_name];
                    const col = this._buildGroupColumn(msg.model_name, msg.content, false);
                    if (placeholder) {
                        placeholder.replaceWith(col);
                        openBotCells[msg.model_name] = col;
                    } else {
                        // Unknown bot in history (config drift?); append.
                        openRow.appendChild(col);
                    }
                } else {
                    // Chatbot mode (or legacy rows) — flat layout.
                    openRow = null;
                    this.addMessageToDOM(msg.content, msg.role, false, {
                        bot_name: msg.model_name || msg.bot_name,
                        timestamp: msg.timestamp,
                    });
                }
            }

            // Scroll to bottom once after all messages are loaded
            requestAnimationFrame(() => {
                this.scrollToBottom();
            });
        } catch (error) {
            console.error('Error loading messages:', error);
        }
    }
    
    async setupWebSocket(conversationId) {
        // Clear any existing error timeout
        if (this.websocketErrorTimeout) {
            clearTimeout(this.websocketErrorTimeout);
            this.websocketErrorTimeout = null;
        }
        
        // Close existing connection if it exists
        if (this.websocket) {
            // Mark that we're intentionally closing for a new connection
            this.websocket.isIntentionalClose = true;
            this.websocket.close();
            
            // Small delay to ensure the previous connection is fully closed
            await new Promise(resolve => setTimeout(resolve, 100));
        }
        
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}${PYPOE_BASE}/ws/chat/${conversationId}`;
        
        console.log('Setting up WebSocket for conversation:', conversationId);
        
        // Create new WebSocket connection
        this.websocket = new WebSocket(wsUrl);
        this.websocket.isIntentionalClose = false; // Track if this is an intentional close
        
        this.websocket.onopen = () => {
            console.log('WebSocket connected successfully');
            // Clear any pending error timeouts
            if (this.websocketErrorTimeout) {
                clearTimeout(this.websocketErrorTimeout);
                this.websocketErrorTimeout = null;
            }
        };
        
        this.websocket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleWebSocketMessage(data);
        };
        
        this.websocket.onerror = (error) => {
            console.error('WebSocket error:', error);
            // Don't show error immediately - give it a chance to connect
            this.websocketErrorTimeout = setTimeout(() => {
                if (this.websocket && this.websocket.readyState !== WebSocket.OPEN && !this.websocket.isIntentionalClose) {
                    this.enableInput();
                    this.addMessage('❌ Connection error. Please try again.', 'error', false);
                }
            }, 2000);
        };
        
        this.websocket.onclose = (event) => {
            console.log('WebSocket closed:', event);
            
            // Clear any pending error timeouts
            if (this.websocketErrorTimeout) {
                clearTimeout(this.websocketErrorTimeout);
                this.websocketErrorTimeout = null;
            }
            
            // Only show error if it's not an intentional close and not a normal closure
            if (!this.websocket.isIntentionalClose && event.code !== 1000) {
                this.enableInput();
                this.addMessage('❌ Connection lost. Please refresh the page.', 'error', false);
            }
            
            // Re-enable input on WebSocket disconnect
            this.enableInput();
        };
    }
    
    handleWebSocketMessage(data) {
        switch (data.type) {
            case 'user_message':
                // A new user message starts a new group/debate round. Reset
                // round state first so the row created for this turn lives
                // in a fresh container.
                this.currentGroupRow = null;
                this.currentGroupColumns = {};
                this.currentGroupContent = {};
                this.pendingGroupColumns = new Set();
                if (this._isMultiMode()) {
                    this._addUserToGroupRow(data.content, {
                        timestamp: new Date().toISOString(),
                    });
                } else {
                    this.addMessage(data.content, 'user', false);
                }
                break;
            case 'bot_response_start':
                if (data.model_name) {
                    this._beginGroupColumn(data.model_name);
                } else {
                    this.currentBotMessage = this.addMessage('', 'assistant', true);
                    this.streamingContent = ''; // Track streaming content
                    this.isShowingThinking = false; // Track if we're showing thinking message
                }
                break;
            case 'bot_response_chunk':
                if (data.model_name) {
                    this._appendGroupChunk(data.model_name, data.content);
                } else if (this.currentBotMessage && data.content) {
                    const contentDiv = this.currentBotMessage.querySelector('.message-content');

                    // Check if this chunk is a thinking/generating message
                    if (this.isThinkingMessage(data.content)) {
                        // Show thinking message temporarily (only if we haven't shown real content yet)
                        if (!this.streamingContent || this.isShowingThinking) {
                            // Remove typing indicator if present
                            const typingIndicator = contentDiv.querySelector('.typing-indicator');
                            if (typingIndicator) {
                                typingIndicator.remove();
                            }

                            contentDiv.textContent = data.content;
                            this.isShowingThinking = true;
                            this.scrollToBottom();
                        }
                        return; // Don't accumulate thinking messages
                    }

                    // Real content arrived - replace thinking message if showing
                    if (this.isShowingThinking) {
                        this.streamingContent = ''; // Reset accumulated content
                        this.isShowingThinking = false;
                    }

                    // Accumulate real content
                    this.streamingContent += data.content;

                    // Remove typing indicator if present
                    const typingIndicator = contentDiv.querySelector('.typing-indicator');
                    if (typingIndicator) {
                        typingIndicator.remove();
                    }

                    // Update content with processed display
                    const processedContent = this.processContentForDisplay(this.streamingContent);
                    if (processedContent !== this.streamingContent) {
                        contentDiv.innerHTML = processedContent;
                    } else {
                        contentDiv.textContent = this.streamingContent;
                    }

                    this.scrollToBottom();
                }
                break;
            case 'bot_response_end':
                if (data.model_name) {
                    this._endGroupColumn(data.model_name);
                    // Re-enable input once every column in this round has ended.
                    if (this.pendingGroupColumns.size === 0) {
                        this.enableInput();
                    }
                } else {
                    // Final processing of complete message
                    if (this.currentBotMessage && this.streamingContent) {
                        const contentDiv = this.currentBotMessage.querySelector('.message-content');
                        const processedContent = this.processContentForDisplay(this.streamingContent);
                        if (processedContent !== this.streamingContent) {
                            contentDiv.innerHTML = processedContent;
                        } else {
                            contentDiv.textContent = this.streamingContent;
                        }
                    }
                    this.currentBotMessage = null;
                    this.streamingContent = '';
                    this.enableInput();
                }
                break;
            case 'error':
                if (data.model_name) {
                    // Surface the error inside the column that produced it,
                    // so the rest of the round keeps streaming.
                    const column = this.currentGroupColumns[data.model_name];
                    if (column) {
                        const contentDiv = column.querySelector('.message-content');
                        const typingIndicator = contentDiv.querySelector('.typing-indicator');
                        if (typingIndicator) typingIndicator.remove();
                        const err = document.createElement('div');
                        err.className = 'group-column-error';
                        err.textContent = '❌ ' + (data.content || 'Error');
                        contentDiv.appendChild(err);
                    } else {
                        this.addMessage(`❌ ${data.model_name}: ${data.content}`, 'error', false);
                    }
                } else {
                    this.addMessage(data.content, 'error', false);
                    // Re-enable input on error responses
                    this.enableInput();
                }
                break;
            case 'topic_updated':
                // Update the conversation topic in the UI
                console.log('Topic updated:', data);
                if (data.conversation_id && data.topic) {
                    // Update in conversations array
                    const conv = this.conversations.find(c => c.id === data.conversation_id);
                    if (conv) {
                        conv.topic = data.topic;
                        
                        // Update sidebar if this conversation is visible
                        const convElement = this.conversationsList.querySelector(`[data-id="${data.conversation_id}"]`);
                        if (convElement) {
                            const titleElement = convElement.querySelector('h4');
                            if (titleElement) {
                                titleElement.textContent = data.topic;
                            }
                        }
                        
                        // Update chat header if this is the current conversation
                        if (this.currentConversationId === data.conversation_id) {
                            this.currentChatTitle.textContent = data.topic;
                        }
                    }
                }
                break;
            default:
                console.log('Unknown message type:', data.type);
        }
    }
    
    addMessageToDOM(content, role, streaming = false, metadata = {}) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role}`;
        
        const avatar = document.createElement('div');
        avatar.className = 'message-avatar';
        avatar.innerHTML = role === 'user' ? '<i class="fas fa-user"></i>' : '<i class="fas fa-robot"></i>';
        
        const contentWrapper = document.createElement('div');
        contentWrapper.className = 'message-wrapper';
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        
        // Process content for images
        const processedContent = this.processContentForDisplay(content);
        if (processedContent !== content) {
            // Content contains HTML (processed images)
            contentDiv.innerHTML = processedContent;
        } else {
            // Plain text content
            contentDiv.textContent = content;
        }
        
        if (streaming) {
            const typingIndicator = document.createElement('div');
            typingIndicator.className = 'typing-indicator';
            typingIndicator.innerHTML = `
                <span>Thinking</span>
                <div class="typing-dots">
                    <span></span><span></span><span></span>
                </div>
            `;
            contentDiv.appendChild(typingIndicator);
        }
        
        contentWrapper.appendChild(contentDiv);
        
        // Add metadata for assistant messages
        if (role === 'assistant' && (metadata.bot_name || metadata.timestamp)) {
            const metadataDiv = document.createElement('div');
            metadataDiv.className = 'message-metadata';
            
            const parts = [];
            if (metadata.bot_name) {
                parts.push(`<span class="bot-name"><i class="fas fa-robot"></i> ${this.escapeHtml(metadata.bot_name)}</span>`);
            }
            if (metadata.timestamp) {
                const timeStr = this.formatTime(metadata.timestamp);
                parts.push(`<span class="timestamp">${timeStr}</span>`);
            }
            
            metadataDiv.innerHTML = parts.join(' • ');
            contentWrapper.appendChild(metadataDiv);
        }
        
        // Add timestamp for user messages
        if (role === 'user' && metadata.timestamp) {
            const metadataDiv = document.createElement('div');
            metadataDiv.className = 'message-metadata user-metadata';
            metadataDiv.innerHTML = `<span class="timestamp">${this.formatTime(metadata.timestamp)}</span>`;
            contentWrapper.appendChild(metadataDiv);
        }
        
        messageDiv.appendChild(avatar);
        messageDiv.appendChild(contentWrapper);
        
        this.messagesContainer.appendChild(messageDiv);
        
        // Force layout recalculation and scroll after DOM update
        if (!streaming) {
            requestAnimationFrame(() => {
                this.scrollToBottom();
            });
        }
        
        return messageDiv;
    }

    // Backward compatibility method
    addMessage(content, role, streaming = false) {
        return this.addMessageToDOM(content, role, streaming, {
            bot_name: role === 'assistant' ? (this.currentConversation?.bot_name || this.globalBotSelect?.value) : null,
            timestamp: new Date().toISOString()
        });
    }

    _isMultiMode() {
        const mode = this.currentConversation?.chat_mode;
        return mode === 'group' || mode === 'debate';
    }

    _ensureGroupRow() {
        if (this.currentGroupRow) return this.currentGroupRow;
        const row = document.createElement('div');
        row.className = 'turn-row multi with-user';
        const bots = this.currentConversation?.bot_names || [];
        row.style.setProperty('--bot-count', String(bots.length));

        // Pre-create the user cell + one placeholder per bot in
        // ``bot_names`` order. Concurrent ``bot_response_start`` frames
        // fill these placeholders in deterministic positions, so column
        // order is stable across runs.
        const userCell = document.createElement('div');
        userCell.className = 'message user group-user-cell placeholder';
        row.appendChild(userCell);
        this.currentGroupUserCell = userCell;

        bots.forEach(bot => {
            const placeholder = document.createElement('div');
            placeholder.className = 'message assistant group-column placeholder';
            placeholder.dataset.model = bot;
            row.appendChild(placeholder);
            this.currentGroupColumns[bot] = placeholder;
        });

        this.messagesContainer.appendChild(row);
        this.currentGroupRow = row;
        return row;
    }

    _addUserToGroupRow(content, metadata = {}) {
        this._ensureGroupRow();
        const cell = this.currentGroupUserCell;
        cell.classList.remove('placeholder');
        cell.innerHTML = '';

        const avatar = document.createElement('div');
        avatar.className = 'message-avatar';
        avatar.innerHTML = '<i class="fas fa-user"></i>';

        const wrapper = document.createElement('div');
        wrapper.className = 'message-wrapper';

        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        const processed = this.processContentForDisplay(content);
        if (processed !== content) {
            contentDiv.innerHTML = processed;
        } else {
            contentDiv.textContent = content;
        }
        wrapper.appendChild(contentDiv);
        if (metadata.timestamp) {
            const meta = document.createElement('div');
            meta.className = 'message-metadata user-metadata';
            meta.innerHTML = `<span class="timestamp">${this.formatTime(metadata.timestamp)}</span>`;
            wrapper.appendChild(meta);
        }

        cell.appendChild(avatar);
        cell.appendChild(wrapper);
        this.scrollToBottom();
        return cell;
    }

    _beginGroupColumn(modelName) {
        this._ensureGroupRow();
        const placeholder = this.currentGroupColumns[modelName];
        if (!placeholder) {
            // Defensive: backend streamed a bot we didn't expect. Drop it
            // into a fresh column at the end of the row.
            const fallback = this._buildGroupColumn(modelName, '', true);
            this.currentGroupRow.appendChild(fallback);
            this.currentGroupColumns[modelName] = fallback;
        } else {
            // Replace the placeholder in-place to preserve column order.
            const built = this._buildGroupColumn(modelName, '', true);
            placeholder.replaceWith(built);
            this.currentGroupColumns[modelName] = built;
        }
        this.currentGroupContent[modelName] = '';
        this.pendingGroupColumns.add(modelName);
        this.scrollToBottom();
    }

    _appendGroupChunk(modelName, content) {
        if (!content) return;
        const column = this.currentGroupColumns[modelName];
        if (!column) return;
        if (this.isThinkingMessage(content)) {
            // Treat thinking chunks the same way the single-bot path does:
            // show them only while no real content has arrived yet.
            if (!this.currentGroupContent[modelName]) {
                const contentDiv = column.querySelector('.message-content');
                const typingIndicator = contentDiv.querySelector('.typing-indicator');
                if (typingIndicator) typingIndicator.remove();
                contentDiv.textContent = content;
                this.scrollToBottom();
            }
            return;
        }
        this.currentGroupContent[modelName] += content;
        const contentDiv = column.querySelector('.message-content');
        const typingIndicator = contentDiv.querySelector('.typing-indicator');
        if (typingIndicator) typingIndicator.remove();
        const accumulated = this.currentGroupContent[modelName];
        const processed = this.processContentForDisplay(accumulated);
        if (processed !== accumulated) {
            contentDiv.innerHTML = processed;
        } else {
            contentDiv.textContent = accumulated;
        }
        this.scrollToBottom();
    }

    _endGroupColumn(modelName) {
        const column = this.currentGroupColumns[modelName];
        if (column) {
            const contentDiv = column.querySelector('.message-content');
            const typingIndicator = contentDiv.querySelector('.typing-indicator');
            if (typingIndicator) typingIndicator.remove();
            const accumulated = this.currentGroupContent[modelName] || '';
            if (accumulated) {
                const processed = this.processContentForDisplay(accumulated);
                if (processed !== accumulated) {
                    contentDiv.innerHTML = processed;
                } else {
                    contentDiv.textContent = accumulated;
                }
            }
        }
        this.pendingGroupColumns.delete(modelName);
    }

    _renderDebateBanner() {
        // Build a pinned banner showing the debate topic + per-bot roles,
        // with an inline edit affordance for the topic. The banner sits at
        // the top of messages-container and scrolls with the chat (v1).
        const conv = this.currentConversation;
        const banner = document.createElement('div');
        banner.className = 'debate-banner';

        const heading = document.createElement('div');
        heading.className = 'debate-banner-heading';
        heading.innerHTML = '<i class="fas fa-bullhorn"></i> Debate topic';
        banner.appendChild(heading);

        const view = document.createElement('div');
        view.className = 'debate-banner-view';
        const topicPara = document.createElement('p');
        topicPara.className = 'debate-banner-topic';
        topicPara.textContent = conv?.debate_topic || '(no topic set)';
        const editBtn = document.createElement('button');
        editBtn.type = 'button';
        editBtn.className = 'btn btn-secondary btn-small';
        editBtn.innerHTML = '<i class="fas fa-pen"></i> Edit topic';
        view.appendChild(topicPara);
        view.appendChild(editBtn);
        banner.appendChild(view);

        const editor = document.createElement('div');
        editor.className = 'debate-banner-editor hidden';
        const textarea = document.createElement('textarea');
        textarea.rows = 3;
        textarea.value = conv?.debate_topic || '';
        const saveBtn = document.createElement('button');
        saveBtn.type = 'button';
        saveBtn.className = 'btn btn-primary btn-small';
        saveBtn.textContent = 'Save';
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn btn-secondary btn-small';
        cancelBtn.textContent = 'Cancel';
        editor.appendChild(textarea);
        const editorActions = document.createElement('div');
        editorActions.className = 'debate-banner-editor-actions';
        editorActions.appendChild(saveBtn);
        editorActions.appendChild(cancelBtn);
        editor.appendChild(editorActions);
        banner.appendChild(editor);

        editBtn.addEventListener('click', () => {
            view.classList.add('hidden');
            editor.classList.remove('hidden');
            textarea.focus();
        });
        cancelBtn.addEventListener('click', () => {
            textarea.value = conv?.debate_topic || '';
            editor.classList.add('hidden');
            view.classList.remove('hidden');
        });
        saveBtn.addEventListener('click', async () => {
            const next = textarea.value.trim();
            if (!next) {
                alert('Topic cannot be empty.');
                return;
            }
            saveBtn.disabled = true;
            try {
                const resp = await fetch(`${PYPOE_BASE}/api/conversation/${conv.id}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ debate_topic: next }),
                });
                const result = await resp.json();
                if (!resp.ok) {
                    alert(`Update failed: ${result?.detail || resp.statusText}`);
                    return;
                }
                // Update local state and rerender just the view band.
                conv.debate_topic = result.debate_topic;
                topicPara.textContent = result.debate_topic;
                editor.classList.add('hidden');
                view.classList.remove('hidden');
            } finally {
                saveBtn.disabled = false;
            }
        });

        // Roles summary row — read-only in this version; the New Chat modal
        // is the editor for assignments.
        const rolesRow = document.createElement('div');
        rolesRow.className = 'debate-banner-roles';
        const assignments = conv?.bot_assignments || {};
        (conv?.bot_names || []).forEach(bot => {
            const pill = document.createElement('span');
            pill.className = 'debate-role-pill';
            const a = assignments[bot] || {};
            const role = a.role === 'custom' ? (a.custom_label || 'custom') : (a.role || 'unassigned').replace(/_/g, ' ');
            pill.textContent = `${bot} · ${role}`;
            rolesRow.appendChild(pill);
        });
        banner.appendChild(rolesRow);

        return banner;
    }

    _getRoleLabel(modelName) {
        // Human-readable role string for column headers. Empty when not in
        // debate mode or when the model has no assignment recorded.
        const assignments = this.currentConversation?.bot_assignments;
        if (!assignments) return '';
        const a = assignments[modelName];
        if (!a) return '';
        if (a.role === 'custom') return a.custom_label || 'custom';
        return a.role.replace(/_/g, ' ');
    }

    _buildGroupColumn(modelName, content, streaming = false) {
        // Mirrors addMessageToDOM but tagged for the column grid layout.
        const wrapper = document.createElement('div');
        wrapper.className = 'message assistant group-column';
        wrapper.dataset.model = modelName;

        const avatar = document.createElement('div');
        avatar.className = 'message-avatar';
        avatar.innerHTML = '<i class="fas fa-robot"></i>';

        const contentWrapper = document.createElement('div');
        contentWrapper.className = 'message-wrapper';

        const header = document.createElement('div');
        header.className = 'group-column-header';
        const roleLabel = this._getRoleLabel(modelName);
        header.textContent = roleLabel ? `${modelName} — ${roleLabel}` : modelName;
        contentWrapper.appendChild(header);

        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        if (content) {
            const processed = this.processContentForDisplay(content);
            if (processed !== content) {
                contentDiv.innerHTML = processed;
            } else {
                contentDiv.textContent = content;
            }
        }
        if (streaming) {
            const typing = document.createElement('div');
            typing.className = 'typing-indicator';
            typing.innerHTML = '<span>Thinking</span><div class="typing-dots"><span></span><span></span><span></span></div>';
            contentDiv.appendChild(typing);
        }
        contentWrapper.appendChild(contentDiv);

        wrapper.appendChild(avatar);
        wrapper.appendChild(contentWrapper);
        return wrapper;
    }

    formatTime(timestamp) {
        const date = new Date(timestamp);
        return date.toLocaleTimeString([], { 
            hour: '2-digit', 
            minute: '2-digit' 
        });
    }
    
    async sendMessage() {
        const message = this.messageInput.value.trim();
        if (!message || !this.currentConversationId) return;
        
        this.messageInput.value = '';
        this.disableInput();
        
        // Check WebSocket connection
        if (!this.websocket || this.websocket.readyState !== WebSocket.OPEN) {
            this.addMessage('❌ Connection not available. Please refresh the page.', 'error', false);
            this.enableInput();
            return;
        }
        
        try {
            this.websocket.send(JSON.stringify({
                message: message,
                bot_name: this.globalBotSelect ? this.globalBotSelect.value : null
            }));
            
            // Set timeout to re-enable input if no response comes
            this.clearMessageTimeout();
            this.messageTimeout = setTimeout(() => {
                console.warn('Message timeout - re-enabling input');
                this.addMessage('⏱️ Response timeout. Please try again.', 'error', false);
                this.enableInput();
            }, 60000); // 60 second timeout
            
        } catch (error) {
            console.error('Error sending message:', error);
            this.addMessage('❌ Failed to send message. Please try again.', 'error', false);
            this.enableInput();
        }
        
        this.autoResizeTextarea();
    }
    
    disableInput() {
        this.messageInput.disabled = true;
        this.sendBtn.disabled = true;
        this.messageInput.placeholder = 'Sending message...';
    }
    
    enableInput() {
        this.messageInput.disabled = false;
        this.sendBtn.disabled = false;
        this.messageInput.placeholder = 'Type your message here...';
        this.clearMessageTimeout();
    }
    
    clearMessageTimeout() {
        if (this.messageTimeout) {
            clearTimeout(this.messageTimeout);
            this.messageTimeout = null;
        }
    }
    


    lockBotSelector(lock = true, reason = '') {
        if (this.globalBotSelect) {
            this.globalBotSelect.disabled = lock;
            
            // Update label to show lock status
            const botLabel = document.querySelector('.bot-controls label');
            
            // Add visual styling
            if (lock) {
                this.globalBotSelect.classList.add('locked');
                this.globalBotSelect.title = reason || 'Bot selection is locked';
                if (botLabel) {
                    botLabel.innerHTML = 'Bot: <i class="fas fa-lock" style="color: #e74c3c; margin-left: 4px;" title="' + (reason || 'Locked') + '"></i>';
                }
            } else {
                this.globalBotSelect.classList.remove('locked');
                this.globalBotSelect.title = 'Select AI bot';
                if (botLabel) {
                    botLabel.textContent = 'Bot:';
                }
            }
        }
    }

    lockChatMode(lock = true, reason = '') {
        if (this.globalChatMode) {
            this.globalChatMode.disabled = lock;
            
            // Update label to show lock status
            const modeLabel = document.querySelector('.mode-controls label');
            
            // Add visual styling
            if (lock) {
                this.globalChatMode.classList.add('locked');
                this.globalChatMode.title = reason || 'Chat mode selection is locked';
                if (modeLabel) {
                    modeLabel.innerHTML = 'Mode: <i class="fas fa-lock" style="color: #e74c3c; margin-left: 4px;" title="' + (reason || 'Locked') + '"></i>';
                }
            } else {
                this.globalChatMode.classList.remove('locked');
                this.globalChatMode.title = 'Select chat mode';
                if (modeLabel) {
                    modeLabel.textContent = 'Mode:';
                }
            }
        }
    }

    updateLockingLogic() {
        const chatMode = this.globalChatMode ? this.globalChatMode.value : 'chatbot';
        
        // Chat mode locking: lock when viewing an existing conversation
        if (this.currentConversationId) {
            this.lockChatMode(true, 'Chat mode is locked for existing conversations');
        } else {
            this.lockChatMode(false);
        }
        
        // Bot locking logic based on frontend rules
        if (!this.currentConversationId) {
            // No conversation selected
            this.lockBotSelector(true, 'Select a conversation first');
        } else if (chatMode === 'chatbot' && this.currentConversation) {
            // Chatbot mode with active conversation
            this.lockBotSelector(true, 'Bot locked in single chat mode');
        } else {
            // Other modes or no active conversation
            this.lockBotSelector(false);
        }
    }

    populateBotFilter() {
        if (!this.botFilter) return;
        
        const bots = [...new Set(this.conversations.map(c => c.bot_name).filter(Boolean))];
        
        this.botFilter.innerHTML = '<option value="">All Bots</option>';
        bots.forEach(bot => {
            const option = document.createElement('option');
            option.value = bot;
            option.textContent = bot;
            this.botFilter.appendChild(option);
        });
    }

    debounceSearch() {
        clearTimeout(this.searchTimeout);
        this.searchTimeout = setTimeout(() => this.filterConversations(), 300);
    }

    filterConversations() {
        const query = this.searchInput?.value.toLowerCase().trim() || '';
        const botFilter = this.botFilter?.value || '';
        
        let filtered = this.conversations;
        
        if (botFilter) {
            filtered = filtered.filter(conv => conv.bot_name === botFilter);
        }
        
        if (query) {
            filtered = filtered.filter(conv => 
                conv.title.toLowerCase().includes(query) ||
                conv.bot_name.toLowerCase().includes(query)
            );
        }
        
        this.renderFilteredConversations(filtered);
    }

    renderFilteredConversations(filteredConversations) {
        if (!this.conversationsList) return;
        
        if (filteredConversations.length === 0) {
            this.conversationsList.innerHTML = `
                <div class="empty-conversations">
                    <p>No conversations found</p>
                    <p>Try adjusting your search</p>
                </div>
            `;
            return;
        }
        
        this.conversationsList.innerHTML = filteredConversations
            .map(conv => this._conversationItemHtml(conv))
            .join('');
        
        // Re-bind events for filtered conversations
        this.bindConversationEvents();
    }

    bindConversationEvents() {
        // Bind conversation selection events
        this.conversationsList.querySelectorAll('.conversation-item').forEach(item => {
            item.addEventListener('click', (e) => {
                if (!e.target.closest('.delete-btn')) {
                    this.selectConversation(item.dataset.id);
                    // On narrow screens the sidebar is a drawer; auto-close
                    // so the user can see the chat they just picked.
                    if (this._isNarrow()) this._closeSidebar();
                }
            });
        });
        
        // Bind delete events
        this.conversationsList.querySelectorAll('.delete-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.deleteConversation(btn.dataset.id);
            });
        });
    }

    async deleteConversation(conversationId) {
        if (!confirm('Are you sure you want to delete this conversation?')) return;
        
        try {
            const response = await fetch(`${PYPOE_BASE}/api/conversation/${conversationId}`, {
                method: 'DELETE'
            });
            
            if (response.ok) {
                // Remove from arrays
                this.conversations = this.conversations.filter(c => c.id !== conversationId);
                
                // Re-render
                this.renderConversationsSidebar();
                this.populateBotFilter();
                await this.loadStats();
                
                // Clear chat if this was the active conversation
                if (this.currentConversationId === conversationId) {
                    this.currentConversationId = null;
                    this.currentConversation = null;
                    this.messagesContainer.innerHTML = `
                        <div class="welcome-message">
                            <i class="fas fa-robot fa-3x"></i>
                            <h3>Welcome to PyPoe Chat!</h3>
                            <p>Select a conversation from the sidebar or create a new one to start chatting with AI bots.</p>
                            <button id="welcome-new-chat-btn" class="btn btn-primary" style="margin-top: 20px;">
                                <i class="fas fa-plus"></i> Start New Chat
                            </button>
                        </div>
                    `;
                    this.currentChatTitle.textContent = 'Select or create a conversation';
                    this.currentBotName.textContent = 'Choose a chat mode and bot above to get started';
                    this.disableInput();
                    this.messageInput.placeholder = 'Select a conversation to start chatting...';
                    
                    // Update locking logic for no active conversation
                    this.updateLockingLogic();
                    
                    // Re-bind welcome button event
                    const welcomeNewChatBtn = document.getElementById('welcome-new-chat-btn');
                    if (welcomeNewChatBtn) {
                        welcomeNewChatBtn.addEventListener('click', () => this.showNewChatModal());
                    }
                }
            }
        } catch (error) {
            console.error('Error deleting conversation:', error);
        }
    }
    
    updateChatMode() {
        // Update UI or behavior based on chat mode
        const selectedMode = this.globalChatMode.value;
        console.log('Chat mode changed to:', selectedMode);
        
        // Update the description under "Select or create a conversation"
        this.updateCurrentBotDisplay();
    }
    
    updateSelectedBot() {
        // Update current bot name display
        const selectedBot = this.globalBotSelect.value;
        console.log('Bot changed to:', selectedBot);
        
        // Update the description under "Select or create a conversation"
        this.updateCurrentBotDisplay();
    }
    
    updateCurrentBotDisplay() {
        if (!this.currentConversationId) {
            const selectedBot = this.globalBotSelect.value;
            const selectedMode = this.globalChatMode.value;
            const descriptions = {
                'chatbot': 'Single AI assistant',
                'group': 'Multiple AI assistants',
                'debate': 'Two AIs debate a topic'
            };
            const description = descriptions[selectedMode] || 'Unknown mode';
            this.currentBotName.textContent = `Bot: ${selectedBot} | Mode: ${this.globalChatMode.options[this.globalChatMode.selectedIndex].text} (${description})`;
        }
    }
    
    showNewChatModal() {
        // Pre-fill modal with current global selections
        const chatModeSelect = document.getElementById('chat-mode');
        const chatBotSelect = document.getElementById('chat-bot');
        
        if (chatModeSelect && this.globalChatMode) {
            chatModeSelect.value = this.globalChatMode.value;
        }
        
        if (chatBotSelect && this.globalBotSelect) {
            chatBotSelect.value = this.globalBotSelect.value;
        }
        
        this.newChatModal.style.display = 'block';
    }
    
    autoResizeTextarea() {
        this.messageInput.style.height = 'auto';
        this.messageInput.style.height = Math.min(this.messageInput.scrollHeight, 120) + 'px';
    }
    
    scrollToBottom(containerId = null) {
        const container = containerId ? document.getElementById(containerId) : this.messagesContainer;
        if (container) {
            container.scrollTo({
                top: container.scrollHeight,
                behavior: 'smooth'
            });
        }
    }
    
    scrollToTop(containerId) {
        const container = document.getElementById(containerId);
        if (container) {
            container.scrollTop = 0;
        }
    }
    
    scrollChatToTop() {
        if (this.messagesContainer) {
            this.messagesContainer.scrollTo({
                top: 0,
                behavior: 'smooth'
            });
        }
    }
    
        escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    isThinkingMessage(content) {
        // Detect thinking/generating messages
        const thinkingPattern = /^(Thinking|Generating)\.+(\s*\(\d+s elapsed\))?$/;
        const trimmedContent = content.trim();
        return thinkingPattern.test(trimmedContent);
    }
    
    shouldFilterContent(content) {
        // This function is now mainly used for legacy compatibility
        // The new logic handles thinking messages in handleWebSocketMessage
        return false;
    }
    
    processContentForDisplay(content) {
        if (!content) return content;

        let processedContent = this.escapeHtml(content);

        // Convert videos first (more specific pattern)
        const videoPattern = /!\[([^\]]*)\]\(([^)]*\.(?:mp4|mov|avi|webm|mkv|flv)[^)]*)\)/gi;
        processedContent = processedContent.replace(videoPattern, (match, altText, url) => {
            const displayText = altText || 'Generated Video';
            return `<video controls style="max-width: 100%; height: auto; border-radius: 8px; margin: 8px 0; display: block;" poster="" preload="metadata"><source src="${url}" type="video/mp4">Your browser does not support the video tag. <a href="${url}" target="_blank" class="video-fallback-link" style="color: #3498db; text-decoration: none;">🎬 ${displayText} (Click to open)</a></video>`;
        });

        // Convert images (excluding videos that were already processed)
        const imagePattern = /!\[([^\]]*)\]\(([^)]+)\)/g;
        processedContent = processedContent.replace(imagePattern, (match, altText, url) => {
            const displayText = altText || 'Generated Image';
            // Skip if this looks like a video URL that should have been caught by video pattern
            if (/\.(mp4|mov|avi|webm|mkv|flv)/i.test(url)) {
                return match; // Return original text
            }
            return `<img src="${url}" alt="${displayText}" style="max-width: 100%; height: auto; border-radius: 8px; margin: 8px 0; display: block;" loading="lazy" onerror="this.style.display='none'; this.nextElementSibling.style.display='inline-block';" /><a href="${url}" target="_blank" class="image-fallback-link" style="display: none; color: #3498db; text-decoration: none;">🖼️ ${displayText} (Click to open)</a>`;
        });

        // Fold model reasoning into a collapsed <details>. This catches
        // `*Thinking...*` (or `**Thinking...**`) followed by one or more
        // blockquote lines (`> …`, which is `&gt;` after escapeHtml).
        return this._wrapThinkingBlocks(processedContent);
    }

    _wrapThinkingBlocks(html) {
        if (!html) return html;
        // The content has already been HTML-escaped, so `>` is `&gt;`.
        // Match the header + the contiguous block of `&gt;`-prefixed lines,
        // tolerating any blank lines in between.
        const pattern = /(\*+Thinking\.\.\.?\*+)[ \t]*(?:\n[ \t]*)*((?:&gt;[^\n]*(?:\n|$))+)/g;
        return html.replace(pattern, (_match, _header, blockquote) => {
            // Strip the leading `&gt; ` from each line so the folded body
            // reads as normal paragraphs.
            const stripped = blockquote
                .replace(/^&gt;[ \t]?/gm, '')
                .replace(/\n{3,}/g, '\n\n')
                .trim();
            return (
                '<details class="thinking-block">'
                + '<summary>💭 Reasoning</summary>'
                + '<div class="thinking-content">' + stripped + '</div>'
                + '</details>'
            );
        });
    }
    
    cleanupWebSocket() {
        // Clear any pending timeouts
        if (this.websocketErrorTimeout) {
            clearTimeout(this.websocketErrorTimeout);
            this.websocketErrorTimeout = null;
        }
        
        // Close WebSocket connection if it exists
        if (this.websocket) {
            this.websocket.isIntentionalClose = true;
            this.websocket.close();
            this.websocket = null;
        }
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new PyPoeApp();
    
    // Clean up WebSocket when page is unloaded
    window.addEventListener('beforeunload', () => {
        if (window.app) {
            window.app.cleanupWebSocket();
        }
    });
    
    // Handle new chat modal (keeping existing functionality)
    const newChatModal = document.getElementById('new-chat-modal');
    const newChatForm = document.getElementById('new-chat-form');
    const closeModalBtns = document.querySelectorAll('.close, #cancel-btn');
    
    closeModalBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            newChatModal.style.display = 'none';
        });
    });
    
    // Toggle the single-bot dropdown vs. the multi-bot checkbox list based
    // on the chosen chat mode. Defined here so it's reachable from both the
    // mode-change handler and the modal-open handler.
    const chatModeSelect = document.getElementById('chat-mode');
    const singleBotGroup = document.getElementById('single-bot-group');
    const multiBotGroup = document.getElementById('multi-bot-group');
    const multiBotList = document.getElementById('multi-bot-list');
    const multiBotCounter = document.getElementById('multi-bot-counter');
    const debateTopicGroup = document.getElementById('debate-topic-group');
    const debateTopicInput = document.getElementById('debate-topic');
    const debateRolesGroup = document.getElementById('debate-roles-group');
    const debateRolesContainer = document.getElementById('debate-roles');

    // Keep in sync with DEBATE_ROLE_PRESETS in src/pypoe/interfaces/web/app.py.
    const DEBATE_ROLE_OPTIONS = [
        { value: 'defend',            label: 'Defend' },
        { value: 'critique',          label: 'Critique' },
        { value: 'steelman_opposite', label: 'Steelman opposite' },
        { value: 'devils_advocate',   label: "Devil's advocate" },
        { value: 'synthesizer',       label: 'Synthesizer' },
        { value: 'custom',            label: 'Custom…' },
    ];

    const renderDebateRoles = () => {
        if (!debateRolesContainer) return;
        const mode = chatModeSelect?.value || 'chatbot';
        if (mode !== 'debate') return;

        const checked = multiBotList
            ? Array.from(multiBotList.querySelectorAll('input[type="checkbox"]:checked'))
                .map(cb => cb.value)
            : [];
        if (checked.length === 0) {
            debateRolesContainer.innerHTML = '<p class="muted">Pick participants above first.</p>';
            return;
        }
        // Preserve any role/label the user already picked when they tick or
        // untick a participant.
        const prior = {};
        debateRolesContainer.querySelectorAll('.debate-role-row').forEach(row => {
            prior[row.dataset.bot] = {
                role: row.querySelector('select')?.value,
                label: row.querySelector('input[type="text"]')?.value || '',
            };
        });
        debateRolesContainer.innerHTML = '';
        checked.forEach(bot => {
            const row = document.createElement('div');
            row.className = 'debate-role-row';
            row.dataset.bot = bot;
            const label = document.createElement('label');
            label.className = 'debate-role-bot';
            label.textContent = bot;
            const select = document.createElement('select');
            DEBATE_ROLE_OPTIONS.forEach(opt => {
                const o = document.createElement('option');
                o.value = opt.value;
                o.textContent = opt.label;
                select.appendChild(o);
            });
            select.value = prior[bot]?.role || 'defend';
            const customInput = document.createElement('input');
            customInput.type = 'text';
            customInput.placeholder = 'custom role description';
            customInput.value = prior[bot]?.label || '';
            customInput.classList.toggle('hidden', select.value !== 'custom');
            select.addEventListener('change', () => {
                customInput.classList.toggle('hidden', select.value !== 'custom');
            });
            row.appendChild(label);
            row.appendChild(select);
            row.appendChild(customInput);
            debateRolesContainer.appendChild(row);
        });
    };

    const updateMultiBotCounter = () => {
        if (!multiBotList || !multiBotCounter) return;
        const checked = multiBotList.querySelectorAll('input[type="checkbox"]:checked');
        multiBotCounter.textContent = `(${checked.length}/2 — pick exactly 2)`;
        // Cap selection at 2.
        const allBoxes = multiBotList.querySelectorAll('input[type="checkbox"]');
        const limitReached = checked.length >= 2;
        allBoxes.forEach(cb => { if (!cb.checked) cb.disabled = limitReached; });
        renderDebateRoles();
    };

    const syncModeUI = () => {
        const mode = chatModeSelect?.value || 'chatbot';
        const isMulti = mode === 'group' || mode === 'debate';
        const isDebate = mode === 'debate';
        if (singleBotGroup) singleBotGroup.classList.toggle('hidden', isMulti);
        if (multiBotGroup) multiBotGroup.classList.toggle('hidden', !isMulti);
        if (debateTopicGroup) debateTopicGroup.classList.toggle('hidden', !isDebate);
        if (debateRolesGroup) debateRolesGroup.classList.toggle('hidden', !isDebate);
        if (!isMulti && multiBotList) {
            multiBotList.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                cb.checked = false;
                cb.disabled = false;
            });
        }
        updateMultiBotCounter();
    };

    if (chatModeSelect) chatModeSelect.addEventListener('change', syncModeUI);
    if (multiBotList) multiBotList.addEventListener('change', updateMultiBotCounter);
    // Ensure the form starts in a coherent state.
    syncModeUI();

    if (newChatForm) {
        newChatForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const mode = formData.get('chat_mode') || 'chatbot';
            const isMulti = mode === 'group' || mode === 'debate';

            const data = {
                title: formData.get('title'),
                chat_mode: mode,
            };

            if (isMulti) {
                const botNames = formData.getAll('bot_names');
                if (botNames.length !== 2) {
                    alert(`${mode === 'group' ? 'Group chat' : 'Debate'} needs exactly 2 participants — currently picked ${botNames.length}.`);
                    return;
                }
                data.bot_names = botNames;
                data.bot_name = botNames[0]; // primary; required by the API schema

                if (mode === 'debate') {
                    const topic = (formData.get('debate_topic') || '').toString().trim();
                    if (!topic) {
                        alert('Debate mode needs a topic.');
                        return;
                    }
                    data.debate_topic = topic;

                    const assignments = {};
                    let assignmentError = null;
                    if (debateRolesContainer) {
                        debateRolesContainer.querySelectorAll('.debate-role-row').forEach(row => {
                            const bot = row.dataset.bot;
                            const role = row.querySelector('select')?.value || 'defend';
                            const customInput = row.querySelector('input[type="text"]');
                            const customLabel = customInput?.value?.trim() || '';
                            if (role === 'custom' && !customLabel) {
                                assignmentError = `Custom role for "${bot}" needs a description.`;
                            }
                            assignments[bot] = role === 'custom'
                                ? { role, custom_label: customLabel }
                                : { role };
                        });
                    }
                    if (assignmentError) {
                        alert(assignmentError);
                        return;
                    }
                    if (Object.keys(assignments).length !== botNames.length) {
                        alert('Every selected participant needs a role.');
                        return;
                    }
                    data.bot_assignments = assignments;
                }
            } else {
                data.bot_name = formData.get('bot_name');
            }

            try {
                const response = await fetch(PYPOE_BASE + '/api/conversation/new', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(data)
                });

                const result = await response.json();
                if (!response.ok) {
                    alert(`Could not create conversation: ${result?.detail || response.statusText}`);
                    return;
                }
                if (result.conversation_id) {
                    newChatModal.style.display = 'none';
                    newChatForm.reset();
                    syncModeUI();

                    // Add a small delay to ensure conversation is fully saved
                    await new Promise(resolve => setTimeout(resolve, 500));

                    // Reload conversations and select the new one
                    await app.loadInitialData();
                    app.selectConversation(result.conversation_id);
                }
            } catch (error) {
                console.error('Error creating conversation:', error);
            }
        });
    }
    
    // Close modals when clicking outside
    window.addEventListener('click', (e) => {
        if (e.target === newChatModal) {
            newChatModal.style.display = 'none';
        }
    });
}); 