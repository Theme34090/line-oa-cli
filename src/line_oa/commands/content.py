from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from .. import config as cfgmod
from ..client import fetch_content, make_client
from ..errors import EXIT_OK, emit_json


EPILOG = """\
Fetch a chat attachment (image/video/audio/file) by its contentHash.

The hash is what `line-oa read` returns in `messages[].contentHash` for
media messages. The binary is cached under
  ~/.cache/line-oa/content/<botId>/
keyed by the hash; subsequent calls return the cached path without
hitting the network. LINE content is immutable per hash, so the cache
is permanent.

Output (JSON to stdout):

  {
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


def _cache_dir(bot_id: str) -> Path:
    return Path.home() / ".cache" / "line-oa" / "content" / bot_id


def _cache_key(content_hash: str) -> str:
    return hashlib.sha256(content_hash.encode("utf-8")).hexdigest()[:16]


def run(args) -> int:
    cfg = cfgmod.load(args.config)
    _, bot_id = cfgmod.resolve_account(cfg, args.account)
    content_hash: str = args.content_hash

    # Explicit --out: always fetch, write to the given path.
    if args.out is not None:
        out_path = Path(args.out).expanduser().resolve()
        with make_client(cfg, bot_id) as client:
            data, ctype = fetch_content(client, bot_id, content_hash)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
        emit_json({
            "path": str(out_path),
            "contentType": ctype,
            "bytes": len(data),
            "cached": False,
        })
        return EXIT_OK

    # Cache-aware path: check for an existing file under any extension.
    cache_dir = _cache_dir(bot_id)
    key = _cache_key(content_hash)
    if not args.no_cache and cache_dir.exists():
        for existing in cache_dir.glob(f"{key}.*"):
            ctype, _ = mimetypes.guess_type(existing.name)
            emit_json({
                "path": str(existing),
                "contentType": ctype or "application/octet-stream",
                "bytes": existing.stat().st_size,
                "cached": True,
            })
            return EXIT_OK

    with make_client(cfg, bot_id) as client:
        data, ctype = fetch_content(client, bot_id, content_hash)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"{key}{_ext_for(ctype)}"
    out_path.write_bytes(data)
    emit_json({
        "path": str(out_path),
        "contentType": ctype,
        "bytes": len(data),
        "cached": False,
    })
    return EXIT_OK
