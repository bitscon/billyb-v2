import sys
from .commands import handle_command

if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = " ".join(sys.argv[1:])
        handle_command(command)
