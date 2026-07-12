import json
import os
import re
import sys
from pathlib import Path


path = Path("/etc/homelab-resource-monitor/hub.json")
if len(sys.argv) != 3:
    raise SystemExit("usage: add-node-hash.py NODE_ID SHA256")
node_id, token_hash = sys.argv[1:]
if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", node_id):
    raise SystemExit("invalid node id")
if len(token_hash) != 64 or any(character not in "0123456789abcdef" for character in token_hash):
    raise SystemExit("invalid SHA-256 hash")
stat = path.stat()
config = json.loads(path.read_text())
config["token_sha256"][node_id] = token_hash
temporary = path.with_suffix(".tmp")
temporary.write_text(json.dumps(config))
os.chown(temporary, stat.st_uid, stat.st_gid)
os.chmod(temporary, stat.st_mode)
os.replace(temporary, path)
