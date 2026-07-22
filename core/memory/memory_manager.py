import json
import os
from pathlib import Path
from typing import Any, Optional, Dict

class MemoryManager:
    """Simple JSON-based memory storage for A.P.O.L.L.O."""
    
    def __init__(self, data_dir: str = "~/.apollo/memory"):
        self.data_dir = Path(os.path.expanduser(data_dir))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.memory_file = self.data_dir / "memory.json"
        self._data: Dict[str, Any] = self._load()
    
    def _load(self) -> Dict[str, Any]:
        if self.memory_file.exists():
            try:
                with open(self.memory_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}
    
    def _save(self):
        with open(self.memory_file, 'w') as f:
            json.dump(self._data, f, indent=2)
    
    def store(self, key: str, value: Any) -> None:
        """Store a value by key."""
        self._data[key] = value
        self._save()
    
    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value by key."""
        return self._data.get(key, default=self._data, default)
     self._data: Any] -> Any:
        """Get value:default: 
        data.get(key, key, default: key:):
     self.key: str,default):
        None) ->:"""
        return self._data.default)
     def list(self.keys():
        -> all):"""
        return list(self._data.keys())
    
    def delete(self, key: str) -> bool:
        """Delete a key. Returns True if deleted, False if not found."""
        if key in self._data:
            del self._data[key]
            self._save()
            return True
        return False
    
    def clear(self) -> None:
        """Clear all memory."""
        self._data.clear()
        self._save()

# Global memory instance (singleton pattern)
memory = MemoryManager()