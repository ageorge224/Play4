"""
Metadata structures and caching
Complete implementation with all necessary functionality
"""
import os
import json
import time
import sqlite3
import logging
import re
from enum import Enum
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

class MetadataSource(Enum):
    YTDLP = 1
    ACOUSTID = 2
    MUSICBRAINZ = 3
    CACHE = 4

@dataclass
class SongMetadata:
    title: str = "Unknown Title"
    artist: str = "Unknown Artist"
    album: str = "Unknown Album" 
    duration: int = 0
    genres: List[str] = field(default_factory=list)
    year: Optional[int] = None
    track_number: Optional[int] = None
    acoustid: Optional[str] = None
    musicbrainz_id: Optional[str] = None
    confidence: float = 0.0
    source: MetadataSource = MetadataSource.YTDLP
    acoustid_attempted: bool = False
    
    def format_duration(self) -> str:
        """Convert duration in seconds to MM:SS format"""
        if self.duration <= 0:
            return "Unknown"
        mins, secs = divmod(self.duration, 60)
        return f"{mins:02d}:{secs:02d}"
    
    def sanitized_filename(self) -> str:
        """Generate a safe filename from metadata"""
        def clean(text: str) -> str:
            # Remove/replace problematic characters
            text = re.sub(r'[<>:"/\\|?*]', '', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:100]  # Limit length
        
        artist = clean(self.artist)
        title = clean(self.title)
        album = clean(self.album)
        
        if self.year:
            return f"{artist} - {title} [{album}] ({self.year})"
        return f"{artist} - {title} [{album}]"
    
    def is_complete_metadata(self) -> bool:
        """Check if metadata seems complete and accurate"""
        return (self.title != "Unknown Title" and 
                self.artist != "Unknown Artist" and
                self.album != "Unknown Album" and
                self.duration > 0 and
                (self.confidence >= 0.7 or self.source == MetadataSource.ACOUSTID))
    
    def __str__(self) -> str:
        return (f"{self.artist} - {self.title} | {self.album} | "
                f"{self.format_duration()} | Confidence: {self.confidence:.1%}")

class MetadataCache:
    def __init__(self, db_path: str, max_age_days: int = 30):
        self.db_path = db_path
        self.max_age_days = max_age_days
        self.init_db()
        self.cleanup_old_entries()
    
    def init_db(self):
        """Initialize the metadata cache database with better schema"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS metadata (
                    url TEXT PRIMARY KEY,
                    title TEXT,
                    artist TEXT,
                    album TEXT,
                    duration INTEGER,
                    genres TEXT,
                    year INTEGER,
                    track_number INTEGER,
                    acoustid TEXT,
                    musicbrainz_id TEXT,
                    confidence REAL,
                    source INTEGER,
                    timestamp REAL,
                    last_accessed REAL,
                    acoustid_attempted INTEGER DEFAULT 0
                )
            ''')
            # Add new column if it doesn't exist
            try:
                conn.execute('ALTER TABLE metadata ADD COLUMN acoustid_attempted INTEGER DEFAULT 0')
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            conn.execute('CREATE INDEX IF NOT EXISTS idx_acoustid ON metadata(acoustid)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_musicbrainz ON metadata(musicbrainz_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON metadata(timestamp)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_confidence ON metadata(confidence)')
    
    def cleanup_old_entries(self):
        """Remove old cache entries"""
        cutoff = time.time() - (self.max_age_days * 24 * 3600)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('DELETE FROM metadata WHERE timestamp < ?', (cutoff,))
            if cursor.rowcount > 0:
                logger.info(f"Cleaned up {cursor.rowcount} old cache entries")
    
    def get_metadata(self, url: str) -> Optional[SongMetadata]:
        """Get cached metadata and update access time"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('SELECT * FROM metadata WHERE url = ?', (url,))
            row = cursor.fetchone()
            if row:
                # Update last accessed time
                conn.execute('UPDATE metadata SET last_accessed = ? WHERE url = ?', 
                           (time.time(), url))
                
                # Handle old schema without acoustid_attempted column
                acoustid_attempted = row[14] if len(row) > 14 else False
                
                return SongMetadata(
                    title=row[1], artist=row[2], album=row[3], duration=row[4],
                    genres=json.loads(row[5]) if row[5] else [],
                    year=row[6], track_number=row[7], acoustid=row[8],
                    musicbrainz_id=row[9], confidence=row[10],
                    source=MetadataSource(row[11]),
                    acoustid_attempted=bool(acoustid_attempted)
                )
        return None
    
    def save_metadata(self, url: str, metadata: SongMetadata):
        """Save metadata to cache"""
        current_time = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO metadata 
                (url, title, artist, album, duration, genres, year, track_number, 
                 acoustid, musicbrainz_id, confidence, source, timestamp, last_accessed, acoustid_attempted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                url, metadata.title, metadata.artist, metadata.album, metadata.duration,
                json.dumps(metadata.genres), metadata.year, metadata.track_number,
                metadata.acoustid, metadata.musicbrainz_id, metadata.confidence, 
                metadata.source.value, current_time, current_time, int(metadata.acoustid_attempted)
            ))