import aiosqlite
import asyncio
import uuid
import json
import hashlib
import aiohttp
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from urllib.parse import urlparse
import re

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
    """History manager with media support and conversation management."""

    def __init__(self, db_path: str, media_dir: Optional[str] = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Media storage directory
        if media_dir:
            self.media_dir = Path(media_dir)
        else:
            self.media_dir = self.db_path.parent / "media"
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
                        chat_mode TEXT DEFAULT 'chatbot',
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
                
                # Handle migration from basic schema to enhanced schema
                await self._migrate_basic_to_enhanced(db)
                
                await db.commit()

    async def _migrate_basic_to_enhanced(self, db):
        """Migrate existing basic database schema to enhanced schema."""
        try:
            # Check if conversations table needs migration
            cursor = await db.execute("PRAGMA table_info(conversations)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            
            # Add missing columns to conversations table
            if 'chat_mode' not in column_names:
                await db.execute("ALTER TABLE conversations ADD COLUMN chat_mode TEXT DEFAULT 'chatbot'")
                print("✅ Added chat_mode column to conversations table")
            
            if 'updated_at' not in column_names:
                await db.execute("ALTER TABLE conversations ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP")
                print("✅ Added updated_at column to conversations table")
            
            if 'topic' not in column_names:
                await db.execute("ALTER TABLE conversations ADD COLUMN topic TEXT")
                print("✅ Added topic column to conversations table")
            
            # Check if messages table needs migration
            cursor = await db.execute("PRAGMA table_info(messages)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            
            # Add missing columns to messages table
            if 'content_type' not in column_names:
                await db.execute("ALTER TABLE messages ADD COLUMN content_type TEXT DEFAULT 'text'")
                print("✅ Added content_type column to messages table")
            
            if 'media_data' not in column_names:
                await db.execute("ALTER TABLE messages ADD COLUMN media_data TEXT")
                print("✅ Added media_data column to messages table")
            
            print("🔄 Database migration to enhanced schema completed successfully")
            
        except Exception as e:
            print(f"⚠️  Database migration warning: {e}")
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

    async def create_conversation(self, title: str, bot_name: str, chat_mode: str = "chatbot", topic: str = None) -> str:
        """Creates a new conversation with enhanced metadata."""
        conversation_id = str(uuid.uuid4())
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "INSERT INTO conversations (id, title, topic, bot_name, chat_mode) VALUES (?, ?, ?, ?, ?)",
                    (conversation_id, title, topic, bot_name, chat_mode)
                )
                await db.commit()
        return conversation_id

    async def add_message(self, 
                         conversation_id: str, 
                         role: str, 
                         content: str,
                         bot_name: Optional[str] = None,
                         download_media: bool = True) -> int:
        """Adds a message with enhanced media handling."""
        
        # Detect media content
        media_info = self._detect_media_content(content, bot_name or "")
        
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                # Insert message
                cursor = await db.execute("""
                    INSERT INTO messages (conversation_id, role, content, content_type, media_data) 
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    conversation_id, 
                    role, 
                    content,
                    media_info['content_type'],
                    json.dumps(media_info) if media_info['has_media'] else None
                ))
                
                message_id = cursor.lastrowid
                
                # Download and store media files if present
                if media_info['has_media'] and download_media:
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
                                      media_context_limit: int = 5) -> List[Dict[str, Any]]:
        """Gets messages with intelligent media context handling."""
        
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                # Get conversation info
                cursor = await db.execute("""
                    SELECT bot_name FROM conversations WHERE id = ?
                """, (conversation_id,))
                conv_info = await cursor.fetchone()
                
                if not conv_info:
                    return []
                
                bot_name = conv_info[0]
                is_media_model = any(
                    any(model in bot_name for model in models) 
                    for models in self.media_models.values()
                )
                
                # Get all messages
                cursor = await db.execute("""
                    SELECT m.id, m.role, m.content, m.content_type, m.media_data, m.timestamp
                    FROM messages m
                    WHERE m.conversation_id = ?
                    ORDER BY m.timestamp ASC
                """, (conversation_id,))
                
                rows = await cursor.fetchall()
                messages = []
                
                for row in rows:
                    message_id, role, content, content_type, media_data, timestamp = row
                    
                    message = {
                        "role": role,
                        "content": content,
                        "content_type": content_type,
                        "timestamp": timestamp
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

    async def get_conversations(self) -> List[Dict[str, Any]]:
        """Gets all conversations with enhanced metadata."""
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("""
                    SELECT c.id, c.title, c.topic, c.bot_name, c.chat_mode, c.created_at, c.updated_at,
                           COUNT(m.id) as message_count,
                           SUM(CASE WHEN m.content_type IN ('media', 'mixed') THEN 1 ELSE 0 END) as media_count
                    FROM conversations c
                    LEFT JOIN messages m ON c.id = m.conversation_id
                    GROUP BY c.id, c.title, c.topic, c.bot_name, c.chat_mode, c.created_at, c.updated_at
                    ORDER BY c.updated_at DESC
                """)
                rows = await cursor.fetchall()
                return [
                    {
                        "id": row[0],
                        "title": row[1],
                        "topic": row[2],
                        "bot_name": row[3],
                        "chat_mode": row[4],
                        "created_at": row[5],
                        "updated_at": row[6],
                        "message_count": row[7],
                        "media_count": row[8],
                        "has_media": row[8] > 0
                    } for row in rows
                ]

    async def delete_conversation(self, conversation_id: str):
        """Delete a conversation and properly clean up all associated media files."""
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
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
                    print(f"🧹 Cleaned up {deleted_files} media files for conversation {conversation_id}")

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
                    print(f"🧹 Cleaned up {deleted_count} orphaned media files")

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