import os
import requests
from typing import Dict, Any, List
from dotenv import load_dotenv
from core.personality.personality_manager import PersonalityManager

# Load environment variables from .env
load_dotenv()

class Agent:
    """Agent orchestrates personality and communicates with the NVIDIA API."""
    
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.getenv("NVIDIA_API_KEY")
        self.model = model or os.getenv("NVIDIA_MODEL", "meta/llama-3.1-8b-instruct")
        self.base_url = "https://integrate.api.nvidia.com/v1/chat/completions"
        self.personality_manager = PersonalityManager()
        self.history: List[Dict[str, str]] = []
        
    def check_config(self) -> bool:
        """Returns True if the API key is set, False otherwise."""
        return bool(self.api_key)

    def clear_history(self) -> None:
        """Clears the session conversation history."""
        self.history.clear()

    def handle_message(self, user_message: str) -> str:
        """Sends user message along with current session history to NVIDIA API."""
        if not self.api_key:
            return "Error: NVIDIA_API_KEY is not set. Please add it to your .env file."
            
        system_prompt = self.personality_manager.get_system_prompt()
        
        # Build the messages payload
        messages = [{"role": "system", "content": system_prompt}]
        
        # Append session history
        for msg in self.history:
            messages.append(msg)
            
        # Append current user message
        messages.append({"role": "user", "content": user_message})
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.5,
            "max_tokens": 1024
        }
        
        try:
            response = requests.post(self.base_url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            reply = data["choices"][0]["message"]["content"]
            
            # Save to session history
            self.history.append({"role": "user", "content": user_message})
            self.history.append({"role": "assistant", "content": reply})
            
            return reply
        except requests.exceptions.RequestException as e:
            return f"Error communicating with NVIDIA API: {str(e)}"
        except (KeyError, ValueError) as e:
            return f"Error parsing response from NVIDIA API: {str(e)}"
