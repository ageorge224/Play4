#!/usr/bin/env python3
"""
Play4.py - Enhanced Music Player & Downloader
Modular version with fixed progress bar and improved performance
"""

if __name__ == "__main__":
    try:
        from play4.main import main
        exit(main())
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("")
        print("🔧 Make sure you have the correct directory structure:")
        print("  Play4/")
        print("  ├── play4.py          # this file")
        print("  └── play4/            # package directory")
        print("      ├── __init__.py")
        print("      ├── main.py")
        print("      └── ... (other modules)")
        print("")
        import os
        print("📁 Current directory contents:")
        for item in sorted(os.listdir('.')):
            if os.path.isdir(item):
                print(f"  📁 {item}/")
            else:
                print(f"  📄 {item}")
        exit(1)
    except Exception as e:
        print(f"❌ Error starting Play4.py: {e}")
        exit(1)
EOF