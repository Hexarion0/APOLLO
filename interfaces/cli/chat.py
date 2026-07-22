import sys
import os
from dotenv import load_dotenv
from core.brain.agent import Agent

# Load environment variables
load_dotenv()

# ANSI Style Codes for Premium UI
COLOR_BLUE = "\033[94m"
COLOR_CYAN = "\033[96m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED = "\033[91m"
STYLE_BOLD = "\033[1m"
STYLE_RESET = "\033[0m"

def print_banner(agent: Agent):
    """Prints a beautiful terminal banner for A.P.O.L.L.O."""
    banner = f"""
{COLOR_CYAN}{STYLE_BOLD}===================================================================
      🚀 A.P.O.L.L.O v0.1 Genesis (NVIDIA NIM Integration)
      {agent.personality_manager.meaning}
==================================================================={STYLE_RESET}
{COLOR_BLUE}Personality Profile Loaded:{STYLE_RESET} {agent.personality_manager.name}
{COLOR_BLUE}NVIDIA Model:{STYLE_RESET} {agent.model}

Type {COLOR_GREEN}/help{STYLE_RESET} to view commands. Type {COLOR_GREEN}/exit{STYLE_RESET} or press {COLOR_GREEN}Ctrl+C{STYLE_RESET} to quit.
"""
    print(banner)

def print_help():
    """Prints a list of available commands."""
    help_text = f"""
{STYLE_BOLD}Available Commands:{STYLE_RESET}
  {COLOR_GREEN}/help{STYLE_RESET}         - Show this help message.
  {COLOR_GREEN}/clear{STYLE_RESET}        - Clear the current session conversation history.
  {COLOR_GREEN}/personality{STYLE_RESET}  - Show the current system prompt and personality configuration.
  {COLOR_GREEN}/exit{STYLE_RESET} or {COLOR_GREEN}/quit{STYLE_RESET} - Exit the application.
"""
    print(help_text)

def print_personality(agent: Agent):
    """Prints the details of Apollo's current personality configuration."""
    pm = agent.personality_manager
    traits = ", ".join(pm.personality_traits)
    principles = "\n  ".join(f"- {p}" for p in pm.principles)
    
    profile = f"""
{COLOR_CYAN}{STYLE_BOLD}--- Personality Profile ---{STYLE_RESET}
{STYLE_BOLD}Name:{STYLE_RESET} {pm.name}
{STYLE_BOLD}Meaning:{STYLE_RESET} {pm.meaning}
{STYLE_BOLD}Purpose:{STYLE_RESET} {pm.purpose}
{STYLE_BOLD}Traits:{STYLE_RESET} {traits}
{STYLE_BOLD}Principles:{STYLE_RESET} 
  {principles}
"""
    print(profile)

def start_chat():
    """Main CLI chat loop."""
    # Ensure stdout/stdin handles terminal colors correctly
    if os.name == 'nt':
        os.system('color')
        
    agent = Agent()
    
    if not agent.check_config():
        print(f"{COLOR_RED}{STYLE_BOLD}Error: NVIDIA_API_KEY is not configured.{STYLE_RESET}")
        print(f"Please add {COLOR_YELLOW}NVIDIA_API_KEY=your_key_here{STYLE_RESET} to your {COLOR_YELLOW}.env{STYLE_RESET} file.")
        print("You can obtain a key from NVIDIA NIM.")
        sys.exit(1)
        
    print_banner(agent)
    
    while True:
        try:
            # Get user input
            user_input = input(f"\n{COLOR_GREEN}{STYLE_BOLD}You > {STYLE_RESET}").strip()
            
            if not user_input:
                continue
                
            # Handle Commands
            if user_input.startswith("/"):
                command = user_input.lower()
                if command in ["/exit", "/quit"]:
                    print(f"\n{COLOR_CYAN}Goodbye!{STYLE_RESET}")
                    break
                elif command == "/help":
                    print_help()
                elif command == "/clear":
                    agent.clear_history()
                    print(f"\n{COLOR_YELLOW}Conversation history cleared.{STYLE_RESET}")
                elif command == "/personality":
                    print_personality(agent)
                else:
                    print(f"\n{COLOR_RED}Unknown command: {user_input}. Type /help for assistance.{STYLE_RESET}")
                continue
                
            # Handle standard messages
            print(f"{COLOR_BLUE}{STYLE_BOLD}{agent.personality_manager.name} > {STYLE_RESET}", end="", flush=True)
            
            # Request response from Agent
            response = agent.handle_message(user_input)
            print(response)
            
        except KeyboardInterrupt:
            print(f"\n\n{COLOR_CYAN}Session interrupted. Goodbye!{STYLE_RESET}")
            break
        except Exception as e:
            print(f"\n{COLOR_RED}An error occurred: {str(e)}{STYLE_RESET}")
            break

if __name__ == "__main__":
    start_chat()
