"""
Unified Display System
Clean, anchored display with 4-line rotating analysis window
Replaces both anchored_progress_system and compact_progress_system
"""
import sys
import time
import threading
from typing import Optional
from pathlib import Path

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

class UnifiedDisplayManager:
    """Single, clean display manager with anchored sections"""
    
    def __init__(self):
        self.lock = threading.Lock()
        
        # Display content
        self.progress_text = ""
        self.song_info_text = ""
        self.status_text = ""
        self.analysis_lines = ["", "", "", ""]  # Fixed 4-line window
        
        # Terminal control
        self.SAVE_CURSOR = "\033[s"
        self.RESTORE_CURSOR = "\033[u"
        self.CLEAR_LINE = "\033[2K"
        self.MOVE_UP = lambda n: f"\033[{n}A"
        self.MOVE_TO_COLUMN = lambda n: f"\033[{n}G"
        
        # Display setup
        self.display_initialized = False
        
    def initialize_display(self):
        """Initialize the clean display layout"""
        with self.lock:
            if self.display_initialized:
                return
                
            print("\n" + "=" * 80)
            print(f"{Colors.HEADER}{Colors.BOLD}🎵 PLAY4.PY - NOW PLAYING{Colors.END}")
            print("=" * 80)
            print()  # Song info line
            print()  # Progress bar line  
            print()  # Status line
            print()  # Spacer
            print(f"{Colors.CYAN}{Colors.BOLD}📊 ANALYSIS STATUS{Colors.END}")
            print("─" * 80)
            print("")  # Analysis line 1
            print("")  # Analysis line 2
            print("")  # Analysis line 3  
            print("")  # Analysis line 4
            print("─" * 80)
            print()  # User input area
            
            self.display_initialized = True
    
    def update_song_info(self, artist: str, title: str, album: str, duration: str):
        """Update the song information display"""
        with self.lock:
            self.song_info_text = f"{Colors.CYAN}🎵 {artist} - {title}{Colors.END} | {Colors.DIM}Album: {album} | Duration: {duration}{Colors.END}"
            self._refresh_display()
    
    def update_progress(self, progress_text: str):
        """Update the progress bar"""
        with self.lock:
            self.progress_text = progress_text
            self._refresh_display()
    
    def update_status(self, status_text: str):
        """Update the status line"""
        with self.lock:
            self.status_text = status_text
            self._refresh_display()
    
    def add_analysis_message(self, message: str, level: str = "info"):
        """Add message to 4-line analysis window (rotates out old messages)"""
        with self.lock:
            timestamp = time.strftime("%H:%M:%S")
            
            # Color coding
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
            
            # Truncate long messages
            max_width = 70
            if len(message) > max_width:
                message = message[:max_width-3] + "..."
                colored_msg = colored_msg[:max_width-3] + f"...{Colors.END}"
            
            formatted_line = f"[{timestamp}] {colored_msg}"
            
            # Rotate lines (oldest drops off, newest added to bottom)
            self.analysis_lines = self.analysis_lines[1:] + [formatted_line]
            self._refresh_display()
    
    def _refresh_display(self):
        """Refresh the display in place"""
        if not self.display_initialized:
            return
            
        # Save cursor position
        sys.stdout.write(self.SAVE_CURSOR)
        
        # Move to song info area (11 lines up from current position)
        sys.stdout.write(self.MOVE_UP(11))
        sys.stdout.write(self.MOVE_TO_COLUMN(1))
        
        # Song info line
        sys.stdout.write(self.CLEAR_LINE)
        sys.stdout.write(self.song_info_text)
        sys.stdout.write("\n")
        
        # Progress bar line
        sys.stdout.write(self.CLEAR_LINE)
        sys.stdout.write(self.progress_text)
        sys.stdout.write("\n")
        
        # Status line
        sys.stdout.write(self.CLEAR_LINE)
        sys.stdout.write(self.status_text)
        sys.stdout.write("\n")
        
        # Skip spacer and header
        sys.stdout.write("\n")  # Spacer
        sys.stdout.write(self.CLEAR_LINE)
        sys.stdout.write(f"{Colors.CYAN}{Colors.BOLD}📊 ANALYSIS STATUS{Colors.END}")
        sys.stdout.write("\n")
        
        # Skip separator
        sys.stdout.write(self.CLEAR_LINE)
        sys.stdout.write("─" * 80)
        sys.stdout.write("\n")
        
        # Update analysis lines (4 lines)
        for line in self.analysis_lines:
            sys.stdout.write(self.CLEAR_LINE)
            sys.stdout.write(line)
            sys.stdout.write("\n")
        
        # Bottom separator
        sys.stdout.write(self.CLEAR_LINE)
        sys.stdout.write("─" * 80)
        sys.stdout.write("\n")
        
        # Restore cursor
        sys.stdout.write(self.RESTORE_CURSOR)
        sys.stdout.flush()
    
    def clear_for_user_input(self):
        """Prepare space for user interaction"""
        with self.lock:
            print()  # Just add a line below the display
    
    def compact_mode(self):
        """Clear screen and reinitialize"""
        with self.lock:
            print("\033[2J\033[H")  # Clear screen
            self.display_initialized = False
            self.initialize_display()

# Global display manager
display = UnifiedDisplayManager()

class CleanPlaybackProgress:
    """Clean progress bar for the unified display"""
    
    def __init__(self, duration: int, title: str = ""):
        self.duration = max(duration, 1)
        self.title = title[:45]
        self.start_time = time.time()
        self.paused_time = 0
        self.last_pause = None
        self.last_update = 0

    def pause(self):
        """Mark as paused"""
        if self.last_pause is None:
            self.last_pause = time.time()

    def resume(self):
        """Mark as resumed"""
        if self.last_pause is not None:
            self.paused_time += time.time() - self.last_pause
            self.last_pause = None

    def get_elapsed(self) -> int:
        """Get elapsed time in seconds"""
        current_time = time.time()
        if self.last_pause is not None:
            return int(self.last_pause - self.start_time - self.paused_time)
        else:
            return int(current_time - self.start_time - self.paused_time)

    def display(self):
        """Update progress display"""
        current_time = time.time()
        # Rate limit updates to once per second
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
        
        # Progress bar
        bar_width = 40
        filled = int(bar_width * progress)
        bar = "█" * filled + "░" * (bar_width - filled)
        
        # Status icon
        status = "⏸️" if self.last_pause is not None else "▶️"
        
        progress_line = f"{status} {Colors.BOLD}[{bar}] {elapsed_str}/{total_str} ({progress:.0%}){Colors.END}"
        display.update_progress(progress_line)

class CleanAnalysisOutput:
    """Clean analysis output for the 4-line window"""
    
    def start_analysis(self, url: str):
        """Start analysis notification"""
        short_url = url[:45] + "..." if len(url) > 45 else url
        display.add_analysis_message(f"🔍 Analyzing: {short_url}", "info")
    
    def basic_metadata_success(self, metadata):
        """Basic metadata retrieved"""
        display.add_analysis_message(f"📝 {metadata.artist} - {metadata.title}", "success")
    
    def acoustid_sample_download(self):
        """Sample download started"""
        display.add_analysis_message("🎵 Downloading sample...", "info")
    
    def acoustid_sample_success(self, file_size: int, duration: float):
        """Sample download completed"""
        display.add_analysis_message(f"✅ Sample: {file_size//1024}KB, {duration:.0f}s", "success")
    
    def acoustid_fingerprint_start(self):
        """Fingerprint generation started"""
        display.add_analysis_message("🔍 Generating fingerprint...", "info")
    
    def acoustid_fingerprint_success(self, duration: float):
        """Fingerprint generated"""
        display.add_analysis_message(f"✅ Fingerprint: {duration:.0f}s audio", "success")
    
    def acoustid_query_start(self):
        """Database query started"""
        display.add_analysis_message("🌐 Querying AcoustID...", "info")
    
    def acoustid_success(self, artist: str, title: str, confidence: float):
        """AcoustID match found"""
        display.add_analysis_message(f"🎯 ID: {artist} - {title} ({confidence:.0%})", "success")
    
    def acoustid_failure(self, reason: str):
        """AcoustID failed"""
        # Filter out verbose failures
        if "mismatch" in reason.lower() or "no matches" in reason.lower():
            return  # Skip these common failures
        display.add_analysis_message(f"❓ {reason[:50]}", "warning")
    
    def analysis_complete(self, source: str):
        """Analysis completed"""
        display.add_analysis_message(f"✅ Complete ({source})", "success")
    
    def add_message(self, message: str, level: str = "info"):
        """Add custom message"""
        display.add_analysis_message(message, level)

# Global analysis output
analysis = CleanAnalysisOutput()

def estimate_duration_from_file_size(file_path: str) -> int:
    """Estimate duration from file size - FIXED VERSION"""
    try:
        path = Path(file_path)
        if not path.exists():
            return 180
        
        file_size_mb = path.stat().st_size / (1024 * 1024)
        
        # More accurate estimates
        if path.suffix.lower() == '.flac':
            estimated_minutes = file_size_mb / 35  # FLAC is usually 30-40MB/min
        elif path.suffix.lower() == '.mp3':
            estimated_minutes = file_size_mb / 1.0  # MP3 ~1MB/min at 128kbps
        elif path.suffix.lower() in ['.m4a', '.aac']:
            estimated_minutes = file_size_mb / 1.2  # AAC slightly larger
        elif path.suffix.lower() == '.ogg':
            estimated_minutes = file_size_mb / 1.1
        else:
            estimated_minutes = file_size_mb / 2  # Conservative estimate
        
        estimated_seconds = int(estimated_minutes * 60)
        # Better range: 1 minute to 10 minutes for most songs
        return max(60, min(estimated_seconds, 600))
        
    except Exception as e:
        print(f"Duration estimation error for {file_path}: {e}")
        return 180