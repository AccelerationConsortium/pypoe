import aiosqlite
import asyncio
import contextvars
import uuid
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from urllib.parse import urlparse
import re

# Sentinel for owner-scoped reads (CLAUDE.local.md §4.9): when a caller does
# not pass ``owner`` we operate across ALL owners — the backward-compatible
# transition behaviour until the web UI is gated (§4.8). Distinct from
# ``owner=None``, which scopes to unowned / legacy rows.
_UNSCOPED = object()

# Per-request owner for multi-user servers (the web UI, §4.8). A pure-ASGI
# middleware sets this from the ``X-Auth-User`` header injected by the ac_auth
# Caddy edge; ``_resolve_owner`` falls back to it when neither a per-call
# owner nor an instance ``default_owner`` is set. Default ``_UNSCOPED`` means
# unscoped, so the CLI, Slack, and tests are unaffected.
owner_ctx = contextvars.ContextVar("pypoe_owner", default=_UNSCOPED)

# ``aiohttp`` is only required when media auto-download is enabled. Import it
# lazily inside ``_download_media`` so chat-only deploys don't need the extra.

class MediaResponse:
    """Represents a media response from an AI model."""
    
    def __init__(self, 
                 media_type: str,  # 'image', 'video', 'audio'
                 url: Optional[str] = None,
                 local_path: Optional[str] = None,
                 metadata: Optional[Dict[str, Any]] = None):
        self.media_type = media_type
        self.url = url
        self.local_path = local_path
        self.metadata = metadata or {}
        
    def to_dict(self) -> Dict[str, Any]:
        return {
            'media_type': self.media_type,
            'url': self.url,
            'local_path': self.local_path,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MediaResponse':
        return cls(
            media_type=data['media_type'],
            url=data.get('url'),
            local_path=data.get('local_path'),
            metadata=data.get('metadata', {})
        )

class HistoryManager:
    """History manager with optional media support and conversation management."""

    def __init__(
        self,
        db_path: str,
        media_dir: Optional[str] = None,
        enable_media: bool = False,
        default_owner=_UNSCOPED,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.enable_media = enable_media

        # Owner-scoping default (CLAUDE.local.md §4.9): a single-user client
        # (CLI) binds its owner once here; a multi-user caller (Slack) leaves
        # this ``_UNSCOPED`` and passes ``owner`` per call. Per-call owner wins.
        self._default_owner = default_owner

        # Media storage directory (created lazily so chat-only deployments
        # don't litter the filesystem with an unused directory).
        if media_dir:
            self.media_dir = Path(media_dir)
        else:
            self.media_dir = self.db_path.parent / "media"
        if self.enable_media:
            self.media_dir.mkdir(parents=True, exist_ok=True)

        self._lock = asyncio.Lock()
        
        # Media model patterns (models that generate media content)
        self.media_models = {
            'image': [
                'DALL-E-3', 'FLUX.1-schnell', 'FLUX.1-dev', 
                'Stable-Diffusion-XL', 'Imagen-3', 'Imagen-3-Fast',
                'FLUX-pro-1.1-ultra', 'FLUX-pro-1.1', 'StableDiffusionXL',
                'StableDiffusion3.5-L', 'Imagen-4-Ultra-Exp', 'Imagen-4',
                'Imagen-4-Fast', 'Seedream-3.0'
            ],
            'video': [
                'Runway-Gen-3', 'Veo-2', 'Kling-Pro-v1.5',
                'Runway-Gen-4-Turbo', 'Veo-3', 'Sora', 
                'Kling-2.1-Pro', 'Kling-2.1-Master', 'Seedance-1.0-Lite'
            ]
        }

    async def initialize(self):
        """Creates the enhanced database schema with migration from basic schema."""
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                # Enhanced conversations table
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS conversations (
                        id TEXT PRIMARY KEY,
                        title TEXT,
                        topic TEXT,
                        bot_name TEXT,
                        bot_names TEXT,         -- JSON list, populated for chat_mode in ('group','debate')
                        bot_assignments TEXT,   -- JSON dict (debate only): bot_name -> {role, custom_label}
                        debate_topic TEXT,      -- shared topic pinned to every debate turn's system prompt
                        chat_mode TEXT DEFAULT 'chatbot',
                        owner TEXT,             -- authenticated principal: web X-Auth-User / CLI OS user / 'slack-*'; NULL = legacy/unowned (admin-only)
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Enhanced messages table
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        conversation_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        content_type TEXT DEFAULT 'text',  -- 'text', 'media', 'mixed'
                        media_data TEXT,  -- JSON for media metadata
                        model_name TEXT,  -- which model produced this assistant row (NULL for user / legacy)
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(conversation_id) REFERENCES conversations(id)
                    )
                """)
                
                # Media files table for tracking local files
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS media_files (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        message_id INTEGER NOT NULL,
                        file_hash TEXT UNIQUE,
                        original_url TEXT,
                        local_path TEXT,
                        media_type TEXT,
                        file_size INTEGER,
                        width INTEGER,
                        height INTEGER,
                        duration REAL,  -- for videos/audio
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(message_id) REFERENCES messages(id)
                    )
                """)

                # Per-thread Slack scoping creates many small conversations,
                # so messages.conversation_id is read on every chat turn.
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_messages_conversation_id "
                    "ON messages(conversation_id)"
                )

                # Handle migration from basic schema to enhanced schema
                await self._migrate_basic_to_enhanced(db)

                # Owner-scoped history (CLAUDE.local.md §4.9): index the owner
                # column. Created AFTER migration so the column exists whether
                # it came from CREATE TABLE (new DB) or an ALTER (existing DB).
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_conversations_owner "
                    "ON conversations(owner)"
                )
                
                await db.commit()

    async def _migrate_basic_to_enhanced(self, db):
        """Migrate existing basic database schema to enhanced schema.

        Each ALTER runs in its own try/except so that one failure (for
        example, SQLite refusing a non-constant DEFAULT) doesn't block the
        rest of the migration.
        """

        async def _column_names(table: str):
            cursor = await db.execute(f"PRAGMA table_info({table})")
            return [col[1] for col in await cursor.fetchall()]

        async def _add_column(sql: str, label: str):
            try:
                await db.execute(sql)
                print(f"{label}")
            except Exception as exc:
                print(f"Skipping {label}: {exc}")

        try:
            conv_cols = await _column_names("conversations")

            if 'chat_mode' not in conv_cols:
                await _add_column(
                    "ALTER TABLE conversations ADD COLUMN chat_mode TEXT DEFAULT 'chatbot'",
                    "Added chat_mode column to conversations table",
                )

            if 'updated_at' not in conv_cols:
                # SQLite forbids non-constant defaults on ALTER TABLE, so we
                # leave existing rows as NULL; the CURRENT_TIMESTAMP default
                # in CREATE TABLE only applies to brand-new tables anyway.
                await _add_column(
                    "ALTER TABLE conversations ADD COLUMN updated_at DATETIME",
                    "Added updated_at column to conversations table",
                )

            if 'topic' not in conv_cols:
                await _add_column(
                    "ALTER TABLE conversations ADD COLUMN topic TEXT",
                    "Added topic column to conversations table",
                )

            # Group/debate modes carry a JSON list of bot names (2-3 entries).
            # NULL for chat_mode='chatbot' rows; populated otherwise.
            if 'bot_names' not in conv_cols:
                await _add_column(
                    "ALTER TABLE conversations ADD COLUMN bot_names TEXT",
                    "Added bot_names column to conversations table",
                )

            # Debate mode pins a topic and per-bot stance assignments.
            if 'bot_assignments' not in conv_cols:
                await _add_column(
                    "ALTER TABLE conversations ADD COLUMN bot_assignments TEXT",
                    "Added bot_assignments column to conversations table",
                )

            if 'debate_topic' not in conv_cols:
                await _add_column(
                    "ALTER TABLE conversations ADD COLUMN debate_topic TEXT",
                    "Added debate_topic column to conversations table",
                )

            # Owner-scoped per-user history (CLAUDE.local.md §4.9). Existing
            # rows stay NULL → treated as admin-only.
            if 'owner' not in conv_cols:
                await _add_column(
                    "ALTER TABLE conversations ADD COLUMN owner TEXT",
                    "Added owner column to conversations table",
                )

            msg_cols = await _column_names("messages")

            if 'content_type' not in msg_cols:
                await _add_column(
                    "ALTER TABLE messages ADD COLUMN content_type TEXT DEFAULT 'text'",
                    "Added content_type column to messages table",
                )

            if 'media_data' not in msg_cols:
                await _add_column(
                    "ALTER TABLE messages ADD COLUMN media_data TEXT",
                    "Added media_data column to messages table",
                )

            # Attribute assistant rows to the specific model that produced
            # them. NULL for user messages and legacy chatbot-mode rows.
            if 'model_name' not in msg_cols:
                await _add_column(
                    "ALTER TABLE messages ADD COLUMN model_name TEXT",
                    "Added model_name column to messages table",
                )

            print("Database migration to enhanced schema completed")

        except Exception as e:
            print(f"Database migration warning: {e}")
            # Continue anyway - the tables should still work for basic functionality

    def _detect_media_content(self, content: str, bot_name: str) -> Dict[str, Any]:
        """Detect if content contains media URLs or is from a media model."""
        
        # Check if bot is a known media model
        media_type = None
        for m_type, models in self.media_models.items():
            if any(model in bot_name for model in models):
                media_type = m_type
                break
        
        # Use the same patterns as ContentProcessor for consistency
        image_pattern = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
        video_pattern = re.compile(r'!\[([^\]]*)\]\(([^)]*\.(?:mp4|mov|avi|webm|mkv|flv)[^)]*)\)', re.IGNORECASE)
        
        # Extract URLs from markdown image/video patterns
        urls = []
        
        # Find video URLs first (more specific)
        for match in video_pattern.finditer(content):
            url = match.group(2)
            urls.append(url)
        
        # Find image URLs (excluding videos already found)
        for match in image_pattern.finditer(content):
            url = match.group(2)
            # Skip if this looks like a video URL
            if any(ext in url.lower() for ext in ['.mp4', '.mov', '.avi', '.webm', '.mkv', '.flv']):
                continue
            urls.append(url)
        
        # Also look for direct URLs with extensions (fallback)
        url_pattern = r'https?://[^\s<>"\'`]*\.(?:jpg|jpeg|png|gif|webp|mp4|mov|avi|webm|pdf)'
        direct_urls = re.findall(url_pattern, content, re.IGNORECASE)
        
        # Look for Poe media patterns
        poe_media_pattern = r'https://poe\.com/[a-zA-Z0-9/\-_]*'
        poe_urls = re.findall(poe_media_pattern, content)
        
        # Combine all URLs and remove duplicates
        all_urls = list(dict.fromkeys(urls + direct_urls + poe_urls))
        
        if all_urls or media_type:
            return {
                'has_media': True,
                'media_type': media_type,
                'urls': all_urls,
                'content_type': 'media' if media_type and all_urls else 'mixed'
            }
        
        return {'has_media': False, 'content_type': 'text'}

    async def _download_media(self, url: str, media_type: str) -> Optional[Dict[str, Any]]:
        """Download media file and return metadata."""
        try:
            # Lazy import so chat-only deployments don't need aiohttp installed.
            import aiohttp

            # Ensure the target directory exists (only when we actually download).
            self.media_dir.mkdir(parents=True, exist_ok=True)

            # Create hash-based filename
            url_hash = hashlib.md5(url.encode()).hexdigest()
            parsed_url = urlparse(url)

            # Determine file extension
            path_ext = Path(parsed_url.path).suffix
            if not path_ext:
                path_ext = '.jpg' if media_type == 'image' else '.mp4'

            local_filename = f"{url_hash}{path_ext}"
            local_path = self.media_dir / local_filename

            # Skip if already downloaded
            if local_path.exists():
                return {
                    'local_path': str(local_path),
                    'file_hash': url_hash,
                    'file_size': local_path.stat().st_size
                }

            # Download file
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        content = await response.read()
                        
                        with open(local_path, 'wb') as f:
                            f.write(content)
                        
                        # Get file metadata
                        file_size = len(content)
                        
                        # Basic metadata extraction (could be enhanced)
                        metadata = {
                            'local_path': str(local_path),
                            'file_hash': url_hash,
                            'file_size': file_size,
                            'content_type': response.headers.get('content-type', ''),
                        }
                        
                        # TODO: Add image dimension detection, video duration, etc.
                        
                        return metadata
                        
        except Exception as e:
            print(f"Warning: Failed to download media from {url}: {e}")
            return None

    def _resolve_owner(self, owner):
        """Resolve the effective owner for a call.

        Precedence: an explicit per-call ``owner`` (anything other than
        ``_UNSCOPED`` — e.g. Slack) wins; then the instance ``default_owner``
        (e.g. the CLI's OS user); then the per-request ``owner_ctx`` contextvar
        (the web UI, set from ``X-Auth-User`` — §4.8). Falls back to
        ``_UNSCOPED`` (unscoped) when none apply.
        """
        if owner is not _UNSCOPED:
            return owner
        if self._default_owner is not _UNSCOPED:
            return self._default_owner
        return owner_ctx.get()

    async def _assert_owner(self, db, conversation_id: str, owner, is_admin: bool) -> None:
        """Raise ``PermissionError`` if ``owner`` is set and mismatches the row.

        Owner-scoping enforcement helper (CLAUDE.local.md §4.9). No-op when
        ``is_admin``, when ``owner`` is ``_UNSCOPED`` (pre-gating transition),
        or when the conversation does not exist (a harmless target for a
        delete / no-op mutation).
        """
        if is_admin or owner is _UNSCOPED:
            return
        cur = await db.execute(
            "SELECT owner FROM conversations WHERE id = ?", (conversation_id,)
        )
        row = await cur.fetchone()
        if row is not None and row[0] != owner:
            raise PermissionError(
                f"conversation {conversation_id!r} is not owned by {owner!r}"
            )

    async def create_conversation(
        self,
        title: str,
        bot_name: str,
        chat_mode: str = "chatbot",
        topic: str = None,
        conversation_id: Optional[str] = None,
        bot_names: Optional[List[str]] = None,
        bot_assignments: Optional[Dict[str, Dict[str, Any]]] = None,
        debate_topic: Optional[str] = None,
        owner=_UNSCOPED,
    ) -> str:
        """Creates a new conversation with enhanced metadata.

        If ``conversation_id`` is provided, that exact id is used and the
        insert is idempotent (re-creating with the same id is a no-op).
        This lets callers like the Slack bot key conversations by stable,
        externally-meaningful ids (e.g. ``slack_thread_<chan>_<ts>``)
        instead of receiving a fresh UUID each call.

        ``bot_names`` is the participant list for ``chat_mode`` in
        ``{'group','debate'}``; stored as a JSON-encoded list and ignored
        for ``'chatbot'``.

        ``bot_assignments`` and ``debate_topic`` are required for
        ``chat_mode='debate'`` and ignored otherwise; both are validated
        upstream in the API layer.

        ``owner`` stamps the authenticated principal (CLAUDE.local.md §4.9):
        web ``X-Auth-User``, the CLI OS user, or a ``slack-*`` namespace.
        ``None`` leaves the row unowned (legacy / pre-gating), which
        owner-scoped reads treat as admin-only.
        """
        conversation_id = conversation_id or str(uuid.uuid4())
        stored_owner = self._resolve_owner(owner)
        owner_value = None if stored_owner is _UNSCOPED else stored_owner
        bot_names_json = json.dumps(bot_names) if bot_names else None
        bot_assignments_json = (
            json.dumps(bot_assignments) if bot_assignments else None
        )
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "INSERT OR IGNORE INTO conversations "
                    "(id, title, topic, bot_name, bot_names, "
                    " bot_assignments, debate_topic, chat_mode, owner) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        conversation_id,
                        title,
                        topic,
                        bot_name,
                        bot_names_json,
                        bot_assignments_json,
                        debate_topic,
                        chat_mode,
                        owner_value,
                    ),
                )
                await db.commit()
        return conversation_id

    async def update_conversation_debate_metadata(
        self,
        conversation_id: str,
        *,
        debate_topic: Optional[str] = None,
        bot_assignments: Optional[Dict[str, Dict[str, Any]]] = None,
        owner=_UNSCOPED,
        is_admin: bool = False,
    ) -> None:
        """Partial update for debate-only fields. ``None`` means 'leave alone'.

        Used by the PATCH endpoint so the user can revise the pinned topic
        or rebalance role assignments mid-debate. The next turn will reflect
        whichever fields changed.
        """
        if debate_topic is None and bot_assignments is None:
            return
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                # Owner-scoping (§4.9): refuse cross-owner edits.
                await self._assert_owner(db, conversation_id, self._resolve_owner(owner), is_admin)
                if debate_topic is not None:
                    await db.execute(
                        "UPDATE conversations SET debate_topic = ?, "
                        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (debate_topic, conversation_id),
                    )
                if bot_assignments is not None:
                    await db.execute(
                        "UPDATE conversations SET bot_assignments = ?, "
                        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (json.dumps(bot_assignments), conversation_id),
                    )
                await db.commit()

    async def add_message(self,
                         conversation_id: str,
                         role: str,
                         content: str,
                         bot_name: Optional[str] = None,
                         download_media: bool = True,
                         model_name: Optional[str] = None,
                         *,
                         owner=_UNSCOPED,
                         is_admin: bool = False) -> int:
        """Adds a message, with optional media auto-download.

        Media detection and downloading are skipped when ``self.enable_media``
        is False (the default) or the caller passes ``download_media=False``.
        The raw text content is always persisted.

        ``model_name`` attributes assistant rows to the model that produced
        them (required for group/debate fan-out so the frontend can render
        the row in the correct column). NULL for user messages and for
        single-bot chatbot rows where attribution is already on the
        conversation.
        """

        # Detect media content only when the instance is configured for it.
        if self.enable_media:
            media_info = self._detect_media_content(content, bot_name or "")
        else:
            media_info = {'has_media': False, 'content_type': 'text'}

        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                # Owner-scoping (§4.9): refuse writing into another owner's convo.
                await self._assert_owner(db, conversation_id, self._resolve_owner(owner), is_admin)
                # Insert message
                cursor = await db.execute("""
                    INSERT INTO messages (conversation_id, role, content, content_type, media_data, model_name)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    conversation_id,
                    role,
                    content,
                    media_info['content_type'],
                    json.dumps(media_info) if media_info['has_media'] else None,
                    model_name,
                ))

                message_id = cursor.lastrowid

                # Download and store media files when enabled and requested.
                if self.enable_media and media_info['has_media'] and download_media:
                    for url in media_info.get('urls', []):
                        media_metadata = await self._download_media(url, media_info.get('media_type', 'image'))

                        if media_metadata:
                            await db.execute("""
                                INSERT INTO media_files
                                (message_id, file_hash, original_url, local_path, media_type, file_size)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (
                                message_id,
                                media_metadata['file_hash'],
                                url,
                                media_metadata['local_path'],
                                media_info.get('media_type', 'unknown'),
                                media_metadata['file_size']
                            ))

                await db.commit()
                return message_id

    async def get_conversation_messages(self, 
                                      conversation_id: str,
                                      include_media_metadata: bool = True,
                                      media_context_limit: int = 5,
                                      *,
                                      owner=_UNSCOPED,
                                      is_admin: bool = False) -> List[Dict[str, Any]]:
        """Gets messages with intelligent media context handling.

        Owner-scoping (CLAUDE.local.md §4.9): when ``owner`` is set and does
        not match the conversation's owner (and ``is_admin`` is False), returns
        ``[]`` — knowing a conversation id must not be enough to read another
        user's messages. Default (``owner`` unset) reads any conversation, the
        transition behaviour until the web UI is gated.
        """
        
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                # Get conversation info
                cursor = await db.execute("""
                    SELECT bot_name, owner FROM conversations WHERE id = ?
                """, (conversation_id,))
                conv_info = await cursor.fetchone()

                if not conv_info:
                    return []

                bot_name, conv_owner = conv_info

                # Owner-scoping (§4.9): deny cross-owner reads unless admin.
                owner = self._resolve_owner(owner)
                if not (is_admin or owner is _UNSCOPED or conv_owner == owner):
                    return []
                is_media_model = any(
                    any(model in bot_name for model in models) 
                    for models in self.media_models.values()
                )
                
                # Get all messages
                cursor = await db.execute("""
                    SELECT m.id, m.role, m.content, m.content_type, m.media_data, m.model_name, m.timestamp
                    FROM messages m
                    WHERE m.conversation_id = ?
                    ORDER BY m.timestamp ASC, m.id ASC
                """, (conversation_id,))

                rows = await cursor.fetchall()
                messages = []

                for row in rows:
                    message_id, role, content, content_type, media_data, model_name, timestamp = row

                    message = {
                        "role": role,
                        "content": content,
                        "content_type": content_type,
                        "model_name": model_name,
                        "timestamp": timestamp,
                    }
                    
                    # Add media metadata if requested
                    if include_media_metadata and content_type in ['media', 'mixed']:
                        if media_data:
                            message['media_info'] = json.loads(media_data)
                        
                        # Get associated media files
                        media_cursor = await db.execute("""
                            SELECT original_url, local_path, media_type, file_size, width, height, duration
                            FROM media_files
                            WHERE message_id = ?
                        """, (message_id,))
                        
                        media_files = await media_cursor.fetchall()
                        if media_files:
                            message['media_files'] = [
                                {
                                    'original_url': mf[0],
                                    'local_path': mf[1],
                                    'media_type': mf[2],
                                    'file_size': mf[3],
                                    'width': mf[4],
                                    'height': mf[5],
                                    'duration': mf[6]
                                } for mf in media_files
                            ]
                    
                    messages.append(message)
                
                # For media models, implement smart context limiting
                if is_media_model and len(messages) > media_context_limit * 2:
                    # Keep recent messages and some media context
                    recent_messages = messages[-media_context_limit:]
                    
                    # Find important media messages to preserve
                    media_messages = [
                        msg for msg in messages[:-media_context_limit] 
                        if msg.get('content_type') in ['media', 'mixed']
                    ][-media_context_limit:]
                    
                    # Combine with smart ordering
                    context_messages = media_messages + recent_messages
                    
                    # Remove duplicates while preserving order
                    seen = set()
                    filtered_messages = []
                    for msg in context_messages:
                        msg_key = (msg['role'], msg['content'][:100], msg['timestamp'])
                        if msg_key not in seen:
                            seen.add(msg_key)
                            filtered_messages.append(msg)
                    
                    return sorted(filtered_messages, key=lambda x: x['timestamp'])
                
                return messages

    async def get_conversations(self, *, owner=_UNSCOPED,
                                is_admin: bool = False) -> List[Dict[str, Any]]:
        """Gets conversations with enhanced metadata.

        Owner-scoping (CLAUDE.local.md §4.9): by default (``owner`` unset)
        returns *all* conversations — the backward-compatible transition
        behaviour until the web UI is gated (§4.8). Pass ``owner=<principal>``
        to restrict to that owner's rows; ``is_admin=True`` sees everything
        (AUTH_DESIGN Req 4). Legacy rows have ``owner IS NULL`` and are visible
        only to admins (or via an explicit ``owner=None`` query).
        """
        owner = self._resolve_owner(owner)
        where, params = "", []
        if not is_admin and owner is not _UNSCOPED:
            if owner is None:
                where = "WHERE c.owner IS NULL"
            else:
                where = "WHERE c.owner = ?"
                params.append(owner)
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(f"""
                    SELECT c.id, c.title, c.topic, c.bot_name, c.bot_names,
                           c.bot_assignments, c.debate_topic, c.chat_mode, c.owner,
                           c.created_at, c.updated_at,
                           COUNT(m.id) as message_count,
                           SUM(CASE WHEN m.content_type IN ('media', 'mixed') THEN 1 ELSE 0 END) as media_count
                    FROM conversations c
                    LEFT JOIN messages m ON c.id = m.conversation_id
                    {where}
                    GROUP BY c.id, c.title, c.topic, c.bot_name, c.bot_names,
                             c.bot_assignments, c.debate_topic, c.chat_mode, c.owner,
                             c.created_at, c.updated_at
                    ORDER BY c.updated_at DESC
                """, params)
                rows = await cursor.fetchall()

                def _parse_json(raw: Optional[str]) -> Any:
                    if not raw:
                        return None
                    try:
                        return json.loads(raw)
                    except (TypeError, ValueError):
                        return None

                def _parse_bot_names(raw: Optional[str]) -> Optional[List[str]]:
                    value = _parse_json(raw)
                    return value if isinstance(value, list) else None

                def _parse_assignments(raw: Optional[str]) -> Optional[Dict[str, Any]]:
                    value = _parse_json(raw)
                    return value if isinstance(value, dict) else None

                return [
                    {
                        "id": row[0],
                        "title": row[1],
                        "topic": row[2],
                        "bot_name": row[3],
                        "bot_names": _parse_bot_names(row[4]),
                        "bot_assignments": _parse_assignments(row[5]),
                        "debate_topic": row[6],
                        "chat_mode": row[7],
                        "owner": row[8],
                        "created_at": row[9],
                        "updated_at": row[10],
                        "message_count": row[11],
                        "media_count": row[12],
                        "has_media": (row[12] or 0) > 0,
                    } for row in rows
                ]

    async def delete_conversation(self, conversation_id: str, *,
                                  owner=_UNSCOPED, is_admin: bool = False):
        """Delete a conversation and clean up all associated media files.

        Owner-scoping (CLAUDE.local.md §4.9): if ``owner`` is set and does not
        match the conversation's owner (and not ``is_admin``), raises
        ``PermissionError`` instead of deleting. A non-existent conversation is
        a harmless no-op regardless.
        """
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                # Owner-scoping (§4.9): refuse cross-owner deletes.
                await self._assert_owner(db, conversation_id, self._resolve_owner(owner), is_admin)

                # Step 1: Find all media files associated with this conversation
                cursor = await db.execute("""
                    SELECT mf.local_path 
                    FROM media_files mf
                    JOIN messages m ON mf.message_id = m.id
                    WHERE m.conversation_id = ?
                """, (conversation_id,))
                
                media_files_to_delete = await cursor.fetchall()
                
                # Step 2: Delete media files from disk
                deleted_files = 0
                for file_path_tuple in media_files_to_delete:
                    file_path = Path(file_path_tuple[0])
                    if file_path.exists():
                        try:
                            file_path.unlink()
                            deleted_files += 1
                        except Exception as e:
                            print(f"Warning: Failed to delete media file {file_path}: {e}")
                
                # Step 3: Delete media file records (cascade from message deletion)
                await db.execute("""
                    DELETE FROM media_files 
                    WHERE message_id IN (
                        SELECT id FROM messages WHERE conversation_id = ?
                    )
                """, (conversation_id,))
                
                # Step 4: Delete messages and conversation (original logic)
                await db.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
                await db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
                
                await db.commit()
                
                # Log cleanup results
                if deleted_files > 0:
                    print(f"Cleaned up {deleted_files} media files for conversation {conversation_id}")

    async def cleanup_orphaned_media(self):
        """Remove media files that are no longer referenced."""
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                # Find orphaned media files
                cursor = await db.execute("""
                    SELECT mf.local_path 
                    FROM media_files mf
                    LEFT JOIN messages m ON mf.message_id = m.id
                    WHERE m.id IS NULL
                """)
                
                orphaned_files = await cursor.fetchall()
                
                # Delete orphaned files from disk
                deleted_count = 0
                for file_path_tuple in orphaned_files:
                    file_path = Path(file_path_tuple[0])
                    if file_path.exists():
                        try:
                            file_path.unlink()
                            deleted_count += 1
                        except Exception as e:
                            print(f"Warning: Failed to delete orphaned file {file_path}: {e}")
                
                # Remove orphaned records
                await db.execute("""
                    DELETE FROM media_files 
                    WHERE message_id NOT IN (SELECT id FROM messages)
                """)
                
                await db.commit()
                
                if deleted_count > 0:
                    print(f"Cleaned up {deleted_count} orphaned media files")

    async def get_media_stats(self) -> Dict[str, Any]:
        """Get statistics about media storage."""
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("""
                    SELECT 
                        COUNT(*) as total_files,
                        SUM(file_size) as total_size,
                        media_type,
                        COUNT(*) as type_count
                    FROM media_files
                    GROUP BY media_type
                """)
                
                stats = await cursor.fetchall()
                
                return {
                    'total_files': sum(row[0] for row in stats),
                    'total_size_bytes': sum(row[1] or 0 for row in stats),
                    'by_type': {row[2]: {'count': row[3], 'size': row[1] or 0} for row in stats}
                }

    async def close(self):
        """Clean up resources."""
        pass 