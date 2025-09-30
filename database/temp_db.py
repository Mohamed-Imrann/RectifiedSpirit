from typing import Dict, Any
import time

class TempDB:
    def __init__(self):
        self.data: Dict[str, Any] = {}
        self.expiry_times: Dict[str, float] = {}
    
    def set(self, key: str, value: Any, ttl: int = 3600):
        """Set a key with optional time-to-live in seconds"""
        self.data[key] = value
        self.expiry_times[key] = time.time() + ttl
    
    def get(self, key: str) -> Any:
        """Get a key if it exists and hasn't expired"""
        if key in self.data:
            if key not in self.expiry_times or time.time() < self.expiry_times[key]:
                return self.data[key]
            self.delete(key)
        return None
    
    def delete(self, key: str):
        """Delete a key"""
        if key in self.data:
            del self.data[key]
        if key in self.expiry_times:
            del self.expiry_times[key]

temp_db = TempDB()
