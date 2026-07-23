from __future__ import annotations

import io
import os
from typing import Any

from minio import Minio
from minio.commonconfig import ENABLED
from minio.versioningconfig import VersioningConfig
from sqlalchemy.orm import Session

from orbital_shared.campaigns import (
    IntegrityError,
    checksum_bytes,
    content_bytes,
    decode_verified_json,
)
from orbital_shared.database import ObjectStore, StorageObjectRecord
from orbital_shared.models import utcnow


class VersionedObjectStorage:
    def __init__(self) -> None:
        self.bucket = os.getenv("MINIO_BUCKET", "orbital-sigma")
        self.client = Minio(
            os.getenv("MINIO_ENDPOINT", "localhost:9000"),
            access_key=os.getenv("MINIO_ACCESS_KEY", "orbital"),
            secret_key=os.getenv("MINIO_SECRET_KEY", "orbital-development-secret"),
            secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
        )
        self.database = ObjectStore()

    def ensure_ready(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
        self.client.set_bucket_versioning(self.bucket, VersioningConfig(ENABLED))

    def health(self) -> str:
        try:
            self.ensure_ready()
            return "AVAILABLE"
        except Exception:
            return "UNAVAILABLE"

    def put_json(self, object_path: str, kind: str, owner_id: str, value: Any) -> dict[str, Any]:
        self.ensure_ready()
        payload = content_bytes(value)
        checksum = checksum_bytes(payload)
        try:
            existing = self.client.stat_object(self.bucket, object_path)
            existing_checksum = existing.metadata.get("x-amz-meta-sha256")
            if existing_checksum and f"sha256:{existing_checksum}" != checksum:
                raise IntegrityError(f"object path checksum conflict: {object_path}")
            if existing_checksum:
                self._record(
                    object_path,
                    kind,
                    owner_id,
                    checksum,
                    len(payload),
                    existing.version_id,
                )
                return {
                    "path": object_path,
                    "checksum": checksum,
                    "size_bytes": len(payload),
                    "version_id": existing.version_id,
                    "idempotent": True,
                }
        except IntegrityError:
            raise
        except Exception:
            pass
        result = self.client.put_object(
            self.bucket,
            object_path,
            io.BytesIO(payload),
            length=len(payload),
            content_type="application/json",
            metadata={"sha256": checksum.removeprefix("sha256:")},
        )
        self._record(object_path, kind, owner_id, checksum, len(payload), result.version_id)
        return {
            "path": object_path,
            "checksum": checksum,
            "size_bytes": len(payload),
            "version_id": result.version_id,
            "idempotent": False,
        }

    def get_json(self, object_path: str, expected_checksum: str | None = None) -> Any:
        response = self.client.get_object(self.bucket, object_path)
        try:
            payload = response.read()
        finally:
            response.close()
            response.release_conn()
        try:
            return decode_verified_json(payload, expected_checksum)
        except IntegrityError as exc:
            raise IntegrityError(f"{object_path}: {exc}") from exc

    def stat(self, object_path: str) -> dict[str, Any]:
        value = self.client.stat_object(self.bucket, object_path)
        return {
            "path": object_path,
            "size_bytes": value.size,
            "version_id": value.version_id,
            "checksum": (
                f"sha256:{value.metadata['x-amz-meta-sha256']}"
                if value.metadata.get("x-amz-meta-sha256")
                else None
            ),
        }

    def _record(
        self,
        object_path: str,
        kind: str,
        owner_id: str,
        checksum: str,
        size_bytes: int,
        version_id: str | None,
    ) -> None:
        with Session(self.database.engine) as session:
            existing = session.get(StorageObjectRecord, object_path)
            if existing:
                if existing.checksum != checksum:
                    raise IntegrityError(f"database checksum conflict: {object_path}")
                if version_id:
                    existing.minio_version_id = version_id
            else:
                session.add(
                    StorageObjectRecord(
                        object_path=object_path,
                        kind=kind,
                        owner_id=owner_id,
                        version="v1",
                        checksum=checksum,
                        size_bytes=size_bytes,
                        minio_version_id=version_id,
                        created_at=utcnow(),
                    )
                )
            session.commit()
