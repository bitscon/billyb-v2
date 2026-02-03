"""
GitHub API integration for Agent Zero approval workflow.
"""

import os
import json
import time
import urllib.request
import urllib.error
import tempfile
from typing import Dict, Any, Optional, List, Union
from datetime import datetime, timedelta
from pathlib import Path

from .schema import validate_version_format

# Custom exceptions
class GitHubAPIError(Exception):
    """Base class for GitHub API errors."""
    pass

class InvalidVersionError(GitHubAPIError):
    """Raised when a version does not exist in GitHub releases."""
    pass

class RateLimitExceededError(GitHubAPIError):
    """Raised when GitHub API rate limit is exceeded."""
    pass

class GitHubUnavailableError(GitHubAPIError):
    """Raised when GitHub API is unavailable."""
    pass

# GitHub API constants
GITHUB_API_TIMEOUT = 5  # seconds
GITHUB_RELEASES_URL = "https://api.github.com/repos/frdel/agent-zero/releases/tags/{tag}"
CACHE_TTL = 3600  # 1 hour

def get_cache_path() -> Path:
    """Returns path to the GitHub API response cache directory."""
    cache_dir = Path(__file__).parent / ".billy" / "cache"
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir

def get_cached_response(tag: str) -> Optional[Dict[str, Any]]:
    """
    Get cached GitHub API response for a release tag.
    
    Args:
        tag: Release tag
        
    Returns:
        Dict or None: Cached response or None if not found or expired
    """
    cache_path = get_cache_path() / f"release_{tag}.json"
    
    # Check if cache exists
    if not cache_path.exists():
        return None
    
    try:
        # Read cache
        with open(cache_path, "r") as f:
            cache_data = json.load(f)
        
        # Check if cache has timestamp
        if "cached_at" not in cache_data:
            return None
        
        # Check if cache is expired
        cached_at = datetime.fromisoformat(cache_data["cached_at"].replace('Z', '+00:00'))
        if datetime.utcnow() - cached_at > timedelta(seconds=CACHE_TTL):
            return None
        
        return cache_data["data"]
    
    except (json.JSONDecodeError, KeyError, ValueError):
        # Invalid cache, ignore
        return None

def cache_response(tag: str, data: Dict[str, Any]) -> None:
    """
    Cache GitHub API response.
    
    Args:
        tag: Release tag
        data: API response data
    """
    cache_path = get_cache_path()
    
    # Create cache directory if it doesn't exist
    cache_path.mkdir(parents=True, exist_ok=True)
    
    # Create cache entry
    cache_data = {
        "cached_at": datetime.utcnow().isoformat() + "Z",
        "data": data
    }
    
    # Write cache file
    tmp_file = tempfile.NamedTemporaryFile(
        dir=str(cache_path),
        prefix=f"release_{tag}.",
        suffix=".json.tmp",
        delete=False,
        mode="w"
    )
    
    try:
        json.dump(cache_data, tmp_file, indent=2)
        tmp_file.close()
        
        # Atomic rename
        os.rename(tmp_file.name, str(cache_path / f"release_{tag}.json"))
    except Exception:
        # Clean up tmp file in case of error
        if os.path.exists(tmp_file.name):
            os.unlink(tmp_file.name)
        raise

def get_github_release(tag: str, allow_prerelease: bool = False, force_check: bool = False) -> Dict[str, Any]:
    """
    Get GitHub release information for a tag.
    
    Args:
        tag: Release tag (e.g., "v0.9.8")
        allow_prerelease: Whether to allow prerelease versions
        force_check: Whether to bypass cache
        
    Returns:
        Dict: Release information
        
    Raises:
        InvalidVersionError: If the tag does not exist
        RateLimitExceededError: If GitHub API rate limit is exceeded
        GitHubUnavailableError: If GitHub API is unavailable
    """
    # Validate version format
    validate_version_format(tag)
    
    # Check cache unless force_check is True
    if not force_check:
        cached = get_cached_response(tag)
        if cached:
            return cached
    
    # Build URL
    url = GITHUB_RELEASES_URL.format(tag=tag)
    
    try:
        # Create request with appropriate headers
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Agent-Zero-Approval-Workflow/1.0"
        }
        
        req = urllib.request.Request(url, headers=headers)
        
        # Make request with timeout
        with urllib.request.urlopen(req, timeout=GITHUB_API_TIMEOUT) as response:
            # Parse JSON response
            data = json.loads(response.read().decode('utf-8'))
            
            # Check if this is a draft release
            if data.get("draft", False):
                raise InvalidVersionError(f"Release {tag} is a draft and cannot be used")
            
            # Check if this is a prerelease
            if data.get("prerelease", False) and not allow_prerelease:
                raise InvalidVersionError(f"Release {tag} is a prerelease. Use --allow-prerelease flag to enable")
            
            # Cache the response
            cache_response(tag, data)
            
            return data
    
    except urllib.error.HTTPError as e:
        # Handle HTTP errors
        if e.code == 404:
            raise InvalidVersionError(f"Version {tag} not found in GitHub releases")
        elif e.code == 429:
            retry_after = e.headers.get("Retry-After", "60")
            raise RateLimitExceededError(f"GitHub API rate limit exceeded. Retry after {retry_after} seconds")
        elif e.code in (500, 502, 503):
            raise GitHubUnavailableError(f"GitHub API is currently unavailable (HTTP {e.code})")
        else:
            raise GitHubAPIError(f"GitHub API error: {e.code} - {e.reason}")
    
    except urllib.error.URLError as e:
        raise GitHubUnavailableError(f"Failed to connect to GitHub: {str(e)}")
    
    except json.JSONDecodeError:
        raise GitHubAPIError("Invalid JSON response from GitHub API")
    
    except Exception as e:
        raise GitHubAPIError(f"Unexpected error: {str(e)}")

def check_release_assets(release_data: Dict[str, Any]) -> bool:
    """
    Check if a release has assets.
    
    Args:
        release_data: Release data from GitHub API
        
    Returns:
        bool: True if assets exist
    """
    assets = release_data.get("assets", [])
    return len(assets) > 0