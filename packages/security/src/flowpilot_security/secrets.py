from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Protocol

from .errors import SecurityError, SecurityErrorCode
from .models import CapabilityHandle, CapabilityUse


class SecretLease:
    """Mutable, non-serializable plaintext lease cleared at scope exit."""

    __slots__ = ("_buffer", "_closed")

    def __init__(self, material: bytes) -> None:
        if not material:
            raise SecurityError(
                SecurityErrorCode.SECRET_UNAVAILABLE,
                "secret material is unavailable",
            )
        self._buffer = bytearray(material)
        self._closed = False

    def borrow(self) -> memoryview:
        if self._closed:
            raise SecurityError(
                SecurityErrorCode.SECRET_UNAVAILABLE,
                "secret lease is closed",
            )
        return memoryview(self._buffer)

    def close(self) -> None:
        if self._closed:
            return
        for index in range(len(self._buffer)):
            self._buffer[index] = 0
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    def __repr__(self) -> str:
        return f"<SecretLease redacted closed={self._closed}>"

    __str__ = __repr__


class SecretProviderPort(Protocol):
    async def authorize(
        self,
        *,
        secret_ref: str,
        capability: CapabilityHandle,
    ) -> None: ...

    def open(
        self,
        *,
        secret_ref: str,
        capability: CapabilityHandle,
    ) -> AbstractAsyncContextManager[SecretLease]: ...


@dataclass(frozen=True, slots=True)
class DevelopmentSecretBinding:
    secret_ref: str
    tool_name: str
    resource_digest: str
    audience: str
    allowed_uses: frozenset[CapabilityUse]

    def __post_init__(self) -> None:
        if not self.secret_ref.startswith("secret://development/"):
            raise ValueError("development secret reference is invalid")
        if not self.tool_name or not self.audience or not self.allowed_uses:
            raise ValueError("development secret binding is incomplete")


class DevelopmentSecretProvider:
    """Local-only provider; enterprise Vault/KMS integrations implement the Port."""

    def __init__(
        self,
        *,
        bindings: tuple[DevelopmentSecretBinding, ...],
        material: Mapping[str, bytes],
    ) -> None:
        self._bindings = {item.secret_ref: item for item in bindings}
        if len(self._bindings) != len(bindings) or set(self._bindings) != set(
            material
        ):
            raise ValueError("development secret bindings are not one-to-one")
        self._material = {key: bytes(value) for key, value in material.items()}
        self.open_count = 0

    def open(
        self,
        *,
        secret_ref: str,
        capability: CapabilityHandle,
    ) -> AbstractAsyncContextManager[SecretLease]:
        return self._lease(secret_ref=secret_ref, capability=capability)

    async def authorize(
        self,
        *,
        secret_ref: str,
        capability: CapabilityHandle,
    ) -> None:
        self._binding(secret_ref=secret_ref, capability=capability)

    def _binding(
        self,
        *,
        secret_ref: str,
        capability: CapabilityHandle,
    ) -> DevelopmentSecretBinding:
        binding = self._bindings.get(secret_ref)
        if (
            binding is None
            or binding.tool_name != capability.tool_name
            or binding.resource_digest != capability.resource_digest
            or binding.audience != capability.audience
            or capability.use not in binding.allowed_uses
        ):
            raise SecurityError(
                SecurityErrorCode.SECRET_UNAVAILABLE,
                "secret reference is not authorized for this capability",
            )
        return binding

    @asynccontextmanager
    async def _lease(
        self,
        *,
        secret_ref: str,
        capability: CapabilityHandle,
    ) -> AsyncIterator[SecretLease]:
        self._binding(secret_ref=secret_ref, capability=capability)
        material = self._material.get(secret_ref)
        if material is None:
            raise SecurityError(
                SecurityErrorCode.SECRET_UNAVAILABLE,
                "secret material is unavailable",
            )
        lease = SecretLease(material)
        self.open_count += 1
        try:
            yield lease
        finally:
            lease.close()
