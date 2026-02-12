import sys
from pathlib import Path
from v2.core.runtime import BillyRuntime


def _print_usage() -> None:
    print("Usage: python main.py \"<your prompt>\"")
    print("")
    print("Modes:")
    print("  /plan      Read-only mode (default). No filesystem writes.")
    print("  /engineer  Explicit engineering mode. Writes PLAN.md, ARTIFACT.md, VERIFY.md.")
    print("")
    print("Examples:")
    print("  python main.py \"/plan Outline a refactor plan for X\"")
    print("  python main.py \"/engineer Build a migration plan for X\"")


def main():
    project_root = Path(__file__).resolve().parent

    if len(sys.argv) < 2:
        _print_usage()
        sys.exit(1)

    user_input = sys.argv[1]

    # Initialize our custom runtime
    runtime = BillyRuntime(root_path=str(project_root))

    # Get the response
    response = runtime.ask(user_input)

    # Print the final output
    print("\n--- Billy's Response ---")
    print(response)


if __name__ == "__main__":
    main()
