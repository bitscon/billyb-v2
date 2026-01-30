import os
    from openai import OpenAI
    from typing import List, Dict

    def get_completion(messages: List[Dict[str, str]], config: dict) -> str:
        """
        Calls an OpenAI-compatible API based on the provided configuration.
        Supports "openai", "openrouter", and "ollama" providers.
        """
        # --- Determine Provider and Credentials ---
        provider = config.get("provider", "openai") # Default to 'openai' if not specified
        service_name = provider.capitalize()

        api_key = config.get("api_key") # Explicit key in config takes highest priority
        base_url = config.get("base_url")
        model_name = config.get("model_name")

        if provider == "ollama":
            # Ollama doesn't need a key, but the client library requires a non-empty string.
            if not api_key:
                api_key = "ollama" 
            if not base_url:
                # Use the default Ollama URL if not specified
                base_url = "https://ollama.barn.workshop.home"
            service_name = "Ollama"

        elif provider == "openrouter":
            # For OpenRouter, fall back to environment variable if no key in config
            if not api_key:
                api_key = os.environ.get("OPENROUTER_API_KEY")
            service_name = "OpenRouter"

        else: # Default behavior for "openai"
            if not api_key:
                api_key = os.environ.get("OPENAI_API_KEY")
            service_name = "OpenAI"

        if not api_key:
            raise ValueError(f"API key for provider '{provider}' not found. Please set it in config.yaml or as an 
environment variable.")
        if not model_name:
            raise ValueError(f"model_name not specified in config.yaml for provider '{provider}'.")

        # --- Call the API ---
        print(f" Calling {service_name} at {base_url} with model: {model_name}...")

        try:
            client = OpenAI(base_url=base_url, api_key=api_key)

            response = client.chat.completions.create(
                model=model_name,
                messages=messages
            )

            content = response.choices[0].message.content
            print(f"✅ {service_name} response received.")
            return content

        except Exception as e:
            print(f"❌ Error calling {service_name} API: {e}")
            return f"I encountered an error trying to connect to {service_name}. Please check the server, model name, 
and network."