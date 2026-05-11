from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from .. import config as cfgmod
from ..client import fetch_content, make_client
from ..errors import EXIT_OK, emit_json


EPILOG = """\
Fetch a chat attachment (image/video/audio/file) by its contentHash.

The hash is what `line-oa read` returns in `messages[].contentHash` for
media messages. The binary is cached under
  $XDG_CACHE_HOME/line-oa/content/<botId>/   (or ~/.cache/...)
The cache is permanent (LINE content is immutable per hash) and
restricted to owner-only (0600/0700) since attachments can include
receipts, ID cards, and other sensitive material.

Output (JSON to stdout):

  {
    "account":     "<name>",
    "path":        "/abs/path/to/file.jpg",
    "contentType": "image/jpeg",
    "bytes":       503631,
    "cached":      false
  }

Typical agent flow:

  HASH=$(line-oa read U... | jq -r '.messages[] | select(.type=="image") | .contentHash' | head -1)
  IMG=$(line-oa content "$HASH" | jq -r .path)
  # then open $IMG with an image viewer / your file reader
"""


# mimetypes.guess_extension is system-dependent (.jpe vs .jpg) and missing
# some types LINE serves. Pin the common ones; fall back to guess_extension.
_EXT_OVERRIDES = {
    "image/jpeg":  ".jpg",
    "image/jpg":   ".jpg",
    "image/png":   ".png",
    "image/gif":   ".gif",
    "image/webp":  ".webp",
    "video/mp4":   ".mp4",
    "audio/m4a":   ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac":   ".aac",
    "audio/mpeg":  ".mp3",
}


def _ext_for(content_type: str) -> str:
    main = content_type.split(";", 1)[0].strip().lower()
    if main in _EXT_OVERRIDES:
        return _EXT_OVERRIDES[main]
    return mimetypes.guess_extension(main) or ".bin"


def _safe_name(content_hash: str) -> str:
    # LINE's contentHash is URL-safe base64 plus `=` padding. Strip the
    # padding (still unique) and any unexpected char so the filename is
    # portable across filesystems.
    base = content_hash.rstrip("=")
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in base)


def _cache_dir(bot_id: str) -> Path:
    return cfgmod.cache_path() / "content" / bot_id


def _write_secure(path: Path, data: bytes) -> None:
    """Atomically write `data` to `path` with 0600 permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_bytes(data)
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def run(args) -> int:
    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)
    content_hash: str = args.content_hash
    safe = _safe_name(content_hash)

    if args.out is None and not args.no_cache:
        cache_dir = _cache_dir(bot_id)
        if cache_dir.exists():
            for existing in cache_dir.glob(f"{safe}.*"):
                ctype, _ = mimetypes.guess_type(existing.name)
                emit_json({
                    "account": name,
                    "path": str(existing),
                    "contentType": ctype or "application/octet-stream",
                    "bytes": existing.stat().st_size,
                    "cached": True,
                })
                return EXIT_OK

    with make_client(cfg, bot_id) as client:
        data, ctype = fetch_content(client, bot_id, content_hash)

    if args.out is not None:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
    else:
        cache_dir = _cache_dir(bot_id)
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            cache_dir.chmod(0o700)
        except OSError:
            pass
        out_path = cache_dir / f"{safe}{_ext_for(ctype)}"
        _write_secure(out_path, data)

    emit_json({
        "account": name,
        "path": str(out_path),
        "contentType": ctype,
        "bytes": len(data),
        "cached": False,
    })
    return EXIT_OK
