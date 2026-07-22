from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey
from orbital_shared.models import CapabilityToken, canonical_json, sha256_digest


class TokenError(ValueError):
    pass


def canonical_arguments_hash(arguments: dict[str, Any]) -> str:
    return sha256_digest(arguments)


class CapabilityIssuer:
    def __init__(self, signing_key: SigningKey):
        self.signing_key = signing_key
        self.verify_key = signing_key.verify_key

    @classmethod
    def generate(cls) -> CapabilityIssuer:
        return cls(SigningKey.generate())

    @classmethod
    def load_or_create(cls, path: str | Path) -> CapabilityIssuer:
        key_path = Path(path)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if key_path.exists():
            return cls(SigningKey(base64.b64decode(key_path.read_text().strip())))
        issuer = cls.generate()
        key_path.write_text(base64.b64encode(bytes(issuer.signing_key)).decode())
        key_path.chmod(0o600)
        return issuer

    @property
    def public_key(self) -> str:
        return base64.b64encode(bytes(self.verify_key)).decode()

    def sign(self, capability: CapabilityToken) -> str:
        payload = capability.model_dump(mode="json", exclude={"signature"})
        signature = self.signing_key.sign(canonical_json(payload).encode()).signature
        return base64.urlsafe_b64encode(signature).decode()

    @staticmethod
    def verify(capability: CapabilityToken, public_key: str) -> bool:
        if datetime.now(UTC) >= capability.expires_at:
            raise TokenError("capability expired")
        payload = capability.model_dump(mode="json", exclude={"signature"})
        try:
            VerifyKey(base64.b64decode(public_key)).verify(
                canonical_json(payload).encode(),
                base64.urlsafe_b64decode(capability.signature.encode()),
            )
        except (BadSignatureError, ValueError) as exc:
            raise TokenError("invalid capability signature") from exc
        return True

    def issue(self, capability: CapabilityToken) -> CapabilityToken:
        return capability.model_copy(update={"signature": self.sign(capability)})
