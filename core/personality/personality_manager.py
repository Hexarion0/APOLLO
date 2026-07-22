import os
from pathlib import Path
from typing import List

class PersonalityManager:
    """Loads and parses A.P.O.L.L.O's personality profile from a markdown file."""
    
    def __init__(self, filepath: Path = None):
        if filepath is None:
            filepath = Path(os.path.dirname(__file__)) / "personality.md"
        self.filepath = filepath
        self.name = "A.P.O.L.L.O"
        self.meaning = ""
        self.purpose = ""
        self.personality_traits: List[str] = []
        self.principles: List[str] = []
        self.load()

    def load(self) -> None:
        """Parses the personality markdown file."""
        if not self.filepath.exists():
            return
        
        with open(self.filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        current_section = None
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            if line_str.startswith("#"):
                continue
            
            if line_str.endswith(":"):
                current_section = line_str[:-1].lower()
                continue
            
            if current_section == "name":
                self.name = line_str
            elif current_section == "meaning":
                self.meaning = line_str
            elif current_section == "purpose":
                self.purpose = line_str
            elif current_section == "personality":
                trait = line_str.lstrip("- ").strip()
                if trait:
                    self.personality_traits.append(trait)
            elif current_section == "principles":
                principle = line_str.lstrip("- ").strip()
                if principle:
                    self.principles.append(principle)

    def get_system_prompt(self) -> str:
        """Generates a system prompt based on personality definition."""
        traits_str = ", ".join(self.personality_traits)
        principles_str = "\n".join(f"- {p}" for p in self.principles)
        return (
            f"You are {self.name} ({self.meaning}).\n"
            f"Your purpose: {self.purpose}\n"
            f"Your personality: {traits_str}.\n"
            f"Your guiding principles:\n{principles_str}\n"
            f"Respond to the user in a way that matches this identity."
        )
