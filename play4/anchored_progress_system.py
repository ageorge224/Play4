"""
Anchored Progress Bar System - Fixed Version
Separates progress display from analysis output using terminal positioning
Avoids circular imports by keeping dependencies minimal
"""
import sys
import time
import threading
from typing import Optional, List
from collections import deque
from pathlib import Path
from .terminal import terminal_manager

# Inline color definitions to avoid circular imports
class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    END = "\033[0m"
    DIM = "\033[2m"

class TerminalManager:
    """Manages terminal output with dedicated progress bar area"""
    
    def __init__(self):
        self.progress_line = 0  # Line number for progress bar
        self.output_buffer = deque(maxlen=50)  # Recent analysis messages
        self.progress_text = ""
        self.lock = threading.Lock()
        self.analysis_active = False
        
        # Terminal control sequences
        self.SAVE_CURSOR = "\033[s"
        self.RESTORE_CURSOR = "\033[u"
        self.CLEAR_LINE = "\033[2K"
        self.MOVE_UP = lambda n: f"\033[{n}A"
        self.MOVE_DOWN = lambda n: f"\033[{n}B"
        self.MOVE_TO_COLUMN = lambda n: f"\033[{n}G"
        
    def initialize_progress_area(self):
        """Initialize the dedicated progress area"""
        with self.lock:
            print()  # Empty line for progress
            print()  # Empty line for status
            print(f"{Colors.CYAN}📊 Analysis Log:{Colors.END}")
            print("-" * 60)
            self.progress_line = 4  # Lines above the log area
            
    def update_progress(self, progress_text: str):
        """Update the progress bar in its dedicated area"""
        with self.lock:
            self.progress_text = progress_text
            # Save current position
            sys.stdout.write(self.SAVE_CURSOR)
            # Move to progress line
            sys.stdout.write(self.MOVE_UP(20))  # Move up enough to reach progress area
            sys.stdout.write(self.MOVE_TO_COLUMN(1))
            sys.stdout.write(self.CLEAR_LINE)
            sys.stdout.write(progress_text)
            # Restore position
            sys.stdout.write(self.RESTORE_CURSOR)
            sys.stdout.flush()
    
    def add_analysis_message(self, message: str, level: str = "info"):
        """Add analysis message to the log area"""
        with self.lock:
            timestamp = time.strftime("%H:%M:%S")
            
            # Color code by level
            if level == "success":
                colored_msg = f"{Colors.GREEN}{message}{Colors.END}"
            elif level == "warning":
                colored_msg = f"{Colors.YELLOW}{message}{Colors.END}"
            elif level == "error":
                colored_msg = f"{Colors.RED}{message}{Colors.END}"
            elif level == "info":
                colored_msg = f"{Colors.CYAN}{message}{Colors.END}"
            else:
                colored_msg = message
            
            formatted_msg = f"[{timestamp}] {colored_msg}"
            self.output_buffer.append(formatted_msg)
            
            # Print to log area (this stays in the bottom area)
            print(formatted_msg)
    
    def show_status_line(self, status_text: str):
        """Update the status line (between progress and log)"""
        with self.lock:
            # Save current position
            sys.stdout.write(self.SAVE_CURSOR)
            # Move to status line (just above log area)
            sys.stdout.write(self.MOVE_UP(22))
            sys.stdout.write(self.MOVE_TO_COLUMN(1))
            sys.stdout.write(self.CLEAR_LINE)
            sys.stdout.write(f"{Colors.BOLD}{status_text}{Colors.END}")
            # Restore position
            sys.stdout.write(self.RESTORE_CURSOR)
            sys.stdout.flush()
    
    def clear_for_user_input(self):
        """Clear space for user input/messages"""
        with self.lock:
            print()  # Add some space
    
    def compact_mode(self):
        """Switch to compact mode for user interactions"""
        with self.lock:
            # Clear screen and show minimal info
            print("\033[2J\033[H")  # Clear screen and move to top
            print(f"{Colors.HEADER}🎵 Play4.py - Compact Mode{Colors.END}")
            print("-" * 40)

# Global terminal manager instance
terminal_manager = TerminalManager()

class EnhancedPlaybackProgress:
    """Enhanced progress bar that works with the terminal manager"""
    
    def __init__(self, duration: int, title: str = ""):
        self.duration = max(duration, 1)
        self.title = title[:35]  # Shorter to fit with other info
        self.start_time = time.time()
        self.paused_time = 0
        self.last_pause = None
        self.last_update = 0

    def pause(self):
        if self.last_pause is None:
            self.last_pause = time.time()

    def resume(self):
        if self.last_pause is not None:
            self.paused_time += time.time() - self.last_pause
            self.last_pause = None

    def get_elapsed(self) -> int:
        current_time = time.time()
        if self.last_pause is not None:
            return int(self.last_pause - self.start_time - self.paused_time)
        else:
            return int(current_time - self.start_time - self.paused_time)

    def display(self):
        """Display progress using the terminal manager"""
        current_time = time.time()
        # Rate limit updates to avoid spam
        if current_time - self.last_update < 0.8:
            return
        self.last_update = current_time
        
        elapsed = self.get_elapsed()
        elapsed = max(0, min(elapsed, self.duration))

        def format_time(seconds):
            mins, secs = divmod(seconds, 60)
            return f"{mins:02d}:{secs:02d}"

        elapsed_str = format_time(elapsed)
        total_str = format_time(self.duration)
        progress = elapsed / self.duration if self.duration > 0 else 0
        bar_width = 25  # Shorter bar to fit with other info
        filled = int(bar_width * progress)
        bar = "█" * filled + "░" * (bar_width - filled)
        status = "⏸️" if self.last_pause is not None else "▶️"
        
        progress_line = f"{status} {self.title:<35} [{bar}] {elapsed_str}/{total_str} ({progress:.0%})"
        terminal_manager.update_progress(progress_line)

def estimate_duration_from_file_size(file_path: str) -> int:
    """Estimate audio duration from file size"""
    try:
        path = Path(file_path)
        if not path.exists():
            return 180  # Default fallback
        
        file_size_mb = path.stat().st_size / (1024 * 1024)
        
        # Rough estimates based on format
        if path.suffix.lower() == '.flac':
            # FLAC: roughly 25-35 MB per minute (high quality)
            estimated_minutes = file_size_mb / 30
        elif path.suffix.lower() == '.mp3':
            # MP3: roughly 1 MB per minute at 128kbps
            estimated_minutes = file_size_mb / 1.2
        elif path.suffix.lower() in ['.m4a', '.aac']:
            # AAC: roughly 1 MB per minute at similar quality
            estimated_minutes = file_size_mb / 1.1
        elif path.suffix.lower() == '.ogg':
            # OGG: roughly 1 MB per minute
            estimated_minutes = file_size_mb / 1.0
        else:
            # Generic estimate
            estimated_minutes = file_size_mb / 2
        
        # Convert to seconds and clamp to reasonable range
        estimated_seconds = int(estimated_minutes * 60)
        return max(30, min(estimated_seconds, 3600))  # Between 30s and 1 hour
        
    except Exception:
        return 180  # 3 minute fallback

class AnalysisOutputManager:
    """Manages analysis output to avoid interfering with progress"""
    
    def __init__(self):
        self.buffer = []
        self.active = False
    
    def start_analysis(self, url: str):
        """Start analysis for a URL"""
        self.active = True
        short_url = url[:50] + "..." if len(url) > 50 else url
        terminal_manager.add_analysis_message(f"🔍 Starting analysis: {short_url}", "info")
    
    def basic_metadata_success(self, metadata):
        """Report basic metadata success"""
        terminal_manager.add_analysis_message(f"📝 Basic: {metadata.artist} - {metadata.title}", "success")
    
    def acoustid_sample_download(self):
        """Report sample download"""
        terminal_manager.add_analysis_message("🎵 Downloading audio sample...", "info")
    
    def acoustid_sample_success(self, file_size: int, duration: float):
        """Report sample download success"""
        terminal_manager.add_analysis_message(f"✅ Sample: {file_size//1024}KB, {duration:.0f}s", "success")
    
    def acoustid_fingerprint_start(self):
        """Report fingerprint generation start"""
        terminal_manager.add_analysis_message("🔍 Generating fingerprint...", "info")
    
    def acoustid_fingerprint_success(self, duration: float):
        """Report fingerprint success"""
        terminal_manager.add_analysis_message(f"✅ Fingerprint: {duration:.1f}s audio", "success")
    
    def acoustid_query_start(self):
        """Report database query start"""
        terminal_manager.add_analysis_message("🌐 Querying AcoustID...", "info")
    
    def acoustid_success(self, artist: str, title: str, confidence: float):
        """Report AcoustID success"""
        terminal_manager.add_analysis_message(f"🎯 AcoustID: {artist} - {title} ({confidence:.1%})", "success")
    
    def acoustid_failure(self, reason: str):
        """Report AcoustID failure"""
        terminal_manager.add_analysis_message(f"❓ AcoustID: {reason}", "warning")
    
    def analysis_complete(self, source: str):
        """Report analysis completion"""
        terminal_manager.add_analysis_message(f"✅ Analysis complete ({source})", "success")
        self.active = False

# Global analysis output manager
analysis_output = AnalysisOutputManager()