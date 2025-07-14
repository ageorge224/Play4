"""
Enhanced Session Manager
Robust session persistence with multiple session support
"""

import os
import json
import time
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class SessionData:
    """Session data structure"""

    session_id: str
    name: str
    created: float
    last_accessed: float
    current_index: int
    total_songs: int
    videos: List[str]
    current_url: Optional[str] = None
    play_count: int = 0
    version: str = "4.2"

    def age_hours(self) -> float:
        """Get session age in hours"""
        return (time.time() - self.created) / 3600

    def last_used_hours(self) -> float:
        """Get hours since last used"""
        return (time.time() - self.last_accessed) / 3600

    def progress_percent(self) -> float:
        """Get progress percentage"""
        if self.total_songs <= 0:
            return 0.0
        return (self.current_index / self.total_songs) * 100

    def estimated_remaining_hours(self, avg_song_minutes: float = 3.5) -> float:
        """Estimate remaining playback time"""
        remaining_songs = max(0, self.total_songs - self.current_index)
        return (remaining_songs * avg_song_minutes) / 60


class SessionManager:
    """Enhanced session management with multiple session support"""

    def __init__(self, config):
        self.config = config
        self.sessions_dir = Path(config.session_file).parent / "sessions"
        self.sessions_dir.mkdir(exist_ok=True)
        self.current_session: Optional[SessionData] = None

    def _generate_session_id(self, videos: List[str]) -> str:
        """Generate unique session ID based on playlist content"""
        # Create hash from first few URLs and timestamp
        content = "".join(videos[:10])  # First 10 URLs
        timestamp = str(int(time.time()))
        combined = f"{content}_{timestamp}"
        return hashlib.md5(combined.encode()).hexdigest()[:12]

    def _session_file_path(self, session_id: str) -> Path:
        """Get path for session file"""
        return self.sessions_dir / f"{session_id}.json"

    def create_session(
        self, videos: List[str], name: Optional[str] = None
    ) -> SessionData:
        """Create a new session"""
        session_id = self._generate_session_id(videos)

        if not name:
            name = f"Session_{datetime.now().strftime('%m%d_%H%M')}"

        session = SessionData(
            session_id=session_id,
            name=name,
            created=time.time(),
            last_accessed=time.time(),
            current_index=0,
            total_songs=len(videos),
            videos=videos,
            play_count=0,
        )

        self._save_session(session)
        self.current_session = session
        return session

    def _save_session(self, session: SessionData):
        """Save session to file"""
        try:
            session_file = self._session_file_path(session.session_id)
            with open(session_file, "w") as f:
                json.dump(asdict(session), f, indent=2)
        except Exception as e:
            print(f"Warning: Failed to save session: {e}")

    def load_session(self, session_id: str) -> Optional[SessionData]:
        """Load specific session with backward compatibility"""
        try:
            session_file = self._session_file_path(session_id)
            if not session_file.exists():
                return None

            with open(session_file, "r") as f:
                data = json.load(f)

            # Handle old session format
            if "index" in data and "current_index" not in data:
                data["current_index"] = data.pop("index")

            # Provide defaults for missing fields
            defaults = {"play_count": 0, "version": "4.2"}
            for key, default_value in defaults.items():
                if key not in data:
                    data[key] = default_value

            session = SessionData(**data)

            # Update last accessed
            session.last_accessed = time.time()
            self._save_session(session)

            self.current_session = session
            return session

        except Exception as e:
            print(f"Warning: Corrupted session file {session_id}: {e}")
        return None

    def list_sessions(self) -> List[SessionData]:
        """List all available sessions"""
        sessions = []

        for session_file in self.sessions_dir.glob("*.json"):
            try:
                with open(session_file, "r") as f:
                    data = json.load(f)
                sessions.append(SessionData(**data))
            except Exception as e:
                print(f"Warning: Corrupted session file {session_file}: {e}")
                continue

        # Sort by last accessed (most recent first)
        sessions.sort(key=lambda s: s.last_accessed, reverse=True)
        return sessions

    def cleanup_old_sessions(self, max_age_days: int = 7, keep_recent: int = 5):
        """Clean up old sessions but keep recent ones"""
        sessions = self.list_sessions()

        # Always keep the most recent sessions
        to_keep = set()
        for session in sessions[:keep_recent]:
            to_keep.add(session.session_id)

        # Remove old sessions beyond max age
        cutoff_time = time.time() - (max_age_days * 24 * 3600)
        removed_count = 0

        for session in sessions:
            if (
                session.session_id not in to_keep
                and session.last_accessed < cutoff_time
            ):
                try:
                    session_file = self._session_file_path(session.session_id)
                    session_file.unlink()
                    removed_count += 1
                except Exception:
                    continue

        if removed_count > 0:
            print(f"Cleaned up {removed_count} old sessions")

    def update_session_progress(self, current_index: int, current_url: str = None):
        """Update current session progress"""
        if self.current_session:
            self.current_session.current_index = current_index
            self.current_session.last_accessed = time.time()
            self.current_session.play_count += 1
            if current_url:
                self.current_session.current_url = current_url
            self._save_session(self.current_session)

    def get_resume_info(self) -> Tuple[List[str], int, Optional[str]]:
        """Get resume information from current session"""
        if self.current_session:
            return (
                self.current_session.videos,
                self.current_session.current_index,
                self.current_session.current_url,
            )
        return [], 0, None

    def interactive_session_select(self) -> Optional[SessionData]:
        """Interactive session selection"""
        sessions = self.list_sessions()

        if not sessions:
            print("No existing sessions found.")
            return None

        print(f"\n📋 Available Sessions:")
        print("-" * 80)

        for i, session in enumerate(sessions):
            age = session.last_used_hours()
            progress = session.progress_percent()
            remaining = session.estimated_remaining_hours()

            age_str = f"{age:.1f}h ago" if age < 24 else f"{age/24:.1f}d ago"

            print(f"{i+1:2d}. {session.name}")
            print(
                f"    📊 Progress: {progress:.1f}% ({session.current_index}/{session.total_songs} songs)"
            )
            print(f"    ⏰ Last used: {age_str} | Est. remaining: {remaining:.1f}h")
            print(f"    🆔 ID: {session.session_id}")
            print()

        print(f" 0. Create new session")
        print(f" c. Cancel (use default behavior)")

        try:
            choice = input("\nSelect session (number): ").strip().lower()

            if choice == "c":
                return None
            elif choice == "0":
                return "new"
            else:
                idx = int(choice) - 1
                if 0 <= idx < len(sessions):
                    return sessions[idx]
                else:
                    print("Invalid selection")
                    return None

        except (ValueError, KeyboardInterrupt):
            print("Invalid input")
            return None

    def get_session_summary(self) -> str:
        """Get current session summary"""
        if not self.current_session:
            return "No active session"

        s = self.current_session
        progress = s.progress_percent()
        remaining = s.estimated_remaining_hours()

        return (
            f"Session: {s.name} | "
            f"Progress: {progress:.1f}% ({s.current_index}/{s.total_songs}) | "
            f"Remaining: {remaining:.1f}h"
        )


def load_or_create_session(
    config, videos: List[str], force_new: bool = False
) -> Tuple[List[str], int, Optional[str]]:
    """Load existing session or create new one with user choice"""
    manager = SessionManager(config)

    # Clean up old sessions
    manager.cleanup_old_sessions()

    if force_new:
        # Force new session
        session = manager.create_session(videos, "Fresh_Session")
        print(f"Created new session: {session.name}")
        return session.videos, 0, None

    # Check if we should resume automatically
    if config.resume_session:
        sessions = manager.list_sessions()

        # Auto-resume most recent session if it's less than 4 hours old
        if sessions and sessions[0].last_used_hours() < 4:
            recent_session = manager.load_session(sessions[0].session_id)
            if recent_session:
                print(f"Auto-resuming recent session: {recent_session.name}")
                print(
                    f"Progress: {recent_session.progress_percent():.1f}% ({recent_session.current_index}/{recent_session.total_songs})"
                )
                return manager.get_resume_info()

        # Otherwise, offer interactive selection
        if sessions:
            print("Found existing sessions...")
            selected = manager.interactive_session_select()

            if selected == "new":
                # Create new session
                session = manager.create_session(videos)
                print(f"Created new session: {session.name}")
                return session.videos, 0, None
            elif selected:
                # Load selected session
                loaded = manager.load_session(selected.session_id)
                if loaded:
                    print(f"Resumed session: {loaded.name}")
                    return manager.get_resume_info()

    # Default: create new session
    session = manager.create_session(videos)
    print(f"Created new session: {session.name}")
    return session.videos, 0, None
