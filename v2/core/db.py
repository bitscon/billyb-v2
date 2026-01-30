import os
    from functools import lru_cache
    from pymongo import MongoClient

    def _env(name: str, default: str | None = None) -> str:
        val = os.getenv(name, default)
        if val is None or val == "":
            raise RuntimeError(f"Missing required env var: {name}")
        return val

    @lru_cache(maxsize=1)
    def get_mongo_client() -> MongoClient:
        uri = _env("BILLY_MONGO_URI")
        # Keep it simple: local LAN only, short timeout so failures are obvious
        return MongoClient(uri, serverSelectionTimeoutMS=2000)

    def get_db():
        client = get_mongo_client()
        db_name = _env("BILLY_MONGO_DB", "billy")
        return client[db_name]