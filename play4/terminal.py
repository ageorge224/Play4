"""
Terminal handling utilities
Complete implementation with all necessary functionality
"""
import sys
import termios
import tty
import select
from contextlib import contextmanager
from typing import Optional

class TerminalHandler:
    def __init__(self):
        self.original_settings = None
        
    @contextmanager
    def raw_mode(self):
        """Context manager for raw terminal mode"""
        fd = sys.stdin.fileno()
        self.original_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd, termios.TCSANOW)
            yield
        finally:
            if self.original_settings:
                termios.tcsetattr(fd, termios.TCSADRAIN, self.original_settings)
    
    def get_keypress(self, timeout=0.5) -> Optional[str]:
        """Get a single keypress with timeout"""
        try:
            with self.raw_mode():
                fd = sys.stdin.fileno()
                rlist, _, _ = select.select([fd], [], [], timeout)
                if rlist:
                    char = sys.stdin.read(1)
                    if char == "\x1b":  # Escape sequence
                        rlist, _, _ = select.select([fd], [], [], 0.01)
                        if rlist:
                            sys.stdin.read(2)  # Read the rest
                        return None
                    return char.lower().strip()
        except Exception as e:
            # Silently handle terminal errors
            pass
        return None
    
    def clear_buffer(self):
        """Clear input buffer"""
        try:
            with self.raw_mode():
                fd = sys.stdin.fileno()
                while True:
                    rlist, _, _ = select.select([fd], [], [], 0.01)
                    if not rlist:
                        break
                    sys.stdin.read(1)
        except Exception:
            pass