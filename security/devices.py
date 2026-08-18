"""
Jarvis trusted-device authentication — Step 14.

Shared authentication layer for every Jarvis transport.

Trusted records are stored outside the web/static directory. Only SHA-256
hashes of device tokens are persisted.

The first device can be bootstrapped explicitly with bootstrap_device().
New devices require an existing trusted device to approve them.
"""

import hashlib
import json
import secrets
import threading
import uuid
from pathlib import Path


class DeviceAuth:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data = {"devices": {}}
        self._load()

    def _load(self):
        with self._lock:
            if not self.path.exists():
                self._save()
                return

            try:
                self._data = json.loads(
                    self.path.read_text(encoding="utf-8")
                )
            except Exception:
                self._data = {"devices": {}}

            self._data.setdefault("devices", {})

    def _save(self):
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._data, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

    def bootstrap_device(
        self,
        device_id: str,
        device_type: str,
        name: str,
    ) -> str:
        """
        Create the first trusted credential.

        Refuses to overwrite an existing trusted database.
        """
        with self._lock:
            if self._data["devices"]:
                raise RuntimeError(
                    "Trusted devices already exist."
                )

            token = secrets.token_urlsafe(32)

            self._data["devices"][device_id] = {
                "device_id": device_id,
                "device_type": device_type,
                "name": name,
                "token_hash": self._hash(token),
            }

            self._save()
            return token

    def authenticate(
        self,
        device_id: str,
        token: str,
    ):
        with self._lock:
            record = self._data["devices"].get(device_id)

            if not record:
                return None

            if not secrets.compare_digest(
                record["token_hash"],
                self._hash(token),
            ):
                return None

            return dict(record)

    def is_trusted(self, device_id: str) -> bool:
        with self._lock:
            return device_id in self._data["devices"]

    def request_pairing(
        self,
        device_id: str,
        device_type: str,
        name: str,
    ):
        """
        Generate a pending pairing request.

        The request itself is intentionally not persisted as a trusted
        credential. It becomes trusted only after approval.
        """
        return {
            "request_id": str(uuid.uuid4()),
            "device_id": device_id,
            "device_type": device_type,
            "name": name,
        }

    def approve(self, device_id: str):
        """
        Approve a device and return its one-time token.

        The raw token is returned only once to the caller.
        """
        with self._lock:
            if device_id in self._data["devices"]:
                raise ValueError(
                    "Device is already trusted."
                )

            token = secrets.token_urlsafe(32)

            # The caller must supply the pending metadata through
            # approve_pending() when using the pairing workflow.
            raise RuntimeError(
                "Use approve_pending() for pairing requests."
            )

    def approve_pending(self, request: dict) -> str:
        with self._lock:
            device_id = request["device_id"]

            if device_id in self._data["devices"]:
                raise ValueError(
                    "Device is already trusted."
                )

            token = secrets.token_urlsafe(32)

            self._data["devices"][device_id] = {
                "device_id": device_id,
                "device_type": request["device_type"],
                "name": request["name"],
                "token_hash": self._hash(token),
            }

            self._save()
            return token

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            existed = device_id in self._data["devices"]

            if existed:
                del self._data["devices"][device_id]
                self._save()

            return existed

    def list_devices(self):
        with self._lock:
            return [
                {
                    "device_id": record["device_id"],
                    "device_type": record["device_type"],
                    "name": record["name"],
                }
                for record in self._data["devices"].values()
            ]


def default_auth_path(root: str | Path) -> Path:
    return Path(root) / "data" / "trusted_devices.json"
