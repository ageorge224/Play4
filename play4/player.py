"""
Audio playback and progress tracking
Complete implementation with all necessary functionality
"""
import os
import time
import subprocess
from typing import Tuple

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

class PlaybackProgress:
    def __init__(self, duration: int, title: str = ""):
        self.duration = max(duration, 1)
        self.title = title[:40]
        self.start_time = time.time()
        self.paused_time = 0
        self.last_pause = None

    def pause(self):
        """Mark playback as paused"""
        if self.last_pause is None:
            self.last_pause = time.time()

    def resume(self):
        """Mark playback as resumed"""
        if self.last_pause is not None:
            self.paused_time += time.time() - self.last_pause
            self.last_pause = None

    def get_elapsed(self) -> int:
        """Get elapsed playback time in seconds"""
        current_time = time.time()
        if self.last_pause is not None:
            return int(self.last_pause - self.start_time - self.paused_time)
        else:
            return int(current_time - self.start_time - self.paused_time)

    def display(self):
        """Display the progress bar - THIS WAS THE MISSING PIECE!"""
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
        status = "⏸️ " if self.last_pause is not None else "▶️ "
        progress_line = f"\r{status}{self.title:<40} [{bar}] {elapsed_str}/{total_str} ({progress:.0%})"
        print(progress_line, end='', flush=True)

def play_song(url: str, metadata) -> Tuple[subprocess.Popen, PlaybackProgress]:
    """Play a song and return process and progress tracker"""
    print(f"{Colors.GREEN}▶️ Playing: {url[:60]}...{Colors.END}")
    print(f"{Colors.CYAN}🎵 {metadata.artist} - {metadata.title}{Colors.END}")
    print(f"{Colors.DIM}   Album: {metadata.album} | Duration: {metadata.format_duration()}{Colors.END}")
    
    # Enhanced mpv command
    mpv_cmd = [
        "mpv", "--no-video", "--quiet", "--no-terminal",
        "--profile=edifier", url
    ]
    
    process = subprocess.Popen(
        mpv_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    
    display_title = f"{metadata.artist} - {metadata.title}"
    progress = PlaybackProgress(metadata.duration, display_title)
    print(f"\n{Colors.CYAN}🎵 Now Playing:{Colors.END}")
    
    return process, progress