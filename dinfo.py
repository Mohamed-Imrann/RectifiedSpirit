# dinfo.py - Debug information
import platform
import sys
import os

def get_debug_info():
    info = {
        "Python Version": sys.version,
        "Platform": platform.platform(),
        "OS Name": os.name,
        "Current Working Directory": os.getcwd(),
        "Environment Variables": dict(os.environ) # Be careful with sensitive info
    }
    return info

if __name__ == "__main__":
    debug_info = get_debug_info()
    for key, value in debug_info.items():
        print(f"{key}: {value}")
