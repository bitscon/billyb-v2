import sys
    import os
    from pathlib import Path
    from core.runtime import BillyRuntime

    def main():
        # Ensure the root of the project is in the Python path
        project_root = Path(__file__).parent.resolve()
        sys.path.insert(0, str(project_root))

        if len(sys.argv) < 2:
            print("Usage: python main.py \"<your question>\"")
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