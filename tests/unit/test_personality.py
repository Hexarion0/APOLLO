import unittest
from pathlib import Path
import tempfile
import os
from core.personality.personality_manager import PersonalityManager

class TestPersonalityManager(unittest.TestCase):
    def setUp(self):
        # Create a temporary personality.md file
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_file_path = Path(self.temp_dir.name) / "personality.md"
        
        self.sample_content = """# Test Identity

Name:
TestBot

Meaning:
Test Bot for Unit Testing

Purpose:
Help run test cases.

Personality:
- Smart
- Fast

Principles:
- Be accurate
- Stay responsive
"""
        with open(self.temp_file_path, "w", encoding="utf-8") as f:
            f.write(self.sample_content)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_load_personality(self):
        pm = PersonalityManager(self.temp_file_path)
        self.assertEqual(pm.name, "TestBot")
        self.assertEqual(pm.meaning, "Test Bot for Unit Testing")
        self.assertEqual(pm.purpose, "Help run test cases.")
        self.assertEqual(pm.personality_traits, ["Smart", "Fast"])
        self.assertEqual(pm.principles, ["Be accurate", "Stay responsive"])

    def test_system_prompt_generation(self):
        pm = PersonalityManager(self.temp_file_path)
        prompt = pm.get_system_prompt()
        self.assertIn("You are TestBot (Test Bot for Unit Testing)", prompt)
        self.assertIn("Your purpose: Help run test cases.", prompt)
        self.assertIn("Your personality: Smart, Fast", prompt)
        self.assertIn("- Be accurate", prompt)
        self.assertIn("- Stay responsive", prompt)

if __name__ == "__main__":
    unittest.main()
