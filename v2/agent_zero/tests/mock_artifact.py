"""
Mock artifact generator for testing validation.

This module creates fake staged artifacts for testing the validation engine
without requiring a full staging process.
"""

import os
import json
import tempfile
import shutil
from pathlib import Path
from typing import Optional


def create_mock_artifact(
    version: str = "v0.9.8",
    include_venv: bool = True,
    include_all_files: bool = True,
    custom_path: Optional[Path] = None
) -> Path:
    """
    Create a mock Agent Zero artifact for testing.
    
    Args:
        version: Version string
        include_venv: Whether to include a mock virtualenv
        include_all_files: Whether to include all critical files
        custom_path: Custom path for artifact (default: temp directory)
        
    Returns:
        Path: Path to created mock artifact
    """
    # Create artifact directory
    if custom_path:
        artifact_path = custom_path
        os.makedirs(artifact_path, exist_ok=True)
    else:
        artifact_path = Path(tempfile.mkdtemp(prefix="mock_artifact_"))
    
    # Create critical files
    if include_all_files:
        # Create agent.py
        with open(artifact_path / "agent.py", "w") as f:
            f.write('"""Mock agent.py"""\n')
        
        # Create models.py
        with open(artifact_path / "models.py", "w") as f:
            f.write('"""Mock models.py"""\n')
        
        # Create requirements.txt
        with open(artifact_path / "requirements.txt", "w") as f:
            f.write("# Mock requirements\n")
        
        # Create prompts directory
        prompts_dir = artifact_path / "prompts"
        os.makedirs(prompts_dir, exist_ok=True)
        
        with open(prompts_dir / "agent.system.main.md", "w") as f:
            f.write("# Mock prompt\n")
        
        # Create python directory with tools
        python_dir = artifact_path / "python"
        os.makedirs(python_dir, exist_ok=True)
        
        tools_dir = python_dir / "tools"
        os.makedirs(tools_dir, exist_ok=True)
        
        with open(tools_dir / "response.py", "w") as f:
            f.write('"""Mock tool"""\n')
        
        # Create __init__.py files
        with open(python_dir / "__init__.py", "w") as f:
            f.write("")
    
    # Create mock virtualenv
    if include_venv:
        venv_dir = artifact_path / ".venv"
        bin_dir = venv_dir / "bin"
        os.makedirs(bin_dir, exist_ok=True)
        
        # Create mock python executable
        python_path = bin_dir / "python"
        with open(python_path, "w") as f:
            f.write("#!/bin/bash\n")
            f.write("# Mock python executable\n")
            f.write("exec /usr/bin/python3 \"$@\"\n")
        
        os.chmod(python_path, 0o755)
    
    # Create manifest.json
    manifest = {
        "version": version,
        "built_at": "2026-02-01T00:00:00Z",
        "source_url": "https://github.com/frdel/agent-zero.git",
        "commit_sha": "0" * 40,
        "checksums": {
            "algorithm": "sha256",
            "files": {},
            "tree_hash": "0" * 64
        },
        "build_id": "mock-build-id",
        "build_log_path": None,
        "virtualenv_hash": None
    }
    
    with open(artifact_path / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    
    return artifact_path


def create_broken_artifact(version: str = "v0.9.8", break_type: str = "missing_files") -> Path:
    """
    Create a broken artifact for testing failure cases.
    
    Args:
        version: Version string
        break_type: Type of breakage:
            - "missing_files": Missing critical files
            - "no_venv": Missing virtualenv
            - "empty_prompts": Empty prompt files
            - "no_tools": Missing tools directory
            
    Returns:
        Path: Path to broken artifact
    """
    artifact_path = Path(tempfile.mkdtemp(prefix="broken_artifact_"))
    
    if break_type == "missing_files":
        # Create minimal structure with missing files
        with open(artifact_path / "agent.py", "w") as f:
            f.write('"""Mock agent.py"""\n')
        # Missing models.py and other critical files
    
    elif break_type == "no_venv":
        # Create all files but no virtualenv
        return create_mock_artifact(version, include_venv=False, custom_path=artifact_path)
    
    elif break_type == "empty_prompts":
        # Create structure but with empty prompt files
        artifact = create_mock_artifact(version, custom_path=artifact_path)
        
        prompts_dir = artifact_path / "prompts"
        for prompt_file in prompts_dir.glob("*.md"):
            with open(prompt_file, "w") as f:
                f.write("")  # Empty file
    
    elif break_type == "no_tools":
        # Create structure but remove tools directory
        artifact = create_mock_artifact(version, custom_path=artifact_path)
        
        tools_dir = artifact_path / "python" / "tools"
        if tools_dir.exists():
            shutil.rmtree(tools_dir)
    
    else:
        raise ValueError(f"Unknown break_type: {break_type}")
    
    # Create basic manifest
    manifest = {
        "version": version,
        "built_at": "2026-02-01T00:00:00Z",
        "source_url": "https://github.com/frdel/agent-zero.git",
        "commit_sha": "0" * 40,
        "checksums": {
            "algorithm": "sha256",
            "files": {},
            "tree_hash": "0" * 64
        },
        "build_id": "broken-build-id",
        "build_log_path": None,
        "virtualenv_hash": None
    }
    
    with open(artifact_path / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    
    return artifact_path