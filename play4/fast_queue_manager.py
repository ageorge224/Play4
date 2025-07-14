"""
Fast Queue Manager with Pre-Analysis
Handles immediate local playback + background YouTube queue building
"""
import os
import time
import random
import threading
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum

from .metadata import SongMetadata, MetadataSource, MetadataCache
from .player import Colors
from .utils import get_playlist_videos
from .enhanced_session_manager import SessionManager, SessionData
from .compact_progress_system import compact_analysis

logger = logging.getLogger(__name__)

class SourceType(Enum):
    LOCAL_FILE = "local"
    YOUTUBE_URL = "youtube"

@dataclass
class QueueItem:
    source_type: SourceType
    path_or_url: str
    metadata: Optional[SongMetadata] = None
    metadata_ready: bool = False
    acoustid_analyzed: bool = False
    analysis_in_progress: bool = False
    priority: int = 0  # Higher = more important

class FastQueueManager:
    def __init__(self, config, metadata_fetcher, executor):
        self.config = config
        self.metadata_fetcher = metadata_fetcher
        self.executor = executor
        self.cache = MetadataCache(config.cache_db)

        # Queues
        self.local_queue: List[QueueItem] = []
        self.youtube_queue: List[QueueItem] = []
        self.ready_queue: List[QueueItem] = []  # Pre-analyzed and ready to play

        # State
        self.is_loading_playlists = True
        self.is_analyzing = True
        self.local_files_exhausted = False
        self.analysis_futures: Dict[str, Any] = {}

        # Stats
        self.stats = {
            'local_files_found': 0,
            'youtube_videos_loaded': 0,
            'metadata_analyzed': 0,
            'acoustid_analyzed': 0,
            'ready_buffer_size': 0
        }

        # Threading
        self.queue_lock = threading.Lock()
        self.analysis_workers = min(3, config.max_workers)  # Dedicated analysis workers

        # Session management
        self.session_manager = SessionManager(config)
        self.current_session: Optional[SessionData] = None

    def initialize(self) -> bool:
        """Initialize fast queue system with session management"""
        print(f"{Colors.CYAN}🚀 Fast Queue: Initializing with session management...{Colors.END}")

        # 1. Scan local files first (instant)
        self._scan_local_files()

        # 2. Load or create session (this handles playlist loading)
        self._initialize_session()

        # 3. Start background metadata analysis
        self._start_metadata_analysis()

        has_local = len(self.local_queue) > 0

        if has_local:
            print(f"{Colors.GREEN}✅ Fast Queue: {len(self.local_queue)} local files ready for immediate playback{Colors.END}")
        else:
            print(f"{Colors.YELLOW}⚠️ Fast Queue: No local files found, will wait for YouTube loading{Colors.END}")

        return has_local

    def _scan_local_files(self):
        """Scan local music directories for immediate playback"""
        print(f"{Colors.CYAN}📁 Scanning local music directories...{Colors.END}")

        local_files = []
        for star_level, folder_path in self.config.music_dirs.items():
            folder = Path(folder_path)
            if folder.exists():
                for ext in ['*.flac', '*.mp3', '*.m4a', '*.ogg']:
                    files = list(folder.glob(ext))
                    local_files.extend(files)

        # Convert to queue items with priority (higher star = higher priority)
        for file_path in local_files:
            # Determine priority from folder name
            priority = 1
            for star_level, folder_path in self.config.music_dirs.items():
                if str(file_path).startswith(folder_path):
                    priority = int(star_level)
                    break

            # Try to get cached metadata quickly
            file_url = f"file://{file_path}"
            metadata = self.cache.get_metadata(file_url)
            if not metadata:
                # Create basic metadata from filename
                stem = file_path.stem
                if ' - ' in stem:
                    parts = stem.split(' - ', 1)
                    artist = parts[0].strip()
                    title = parts[1].strip()
                else:
                    artist = "Unknown Artist"
                    title = stem

                metadata = SongMetadata(
                    title=title,
                    artist=artist,
                    album=file_path.parent.name,
                    source=MetadataSource.CACHE
                )

            queue_item = QueueItem(
                source_type=SourceType.LOCAL_FILE,
                path_or_url=str(file_path),
                metadata=metadata,
                metadata_ready=True,
                priority=priority
            )
            self.local_queue.append(queue_item)

        # Sort by priority (higher stars first) then shuffle within priority groups
        self.local_queue.sort(key=lambda x: (-x.priority, random.random()))
        self.stats['local_files_found'] = len(self.local_queue)

        print(f"{Colors.GREEN}✅ Found {len(self.local_queue)} local music files{Colors.END}")
        for star in sorted(self.config.music_dirs.keys(), reverse=True):
            count = len([item for item in self.local_queue if item.priority == int(star)])
            if count > 0:
                stars = "⭐" * int(star)
                print(f"   {stars} {star}-star: {count} files")

    def _initialize_session(self):
        """Initialize session management and load playlists"""
        # Get fresh playlist data
        fresh_videos = []
        print(f"{Colors.CYAN}🔄 Fetching fresh playlist data...{Colors.END}")

        for i, playlist_url in enumerate(self.config.playlists):
            try:
                videos = get_playlist_videos(playlist_url)
                fresh_videos.extend(videos)
                print(f"{Colors.GREEN}✅ Playlist {i+1}: Fetched {len(videos)} songs{Colors.END}")
            except Exception as e:
                print(f"{Colors.RED}❌ Playlist {i+1} failed: {str(e)[:50]}...{Colors.END}")

        # Remove duplicates
        unique_videos = list(dict.fromkeys(fresh_videos))
        if len(unique_videos) != len(fresh_videos):
            print(f"{Colors.YELLOW}⚠️ Removed {len(fresh_videos) - len(unique_videos)} duplicate URLs{Colors.END}")

        # Session management decision
        sessions = self.session_manager.list_sessions()

        # Auto-resume recent session if < 4 hours old
        if sessions and sessions[0].last_used_hours() < 4:
            recent_session = self.session_manager.load_session(sessions[0].session_id)
            if recent_session:
                print(f"{Colors.GREEN}🔄 Auto-resuming: {recent_session.name}")
                print(f"   Progress: {recent_session.progress_percent():.1f}% ({recent_session.current_index}/{recent_session.total_songs})")
                self.current_session = recent_session
                self._load_session_videos(recent_session.videos, recent_session.current_index)
                return

        # Interactive session selection for older sessions
        if sessions:
            print(f"\n{Colors.CYAN}📋 Found {len(sessions)} existing sessions{Colors.END}")
            selected = self.session_manager.interactive_session_select()

            if selected == 'new':
                # Create new session
                import random
                random.shuffle(unique_videos)
                session = self.session_manager.create_session(unique_videos)
                print(f"{Colors.GREEN}✅ Created new session: {session.name}{Colors.END}")
                self.current_session = session
                self._load_session_videos(unique_videos, 0)
            elif selected:
                # Load selected session
                loaded = self.session_manager.load_session(selected.session_id)
                if loaded:
                    print(f"{Colors.GREEN}🔄 Resumed session: {loaded.name}{Colors.END}")
                    self.current_session = loaded
                    self._load_session_videos(loaded.videos, loaded.current_index)
                    return

        # Default: create new session
        import random
        random.shuffle(unique_videos)
        session = self.session_manager.create_session(unique_videos)
        print(f"{Colors.GREEN}✅ Created new session: {session.name}{Colors.END}")
        self.current_session = session
        self._load_session_videos(unique_videos, 0)

    def _start_metadata_analysis(self):
        """Start background metadata analysis"""
        def analyze_metadata():
            print(f"{Colors.CYAN}🧬 Background: Starting metadata analysis...{Colors.END}")
            while self.is_analyzing:
                # Get next item to analyze
                item_to_analyze = None
                with self.queue_lock:
                    # Prioritize YouTube items that aren't being analyzed
                    for item in self.youtube_queue:
                        if not item.metadata_ready and not item.analysis_in_progress:
                            item.analysis_in_progress = True
                            item_to_analyze = item
                            break
                if item_to_analyze:
                    self._analyze_item(item_to_analyze)
                else:
                    time.sleep(1)  # Wait for more items

                # Check if we should stop
                with self.queue_lock:
                    unanalyzed = len([item for item in self.youtube_queue
                                      if not item.metadata_ready and not item.analysis_in_progress])
                    if unanalyzed == 0 and not self.is_loading_playlists:
                        self.is_analyzing = False

        # Start analysis workers
        for i in range(self.analysis_workers):
            self.executor.submit(analyze_metadata)

    def _analyze_item(self, item: QueueItem):
        """Analyze a single queue item"""
        try:
            compact_analysis.start_analysis(item.path_or_url)
            # Get metadata (this will include AcoustID if configured)
            metadata = self.metadata_fetcher.get_metadata(item.path_or_url)
            # Show analysis results
            if metadata.source == MetadataSource.ACOUSTID:
                compact_analysis.acoustid_success(metadata.artist, metadata.title, metadata.confidence)
                item.acoustid_analyzed = True
                self.stats['acoustid_analyzed'] += 1
            elif metadata.acoustid_attempted:
                compact_analysis.acoustid_success(metadata.artist, metadata.title, metadata.confidence)
                item.acoustid_analyzed = True
            else:
                compact_analysis.acoustid_success(metadata.artist, metadata.title, metadata.confidence)

            # Update item
            with self.queue_lock:
                item.metadata = metadata
                item.metadata_ready = True
                item.analysis_in_progress = False
                # Move to ready queue if good enough
                if metadata.is_complete_metadata() or metadata.source in [MetadataSource.ACOUSTID, MetadataSource.MUSICBRAINZ]:
                    self.ready_queue.append(item)
                    self.stats['ready_buffer_size'] = len(self.ready_queue)

            self.stats['metadata_analyzed'] += 1

        except Exception as e:
            logger.error(f"Analysis failed for {item.path_or_url}: {e}")
            with self.queue_lock:
                item.analysis_in_progress = False
                # Still mark as ready with basic metadata
                if not item.metadata:
                    item.metadata = SongMetadata()
                item.metadata_ready = True

    def _load_session_videos(self, videos: List[str], start_index: int):
        """Load videos from session into YouTube queue"""
        with self.queue_lock:
            # Clear existing YouTube queue
            self.youtube_queue.clear()
            # Load from start_index onwards
            for video_url in videos[start_index:]:
                queue_item = QueueItem(
                    source_type=SourceType.YOUTUBE_URL,
                    path_or_url=video_url,
                    metadata=None,
                    metadata_ready=False,
                    priority=0
                )
                self.youtube_queue.append(queue_item)

            self.stats['youtube_videos_loaded'] = len(self.youtube_queue)
            self.is_loading_playlists = False

        print(f"{Colors.GREEN}✅ Session loaded: {len(self.youtube_queue)} songs in queue{Colors.END}")

    def get_next_song(self) -> Optional[QueueItem]:
        """Get the next song to play with smart handoff and session tracking"""
        with self.queue_lock:
            if not self.local_files_exhausted and self.local_queue:
                return self.local_queue.pop(0)
            elif self.ready_queue:
                item = self.ready_queue.pop(0)
                if self.current_session:
                    remaining_in_queue = len(self.youtube_queue) + len(self.ready_queue)
                    current_pos = self.current_session.total_songs - remaining_in_queue
                    self.session_manager.update_session_progress(current_pos, item.path_or_url)
                return item
            elif self.youtube_queue:
                for i, item in enumerate(self.youtube_queue):
                    if item.metadata_ready:
                        self.youtube_queue.pop(i)
                        if self.current_session:
                            remaining_in_queue = len(self.youtube_queue) + len(self.ready_queue)
                            current_pos = self.current_session.total_songs - remaining_in_queue
                            self.session_manager.update_session_progress(current_pos, item.path_or_url)
                        return item
                # No ready item found, take the first one anyway
                item = self.youtube_queue.pop(0)
                if self.current_session:
                    remaining_in_queue = len(self.youtube_queue) + len(self.ready_queue)
                    current_pos = self.current_session.total_songs - remaining_in_queue
                    self.session_manager.update_session_progress(current_pos, item.path_or_url)
                return item
            else:
                return None

    def get_stats(self) -> Dict[str, Any]:
        """Get current queue statistics"""
        with self.queue_lock:
            ready_buffer_size = len(self.ready_queue)
            local_remaining = len(self.local_queue)
            youtube_remaining = len(self.youtube_queue)
            analyzing = len([item for item in self.youtube_queue if item.analysis_in_progress])

        return {
            **self.stats,
            'ready_buffer_size': ready_buffer_size,
            'local_remaining': local_remaining,
            'youtube_remaining': youtube_remaining,
            'currently_analyzing': analyzing,
            'is_loading_playlists': self.is_loading_playlists,
            'is_analyzing': self.is_analyzing,
            'local_exhausted': self.local_files_exhausted
        }

    def show_status(self):
        """Show detailed queue status"""
        stats = self.get_stats()

        print(f"\n{Colors.CYAN}📊 Fast Queue Status:{Colors.END}")
        print(f"  {Colors.BOLD}Local Files:{Colors.END} {stats['local_remaining']} remaining (of {stats['local_files_found']} found)")
        print(f"  {Colors.BOLD}YouTube Queue:{Colors.END} {stats['youtube_remaining']} total, {stats['ready_buffer_size']} pre-analyzed")
        print(f"  {Colors.BOLD}Analysis Progress:{Colors.END} {stats['metadata_analyzed']} analyzed, {stats['currently_analyandzing']} in progress")
        print(f"  {Colors.BOLD}AcoustID Success:{Colors.END} {stats['acoustid_analyzed']} songs identified")

        if stats['local_exhausted']:
            print(f"  {Colors.GREEN}🔄 Status: Playing from pre-analyzed YouTube queue{Colors.END}")
        elif stats['local_remaining'] > 0:
            print(f"  {Colors.BLUE}🎵 Status: Playing local files while analyzing YouTube queue{Colors.END}")
        else:
            print(f"  {Colors.YELLOW}⏳ Status: Waiting for analysis to complete{Colors.END}")

        # Buffer health
        if stats['ready_buffer_size'] >= 5:
            print(f"  {Colors.GREEN}💚 Buffer Health: Excellent ({stats['ready_buffer_size']} songs ready){Colors.END}")
        elif stats['ready_buffer_size'] >= 2:
            print(f"  {Colors.YELLOW}💛 Buffer Health: Good ({stats['ready_buffer_size']} songs ready){Colors.END}")
        else:
            print(f"  {Colors.RED}❤️ Buffer Health: Low ({stats['ready_buffer_size']} songs ready){Colors.END}")

    def cleanup(self):
        """Cleanup resources"""
        self.is_analyzing = False
        # Cancel running analysis
        for future in self.analysis_futures.values():
            if not future.done():
                future.cancel()