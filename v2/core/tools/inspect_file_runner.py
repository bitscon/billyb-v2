from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Any, Dict, Tuple


MAX_EXCERPT_BYTES = 65536
DEFAULT_EXCERPT_BYTES = 4096
MAX_HASH_FILE_BYTES = 16 * 1024 * 1024
MAX_DIRECTORY_DEPTH = 4
MAX_PAGE_SIZE = 200
DEFAULT_DIRECTORY_DEPTH = 1
DEFAULT_PAGE_SIZE = 100
ALLOWED_ENCODING = "utf-8"
PARENT_TRAVERSAL_PATTERN = re.compile(r"(?:^|[\\/])\.\.(?:[\\/]|$)")

ERROR_NOT_FOUND = "NOT_FOUND"
ERROR_PERMISSION_DENIED = "PERMISSION_DENIED"
ERROR_INVALID_ENCODING = "INVALID_ENCODING"
ERROR_PATH_OUTSIDE_ALLOWLIST = "PATH_OUTSIDE_ALLOWLIST"
ERROR_PATH_TRAVERSAL_FORBIDDEN = "PATH_TRAVERSAL_FORBIDDEN"
ERROR_SYMLINK_NOT_ALLOWED = "SYMLINK_NOT_ALLOWED"
ERROR_HASH_LIMIT_EXCEEDED = "HASH_LIMIT_EXCEEDED"
ERROR_INVALID_ARGUMENT = "INVALID_ARGUMENT"

_ALLOWED_ERROR_CODES = {
    ERROR_NOT_FOUND,
    ERROR_PERMISSION_DENIED,
    ERROR_INVALID_ENCODING,
    ERROR_PATH_OUTSIDE_ALLOWLIST,
    ERROR_PATH_TRAVERSAL_FORBIDDEN,
    ERROR_SYMLINK_NOT_ALLOWED,
    ERROR_HASH_LIMIT_EXCEEDED,
    ERROR_INVALID_ARGUMENT,
}

_INPUT_ALLOWED_FIELDS = {
    "path",
    "offset_bytes",
    "max_excerpt_bytes",
    "encoding",
    "include_sha256",
}

_DIRECTORY_INPUT_ALLOWED_FIELDS = {
    "path",
    "max_depth",
    "page_size",
    "page_token",
    "include_hidden",
}

_OUTPUT_FIELDS = {
    "status",
    "path",
    "normalized_path",
    "exists",
    "entry_type",
    "byte_size",
    "excerpt",
    "excerpt_offset_bytes",
    "excerpt_bytes",
    "truncated",
    "sha256",
    "sha256_scope",
    "error",
}

_DIRECTORY_OUTPUT_FIELDS = {
    "status",
    "path",
    "normalized_path",
    "exists",
    "depth",
    "page_size",
    "next_page_token",
    "entries",
    "error",
}


def inspect_file(payload: Dict[str, Any], workspace_root: str | Path) -> Dict[str, Any]:
    """
    Execute bounded, read-only file inspection under an allowlisted workspace root.
    """
    try:
        valid, message, params = _validate_payload(payload)
        path_value = str(payload.get("path", "")) if isinstance(payload, dict) else ""
        if not valid:
            return _error_response(
                path=path_value,
                normalized_path="",
                code=ERROR_INVALID_ARGUMENT,
                message=message,
                exists=False,
                entry_type="other",
                byte_size=None,
                excerpt_offset_bytes=0,
            )

        path_value = params["path"]
        offset_bytes = params["offset_bytes"]
        excerpt_limit = params["max_excerpt_bytes"]
        include_sha256 = params["include_sha256"]

        if PARENT_TRAVERSAL_PATTERN.search(path_value):
            return _error_response(
                path=path_value,
                normalized_path="",
                code=ERROR_PATH_TRAVERSAL_FORBIDDEN,
                message="Parent traversal segments are forbidden.",
                exists=False,
                entry_type="other",
                byte_size=None,
                excerpt_offset_bytes=offset_bytes,
            )

        normalized_root = _normalize_root(workspace_root)
        normalized_path = _normalize_candidate_path(path_value=path_value, workspace_root=normalized_root)
        if not _is_within(normalized_path, normalized_root):
            return _error_response(
                path=path_value,
                normalized_path=str(normalized_path),
                code=ERROR_PATH_OUTSIDE_ALLOWLIST,
                message="Path is outside allowlisted workspace root.",
                exists=False,
                entry_type="other",
                byte_size=None,
                excerpt_offset_bytes=offset_bytes,
            )

        symlink_error = _scan_symlink_components(normalized_path, normalized_root, path_value, offset_bytes)
        if symlink_error is not None:
            return symlink_error

        try:
            path_stat = os.lstat(normalized_path)
        except FileNotFoundError:
            return _error_response(
                path=path_value,
                normalized_path=str(normalized_path),
                code=ERROR_NOT_FOUND,
                message="Path does not exist.",
                exists=False,
                entry_type="other",
                byte_size=None,
                excerpt_offset_bytes=offset_bytes,
            )
        except PermissionError:
            return _error_response(
                path=path_value,
                normalized_path=str(normalized_path),
                code=ERROR_PERMISSION_DENIED,
                message="Permission denied for path.",
                exists=True,
                entry_type="other",
                byte_size=None,
                excerpt_offset_bytes=offset_bytes,
            )

        entry_type = _entry_type(path_stat.st_mode)
        if entry_type != "file":
            return _error_response(
                path=path_value,
                normalized_path=str(normalized_path),
                code=ERROR_INVALID_ARGUMENT,
                message="Path must reference a regular file.",
                exists=True,
                entry_type=entry_type,
                byte_size=path_stat.st_size if entry_type != "directory" else None,
                excerpt_offset_bytes=offset_bytes,
            )

        file_size = int(path_stat.st_size)
        excerpt_bytes = b""
        try:
            with open(normalized_path, "rb") as handle:
                handle.seek(offset_bytes)
                excerpt_bytes = handle.read(excerpt_limit)
        except PermissionError:
            return _error_response(
                path=path_value,
                normalized_path=str(normalized_path),
                code=ERROR_PERMISSION_DENIED,
                message="Permission denied while reading file.",
                exists=True,
                entry_type="file",
                byte_size=file_size,
                excerpt_offset_bytes=offset_bytes,
            )

        try:
            excerpt_text = excerpt_bytes.decode(ALLOWED_ENCODING)
        except UnicodeDecodeError:
            return _error_response(
                path=path_value,
                normalized_path=str(normalized_path),
                code=ERROR_INVALID_ENCODING,
                message="File excerpt is not valid utf-8.",
                exists=True,
                entry_type="file",
                byte_size=file_size,
                excerpt_offset_bytes=offset_bytes,
            )

        excerpt_length = len(excerpt_bytes)
        truncated = (offset_bytes + excerpt_length) < file_size

        sha256_value = None
        sha256_scope = "none"
        if include_sha256:
            if file_size > MAX_HASH_FILE_BYTES:
                return _error_response(
                    path=path_value,
                    normalized_path=str(normalized_path),
                    code=ERROR_HASH_LIMIT_EXCEEDED,
                    message="File size exceeds max_hash_file_bytes.",
                    exists=True,
                    entry_type="file",
                    byte_size=file_size,
                    excerpt_offset_bytes=offset_bytes,
                    excerpt=excerpt_text,
                    excerpt_bytes=excerpt_length,
                    truncated=truncated,
                )
            sha256_value = _sha256_file(normalized_path)
            sha256_scope = "full_file_bytes"

        return {
            "status": "ok",
            "path": path_value,
            "normalized_path": str(normalized_path),
            "exists": True,
            "entry_type": "file",
            "byte_size": file_size,
            "excerpt": excerpt_text,
            "excerpt_offset_bytes": offset_bytes,
            "excerpt_bytes": excerpt_length,
            "truncated": truncated,
            "sha256": sha256_value,
            "sha256_scope": sha256_scope,
            "error": None,
        }
    except Exception:
        path_value = ""
        if isinstance(payload, dict):
            path_value = str(payload.get("path", ""))
        return _error_response(
            path=path_value,
            normalized_path="",
            code=ERROR_INVALID_ARGUMENT,
            message="Inspection failed due to invalid arguments or inaccessible path.",
            exists=False,
            entry_type="other",
            byte_size=None,
            excerpt_offset_bytes=0,
        )


def inspect_directory(payload: Dict[str, Any], workspace_root: str | Path) -> Dict[str, Any]:
    """
    Execute bounded, read-only directory inspection under an allowlisted workspace root.
    """
    try:
        valid, message, params = _validate_directory_payload(payload)
        path_value = str(payload.get("path", "")) if isinstance(payload, dict) else ""
        if not valid:
            return _directory_error_response(
                path=path_value,
                normalized_path="",
                code=ERROR_INVALID_ARGUMENT,
                message=message,
                exists=False,
                depth=0,
                page_size=DEFAULT_PAGE_SIZE,
            )

        path_value = params["path"]
        max_depth = params["max_depth"]
        page_size = params["page_size"]
        page_token = params["page_token"]
        include_hidden = params["include_hidden"]

        if PARENT_TRAVERSAL_PATTERN.search(path_value):
            return _directory_error_response(
                path=path_value,
                normalized_path="",
                code=ERROR_PATH_TRAVERSAL_FORBIDDEN,
                message="Parent traversal segments are forbidden.",
                exists=False,
                depth=max_depth,
                page_size=page_size,
            )

        normalized_root = _normalize_root(workspace_root)
        normalized_path = _normalize_candidate_path(path_value=path_value, workspace_root=normalized_root)
        if not _is_within(normalized_path, normalized_root):
            return _directory_error_response(
                path=path_value,
                normalized_path=str(normalized_path),
                code=ERROR_PATH_OUTSIDE_ALLOWLIST,
                message="Path is outside allowlisted workspace root.",
                exists=False,
                depth=max_depth,
                page_size=page_size,
            )

        symlink_error = _scan_symlink_components_for_directory(
            normalized_path=normalized_path,
            normalized_root=normalized_root,
            original_path=path_value,
            depth=max_depth,
            page_size=page_size,
        )
        if symlink_error is not None:
            return symlink_error

        try:
            path_stat = os.lstat(normalized_path)
        except FileNotFoundError:
            return _directory_error_response(
                path=path_value,
                normalized_path=str(normalized_path),
                code=ERROR_NOT_FOUND,
                message="Path does not exist.",
                exists=False,
                depth=max_depth,
                page_size=page_size,
            )
        except PermissionError:
            return _directory_error_response(
                path=path_value,
                normalized_path=str(normalized_path),
                code=ERROR_PERMISSION_DENIED,
                message="Permission denied for path.",
                exists=True,
                depth=max_depth,
                page_size=page_size,
            )

        if _entry_type(path_stat.st_mode) != "directory":
            return _directory_error_response(
                path=path_value,
                normalized_path=str(normalized_path),
                code=ERROR_INVALID_ARGUMENT,
                message="Path must reference a directory.",
                exists=True,
                depth=max_depth,
                page_size=page_size,
            )

        entries, error = _collect_directory_entries(
            root_directory=normalized_path,
            allowlist_root=normalized_root,
            max_depth=max_depth,
            include_hidden=include_hidden,
            original_path=path_value,
            request_depth=max_depth,
            request_page_size=page_size,
        )
        if error is not None:
            return error

        offset, token_error = _decode_page_token(page_token)
        if token_error is not None:
            return _directory_error_response(
                path=path_value,
                normalized_path=str(normalized_path),
                code=ERROR_INVALID_ARGUMENT,
                message=token_error,
                exists=True,
                depth=max_depth,
                page_size=page_size,
            )
        if offset > len(entries):
            return _directory_error_response(
                path=path_value,
                normalized_path=str(normalized_path),
                code=ERROR_INVALID_ARGUMENT,
                message="page_token offset is out of range.",
                exists=True,
                depth=max_depth,
                page_size=page_size,
            )

        page_entries = entries[offset: offset + page_size]
        next_token = None
        if offset + page_size < len(entries):
            next_token = str(offset + page_size)

        return {
            "status": "ok",
            "path": path_value,
            "normalized_path": str(normalized_path),
            "exists": True,
            "depth": max_depth,
            "page_size": page_size,
            "next_page_token": next_token,
            "entries": page_entries,
            "error": None,
        }
    except Exception:
        path_value = ""
        if isinstance(payload, dict):
            path_value = str(payload.get("path", ""))
        return _directory_error_response(
            path=path_value,
            normalized_path="",
            code=ERROR_INVALID_ARGUMENT,
            message="Directory inspection failed due to invalid arguments or inaccessible path.",
            exists=False,
            depth=0,
            page_size=DEFAULT_PAGE_SIZE,
        )


def _validate_payload(payload: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    if not isinstance(payload, dict):
        return False, "Payload must be an object.", {}
    unknown_fields = [key for key in payload.keys() if key not in _INPUT_ALLOWED_FIELDS]
    if unknown_fields:
        return False, f"Unsupported payload fields: {', '.join(sorted(unknown_fields))}.", {}
    if "path" not in payload:
        return False, "Missing required field: path.", {}
    path = payload.get("path")
    if not isinstance(path, str) or not path.strip():
        return False, "Path must be a non-empty string.", {}

    offset_bytes = payload.get("offset_bytes", 0)
    if not isinstance(offset_bytes, int) or offset_bytes < 0:
        return False, "offset_bytes must be an integer >= 0.", {}

    max_excerpt_bytes = payload.get("max_excerpt_bytes", DEFAULT_EXCERPT_BYTES)
    if not isinstance(max_excerpt_bytes, int):
        return False, "max_excerpt_bytes must be an integer.", {}
    if max_excerpt_bytes < 1 or max_excerpt_bytes > MAX_EXCERPT_BYTES:
        return False, f"max_excerpt_bytes must be between 1 and {MAX_EXCERPT_BYTES}.", {}

    encoding = payload.get("encoding", ALLOWED_ENCODING)
    if encoding != ALLOWED_ENCODING:
        return False, "encoding must be utf-8.", {}

    include_sha256 = payload.get("include_sha256", False)
    if not isinstance(include_sha256, bool):
        return False, "include_sha256 must be boolean.", {}

    return True, "", {
        "path": path,
        "offset_bytes": offset_bytes,
        "max_excerpt_bytes": max_excerpt_bytes,
        "include_sha256": include_sha256,
    }


def _validate_directory_payload(payload: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    if not isinstance(payload, dict):
        return False, "Payload must be an object.", {}
    unknown_fields = [key for key in payload.keys() if key not in _DIRECTORY_INPUT_ALLOWED_FIELDS]
    if unknown_fields:
        return False, f"Unsupported payload fields: {', '.join(sorted(unknown_fields))}.", {}
    if "path" not in payload:
        return False, "Missing required field: path.", {}
    path = payload.get("path")
    if not isinstance(path, str) or not path.strip():
        return False, "Path must be a non-empty string.", {}

    max_depth = payload.get("max_depth", DEFAULT_DIRECTORY_DEPTH)
    if not isinstance(max_depth, int):
        return False, "max_depth must be an integer.", {}
    if max_depth < 0 or max_depth > MAX_DIRECTORY_DEPTH:
        return False, f"max_depth must be between 0 and {MAX_DIRECTORY_DEPTH}.", {}

    page_size = payload.get("page_size", DEFAULT_PAGE_SIZE)
    if not isinstance(page_size, int):
        return False, "page_size must be an integer.", {}
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        return False, f"page_size must be between 1 and {MAX_PAGE_SIZE}.", {}

    page_token = payload.get("page_token", None)
    if page_token is not None and not isinstance(page_token, str):
        return False, "page_token must be a string or null.", {}

    include_hidden = payload.get("include_hidden", False)
    if not isinstance(include_hidden, bool):
        return False, "include_hidden must be boolean.", {}

    return True, "", {
        "path": path,
        "max_depth": max_depth,
        "page_size": page_size,
        "page_token": page_token,
        "include_hidden": include_hidden,
    }


def _normalize_root(workspace_root: str | Path) -> Path:
    root = Path(workspace_root).expanduser()
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve(strict=False)
    return root.resolve(strict=False)


def _normalize_candidate_path(*, path_value: str, workspace_root: Path) -> Path:
    raw = Path(path_value).expanduser()
    if raw.is_absolute():
        combined = raw
    else:
        combined = workspace_root / raw
    normalized = os.path.abspath(os.path.normpath(str(combined)))
    return Path(normalized)


def _is_within(path_value: Path, root: Path) -> bool:
    try:
        path_value.relative_to(root)
        return True
    except ValueError:
        return False


def _scan_symlink_components(
    normalized_path: Path,
    normalized_root: Path,
    original_path: str,
    offset_bytes: int,
) -> Dict[str, Any] | None:
    try:
        relative_parts = normalized_path.relative_to(normalized_root).parts
    except ValueError:
        return _error_response(
            path=original_path,
            normalized_path=str(normalized_path),
            code=ERROR_PATH_OUTSIDE_ALLOWLIST,
            message="Path is outside allowlisted workspace root.",
            exists=False,
            entry_type="other",
            byte_size=None,
            excerpt_offset_bytes=offset_bytes,
        )

    current = normalized_root
    for part in relative_parts:
        candidate = current / part
        try:
            mode = os.lstat(candidate).st_mode
        except FileNotFoundError:
            return None
        except PermissionError:
            return _error_response(
                path=original_path,
                normalized_path=str(normalized_path),
                code=ERROR_PERMISSION_DENIED,
                message="Permission denied while validating path.",
                exists=False,
                entry_type="other",
                byte_size=None,
                excerpt_offset_bytes=offset_bytes,
            )

        if stat.S_ISLNK(mode):
            target_outside = _symlink_target_outside_allowlist(candidate, normalized_root)
            if target_outside:
                return _error_response(
                    path=original_path,
                    normalized_path=str(normalized_path),
                    code=ERROR_PATH_OUTSIDE_ALLOWLIST,
                    message="Symlink target resolves outside allowlisted workspace root.",
                    exists=True,
                    entry_type="symlink",
                    byte_size=None,
                    excerpt_offset_bytes=offset_bytes,
                )
            return _error_response(
                path=original_path,
                normalized_path=str(normalized_path),
                code=ERROR_SYMLINK_NOT_ALLOWED,
                message="Symlinks are not allowed for inspect_file reads.",
                exists=True,
                entry_type="symlink",
                byte_size=None,
                excerpt_offset_bytes=offset_bytes,
            )
        current = candidate
    return None


def _scan_symlink_components_for_directory(
    *,
    normalized_path: Path,
    normalized_root: Path,
    original_path: str,
    depth: int,
    page_size: int,
) -> Dict[str, Any] | None:
    try:
        relative_parts = normalized_path.relative_to(normalized_root).parts
    except ValueError:
        return _directory_error_response(
            path=original_path,
            normalized_path=str(normalized_path),
            code=ERROR_PATH_OUTSIDE_ALLOWLIST,
            message="Path is outside allowlisted workspace root.",
            exists=False,
            depth=depth,
            page_size=page_size,
        )

    current = normalized_root
    for part in relative_parts:
        candidate = current / part
        try:
            mode = os.lstat(candidate).st_mode
        except FileNotFoundError:
            return None
        except PermissionError:
            return _directory_error_response(
                path=original_path,
                normalized_path=str(normalized_path),
                code=ERROR_PERMISSION_DENIED,
                message="Permission denied while validating path.",
                exists=False,
                depth=depth,
                page_size=page_size,
            )

        if stat.S_ISLNK(mode):
            target_outside = _symlink_target_outside_allowlist(candidate, normalized_root)
            if target_outside:
                return _directory_error_response(
                    path=original_path,
                    normalized_path=str(normalized_path),
                    code=ERROR_PATH_OUTSIDE_ALLOWLIST,
                    message="Symlink target resolves outside allowlisted workspace root.",
                    exists=True,
                    depth=depth,
                    page_size=page_size,
                )
            return _directory_error_response(
                path=original_path,
                normalized_path=str(normalized_path),
                code=ERROR_SYMLINK_NOT_ALLOWED,
                message="Symlinks are not allowed for inspect_directory traversal.",
                exists=True,
                depth=depth,
                page_size=page_size,
            )
        current = candidate
    return None


def _symlink_target_outside_allowlist(link_path: Path, allowlist_root: Path) -> bool:
    try:
        target = os.readlink(link_path)
    except OSError:
        return True

    target_path = Path(target)
    if not target_path.is_absolute():
        target_path = (link_path.parent / target_path).resolve(strict=False)
    else:
        target_path = target_path.resolve(strict=False)
    return not _is_within(target_path, allowlist_root)


def _entry_type(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "other"


def _sha256_file(path_value: Path) -> str:
    hasher = hashlib.sha256()
    with open(path_value, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _decode_page_token(page_token: str | None) -> Tuple[int, str | None]:
    if page_token is None or not str(page_token).strip():
        return 0, None
    token = str(page_token).strip()
    if not token.isdigit():
        return 0, "page_token must be a non-negative integer string."
    return int(token), None


def _collect_directory_entries(
    *,
    root_directory: Path,
    allowlist_root: Path,
    max_depth: int,
    include_hidden: bool,
    original_path: str,
    request_depth: int,
    request_page_size: int,
) -> Tuple[list[Dict[str, Any]], Dict[str, Any] | None]:
    # queue stores (directory_path, entry_depth_for_children)
    queue: list[Tuple[Path, int]] = [(root_directory, 1)]
    entries: list[Dict[str, Any]] = []

    while queue:
        directory_path, entry_depth = queue.pop(0)
        if entry_depth > max_depth:
            continue

        try:
            with os.scandir(directory_path) as iterator:
                dir_entries = sorted(list(iterator), key=lambda item: item.name)
        except PermissionError:
            return [], _directory_error_response(
                path=original_path,
                normalized_path=str(directory_path),
                code=ERROR_PERMISSION_DENIED,
                message="Permission denied while reading directory.",
                exists=True,
                depth=request_depth,
                page_size=request_page_size,
            )
        except FileNotFoundError:
            return [], _directory_error_response(
                path=original_path,
                normalized_path=str(directory_path),
                code=ERROR_NOT_FOUND,
                message="Directory no longer exists.",
                exists=False,
                depth=request_depth,
                page_size=request_page_size,
            )

        for entry in dir_entries:
            if not include_hidden and entry.name.startswith("."):
                continue

            normalized_entry = _normalize_candidate_path(path_value=entry.path, workspace_root=allowlist_root)
            if not _is_within(normalized_entry, allowlist_root):
                return [], _directory_error_response(
                    path=original_path,
                    normalized_path=str(normalized_entry),
                    code=ERROR_PATH_OUTSIDE_ALLOWLIST,
                    message="Observed entry outside allowlisted workspace root.",
                    exists=False,
                    depth=request_depth,
                    page_size=request_page_size,
                )

            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except PermissionError:
                return [], _directory_error_response(
                    path=original_path,
                    normalized_path=str(normalized_entry),
                    code=ERROR_PERMISSION_DENIED,
                    message="Permission denied while reading entry metadata.",
                    exists=True,
                    depth=request_depth,
                    page_size=request_page_size,
                )

            entry_type = _entry_type(entry_stat.st_mode)
            byte_size = int(entry_stat.st_size) if entry_type == "file" else None

            symlink_target: str | None = None
            symlink_target_within_allowlist: bool | None = None
            if entry_type == "symlink":
                try:
                    symlink_target = os.readlink(normalized_entry)
                    symlink_target_within_allowlist = _symlink_target_within_allowlist(
                        symlink_path=normalized_entry,
                        symlink_target=symlink_target,
                        allowlist_root=allowlist_root,
                    )
                except OSError:
                    symlink_target = None
                    symlink_target_within_allowlist = False

            entries.append(
                {
                    "name": entry.name,
                    "path": str(normalized_entry),
                    "entry_type": entry_type,
                    "byte_size": byte_size,
                    "symlink_target": symlink_target,
                    "symlink_target_within_allowlist": symlink_target_within_allowlist,
                }
            )

            if entry_type == "directory" and entry_depth < max_depth:
                queue.append((normalized_entry, entry_depth + 1))

    entries.sort(key=lambda item: str(item.get("path", "")))
    return entries, None


def _symlink_target_within_allowlist(
    *,
    symlink_path: Path,
    symlink_target: str,
    allowlist_root: Path,
) -> bool:
    target_path = Path(symlink_target)
    if target_path.is_absolute():
        normalized = Path(os.path.abspath(os.path.normpath(str(target_path))))
    else:
        normalized = Path(os.path.abspath(os.path.normpath(str(symlink_path.parent / target_path))))
    return _is_within(normalized, allowlist_root)


def _error_response(
    *,
    path: str,
    normalized_path: str,
    code: str,
    message: str,
    exists: bool,
    entry_type: str,
    byte_size: int | None,
    excerpt_offset_bytes: int,
    excerpt: str | None = None,
    excerpt_bytes: int = 0,
    truncated: bool = False,
) -> Dict[str, Any]:
    safe_code = code if code in _ALLOWED_ERROR_CODES else ERROR_INVALID_ARGUMENT
    response = {
        "status": "error",
        "path": path,
        "normalized_path": normalized_path,
        "exists": exists,
        "entry_type": entry_type,
        "byte_size": byte_size,
        "excerpt": excerpt,
        "excerpt_offset_bytes": excerpt_offset_bytes,
        "excerpt_bytes": excerpt_bytes,
        "truncated": truncated,
        "sha256": None,
        "sha256_scope": "none",
        "error": {
            "code": safe_code,
            "message": message,
            "path": path,
            "normalized_path": normalized_path,
            "retryable": False,
        },
    }
    for key in _OUTPUT_FIELDS:
        response.setdefault(key, None)
    return response


def _directory_error_response(
    *,
    path: str,
    normalized_path: str,
    code: str,
    message: str,
    exists: bool,
    depth: int,
    page_size: int,
) -> Dict[str, Any]:
    safe_code = code if code in _ALLOWED_ERROR_CODES else ERROR_INVALID_ARGUMENT
    response = {
        "status": "error",
        "path": path,
        "normalized_path": normalized_path,
        "exists": exists,
        "depth": depth,
        "page_size": page_size,
        "next_page_token": None,
        "entries": [],
        "error": {
            "code": safe_code,
            "message": message,
            "path": path,
            "normalized_path": normalized_path,
            "retryable": False,
        },
    }
    for key in _DIRECTORY_OUTPUT_FIELDS:
        response.setdefault(key, None)
    return response
