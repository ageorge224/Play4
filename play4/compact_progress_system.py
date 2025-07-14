"""
Compact Progress System with 4-Line Analysis Window
Eliminates spam by updating analysis info in a fixed 4-line window
"""
import sys
import time
import threading
from typing import Optional, List
from collections import deque

# Inline color definitions
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

class CompactTerminalManager:
    """Manages compact terminal output with fixed analysis window"""
    
    def __init__(self):
        self.lock = threading.Lock()
        self.progress_text = ""
        self.status_text = ""
        self.analysis_lines = ["", "", "", ""]  # Fixed 4-line analysis window
        self.current_analysis_line = 0
        
        # Terminal control sequences
        self.SAVE_CURSOR = "\033[s"
        self.RESTORE_CURSOR = "\033[u"
        self.CLEAR_LINE = "\033[2K"
        self.MOVE_UP = lambda n: f"\033[{n}A"
        self.MOVE_TO_COLUMN = lambda n: f"\033[{n}G"
        
    def initialize_display(self):
        """Initialize the compact display layout"""
        with self.lock:
            print()  # Progress bar line
            print()  # Status line
            print(f"{Colors.CYAN}📊 Analysis Window:{Colors.END}")
            print("─" * 70)
            print("") # Analysis line 1
            print("") # Analysis line 2  
            print("") # Analysis line 3
            print("") # Analysis line 4
            print("─" * 70)
            print()  # Space for user input
    
    def update_progress(self, progress_text: str):
        """Update progress bar"""
        with self.lock:
            self.progress_text = progress_text
            self._refresh_display()
    
    def update_status(self, status_text: str):
        """Update status line"""
        with self.lock:
            self.status_text = status_text
            self._refresh_display()
    
    def add_analysis_line(self, text: str, level: str = "info"):
        """Add analysis line to the 4-line window (rotates old lines out)"""
        with self.lock:
            timestamp = time.strftime("%H:%M:%S")
            
            # Color code by level
            if level == "success":
                colored_text = f"{Colors.GREEN}{text}{Colors.END}"
            elif level == "warning":
                colored_text = f"{Colors.YELLOW}{text}{Colors.END}"
            elif level == "error":
                colored_text = f"{Colors.RED}{text}{Colors.END}"
            elif level == "info":
                colored_text = f"{Colors.CYAN}{text}{Colors.END}"
            else:
                colored_text = text
            
            # Truncate long lines
            max_width = 65
            if len(text) > max_width:
                display_text = text[:max_width-3] + "..."
                colored_text = f"{colored_text[:max_width-3]}...{Colors.END}" if colored_text.endswith(Colors.END) else f"{colored_text[:max_width-3]}..."
            
            formatted_line = f"[{timestamp}] {colored_text}"
            
            # Rotate lines (shift up, add new at bottom)
            self.analysis_lines = self.analysis_lines[1:] + [formatted_line]
            self._refresh_display()
    
    def _refresh_display(self):
        """Refresh the entire display in place"""
        # Save cursor position
        sys.stdout.write(self.SAVE_CURSOR)
        
        # Move to start of our display area (9 lines up)
        sys.stdout.write(self.MOVE_UP(9))
        sys.stdout.write(self.MOVE_TO_COLUMN(1))
        
        # Update progress line
        sys.stdout.write(self.CLEAR_LINE)
        sys.stdout.write(self.progress_text)
        sys.stdout.write("\n")
        
        # Update status line
        sys.stdout.write(self.CLEAR_LINE)
        sys.stdout.write(f"{Colors.BOLD}{self.status_text}{Colors.END}")
        sys.stdout.write("\n")
        
        # Header line
        sys.stdout.write(self.CLEAR_LINE)
        sys.stdout.write(f"{Colors.CYAN}📊 Analysis Window:{Colors.END}")
        sys.stdout.write("\n")
        
        # Separator
        sys.stdout.write(self.CLEAR_LINE)
        sys.stdout.write("─" * 70)
        sys.stdout.write("\n")
        
        # Analysis lines (4 lines)
        for line in self.analysis_lines:
            sys.stdout.write(self.CLEAR_LINE)
            sys.stdout.write(line)
            sys.stdout.write("\n")
        
        # Bottom separator
        sys.stdout.write(self.CLEAR_LINE)
        sys.stdout.write("─" * 70)
        sys.stdout.write("\n")
        
        # Restore cursor position
        sys.stdout.write(self.RESTORE_CURSOR)
        sys.stdout.flush()
    
    def clear_for_user_input(self):
        """Clear space for user interaction"""
        with self.lock:
            print()  # Just add a line
    
    def compact_mode(self):
        """Switch to compact mode"""
        with self.lock:
            print("\033[2J\033[H")  # Clear screen
            print(f"{Colors.HEADER}🎵 Play4.py - Compact Mode{Colors.END}")
            print("-" * 50)

# Global compact terminal manager
compact_terminal = CompactTerminalManager()

class CompactPlaybackProgress:
    """Compact progress bar that updates in place"""
    
    def __init__(self, duration: int, title: str = ""):
        self.duration = max(duration, 1)
        self.title = title[:40]
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
        """Display progress using compact terminal manager"""
        current_time = time.time()
        # Rate limit updates
        if current_time - self.last_update < 1.0:
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
        bar_width = 30
        filled = int(bar_width * progress)
        bar = "█" * filled + "░" * (bar_width - filled)
        status = "⏸️" if self.last_pause is not None else "▶️"
        
        progress_line = f"{status} {self.title:<40} [{bar}] {elapsed_str}/{total_str} ({progress:.0%})"
        compact_terminal.update_progress(progress_line)

class CompactAnalysisOutput:
    """Manages compact analysis output in the 4-line window"""
    
    def __init__(self):
        self.current_analysis = {}  # Track current analysis per URL
    
    def start_analysis(self, url: str):
        """Start analysis for a URL"""
        short_url = url[:40] + "..." if len(url) > 40 else url
        compact_terminal.add_analysis_line(f"🔍 Analyzing: {short_url}", "info")
        self.current_analysis[url] = "started"
    
    def basic_metadata_success(self, metadata):
        """Report basic metadata success"""
        compact_terminal.add_analysis_line(f"📝 {metadata.artist} - {metadata.title}", "success")
    
    def acoustid_sample_download(self):
        """Report sample download"""
        compact_terminal.add_analysis_line("🎵 Downloading sample...", "info")
    
    def acoustid_sample_success(self, file_size: int, duration: float):
        """Report sample success"""
        compact_terminal.add_analysis_line(f"✅ Sample: {file_size//1024}KB", "success")
    
    def acoustid_fingerprint_start(self):
        """Report fingerprint start"""
        compact_terminal.add_analysis_line("🔍 Generating fingerprint...", "info")
    
    def acoustid_fingerprint_success(self, duration: float):
        """Report fingerprint success"""
        compact_terminal.add_analysis_line(f"✅ Fingerprint: {duration:.0f}s", "success")
    
    def acoustid_query_start(self):
        """Report database query"""
        compact_terminal.add_analysis_line("🌐 Querying AcoustID...", "info")
    
    def acoustid_success(self, artist: str, title: str, confidence: float):
        """Report AcoustID success"""
        compact_terminal.add_analysis_line(f"🎯 ID: {artist} - {title} ({confidence:.0%})", "success")
    
    def acoustid_failure(self, reason: str):
        """Report AcoustID failure"""
        # Only show important failures, skip verbose ones
        if "mismatch" not in reason.lower() and "no matches" not in reason.lower():
            compact_terminal.add_analysis_line(f"❓ AcoustID: {reason[:30]}", "warning")
    
    def analysis_complete(self, source: str):
        """Report analysis completion"""
        compact_terminal.add_analysis_line(f"✅ Complete ({source})", "success")
    
    def add_message(self, message: str, level: str = "info"):
        """Add generic message"""
        compact_terminal.add_analysis_line(message, level)

# Global compact analysis output
compact_analysis = CompactAnalysisOutput()

def estimate_duration_from_file_size(file_path: str) -> int:
    """Estimate audio duration from file size"""
    try:
        from pathlib import Path
        path = Path(file_path)
        if not path.exists():
            return 180
        
        file_size_mb = path.stat().st_size / (1024 * 1024)
        
        if path.suffix.lower() == '.flac':
            estimated_minutes = file_size_mb / 30
        elif path.suffix.lower() == '.mp3':
            estimated_minutes = file_size_mb / 1.2
        elif path.suffix.lower() in ['.m4a', '.aac']:
            estimated_minutes = file_size_mb / 1.1
        elif path.suffix.lower() == '.ogg':
            estimated_minutes = file_size_mb / 1.0
        else:
            estimated_minutes = file_size_mb / 2
        
        estimated_seconds = int(estimated_minutes * 60)
        return max(30, min(estimated_seconds, 3600))
        
    except Exception:
        return 180