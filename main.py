import argparse
import sys

def main():
    parser = argparse.ArgumentParser(
        description="A.P.O.L.L.O - Adaptive Personal Operator for Learning, Life & Optimization"
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Launch in interactive Command Line Interface mode (default)"
    )
    
    args = parser.parse_args()
    
    # Default to CLI mode if no other mode is specified
    try:
        from interfaces.cli.chat import start_chat
        start_chat()
    except ImportError as e:
        print(f"Error importing modules: {e}")
        print("Please verify you are running from the project root and requirements are installed.")
        sys.exit(1)

if __name__ == "__main__":
    main()
