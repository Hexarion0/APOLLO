import unittest
import tempfile
import os
from pathlib import Path
from core.memory.memory_manager import MemoryManager

class TestMemoryManager(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for memory storage
        self.temp_dir = tempfile.TemporaryDirectory()
        self.memory_dir_path = self.temp_dir.name
        self.manager = MemoryManager(data_dir=self.memory_dir_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_store_and_get(self):
        self.manager.store("username", "hexarion")
        self.assertEqual(self.manager.get("username"), "hexarion")
        
        # Default value test
        self.assertEqual(self.manager.get("nonexistent", "default_val"), "default_val")

    def test_list_keys(self):
        self.manager.store("key1", "value1")
        self.manager.store("key2", "value2")
        keys = self.manager.list_keys()
        self.assertIn("key1", keys)
        self.assertIn("key2", keys)

    def test_delete(self):
        self.manager.store("temp_key", "temp_value")
        self.assertTrue(self.manager.delete("temp_key"))
        self.assertIsNone(self.manager.get("temp_key"))
        
        # Test delete nonexistent key
        self.assertFalse(self.manager.delete("nonexistent"))

    def test_clear(self):
        self.manager.store("key1", "value1")
        self.manager.store("key2", "value2")
        self.manager.clear()
        self.assertEqual(len(self.manager.list_keys()), 0)

if __name__ == "__main__":
    unittest.main()
