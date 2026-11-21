"""Perceptual hashing and near-duplicate lookup.

pHash and dHash are implemented directly on numpy rather than through a wrapper
library. The transform is short, the behaviour is fully specified here, and the
result is reproducible across environments, which matters because a Hamming
distance is used as evidence.

pHash: 32x32 greyscale, type-II DCT, retain the 8x8 low-frequency block, threshold
at its median. dHash: 9x8 greyscale, compare horizontal neighbours. Both yield 64
bits rendered as 16 hex characters.

Lookup uses a BK-tree. Hamming distance is a metric, so the triangle inequality
allows pruning and avoids scanning the whole ward corpus for every closure.
"""

from __future__ import annotations

import io
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from PIL import Image, UnidentifiedImageError

from app.core.errors import EvidenceUnreadableError
from app.core.logging import get_logger

log = get_logger(__name__)

HASH_BITS = 64
HASH_HEX_LENGTH = 16
_PHASH_SIZE = 32
_BLOCK = 8


def _dct_matrix(size: int) -> np.ndarray:
    """Orthonormal type-II DCT basis, computed once per size."""
    indices = np.arange(size, dtype=np.float64)
    basis = np.cos(math.pi * (indices[:, None] + 0.5) * indices[None, :] / size)
    basis *= math.sqrt(2.0 / size)
    basis[0, :] *= math.sqrt(0.5)
    return basis


_DCT_32 = _dct_matrix(_PHASH_SIZE)


def _greyscale(data: bytes, size: tuple[int, int]) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(data)) as image:
            resized = image.convert("L").resize(size, Image.Resampling.LANCZOS)
            return np.asarray(resized, dtype=np.float64)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise EvidenceUnreadableError("Image could not be decoded for hashing.") from exc


def _bits_to_hex(bits: np.ndarray) -> str:
    value = 0
    for bit in bits.flatten():
        value = (value << 1) | int(bool(bit))
    return f"{value:0{HASH_HEX_LENGTH}x}"


def compute_phash(data: bytes) -> str:
    """Return the 64-bit perceptual hash of an image as 16 hex characters."""
    pixels = _greyscale(data, (_PHASH_SIZE, _PHASH_SIZE))
    transformed = _DCT_32 @ pixels @ _DCT_32.T
    block = transformed[:_BLOCK, :_BLOCK]
    return _bits_to_hex(block > np.median(block))


def compute_dhash(data: bytes) -> str:
    """Return the 64-bit horizontal gradient hash as 16 hex characters."""
    pixels = _greyscale(data, (_BLOCK + 1, _BLOCK))
    return _bits_to_hex(pixels[:, 1:] > pixels[:, :-1])


def hash_to_int(digest: str) -> int:
    """Parse a hex hash, rejecting malformed input rather than silently coercing."""
    cleaned = digest.strip().lower()
    if len(cleaned) != HASH_HEX_LENGTH:
        raise ValueError(f"expected {HASH_HEX_LENGTH} hex characters, got {len(cleaned)}")
    return int(cleaned, 16)


def int_to_hash(value: int) -> str:
    """Render an integer hash in canonical hex form."""
    if not 0 <= value < 1 << HASH_BITS:
        raise ValueError("hash value exceeds 64 bits")
    return f"{value:0{HASH_HEX_LENGTH}x}"


def hamming(left: str, right: str) -> int:
    """Bit distance between two hashes."""
    return (hash_to_int(left) ^ hash_to_int(right)).bit_count()


@dataclass(slots=True)
class _Node:
    digest: str
    value: int
    members: list[str] = field(default_factory=list)
    children: dict[int, _Node] = field(default_factory=dict)


@dataclass(slots=True)
class Match:
    """One near-duplicate hit."""

    identifier: str
    digest: str
    distance: int


class BKTree:
    """Metric tree over Hamming distance.

    Identical hashes share a node and accumulate identifiers, so a photograph
    reused across ten tickets costs one node rather than ten.
    """

    def __init__(self) -> None:
        self._root: _Node | None = None
        self._size = 0

    def __len__(self) -> int:
        return self._size

    def insert(self, digest: str, identifier: str) -> None:
        value = hash_to_int(digest)
        if self._root is None:
            self._root = _Node(digest=digest, value=value, members=[identifier])
            self._size = 1
            return

        node = self._root
        while True:
            distance = (node.value ^ value).bit_count()
            if distance == 0:
                if identifier not in node.members:
                    node.members.append(identifier)
                return
            child = node.children.get(distance)
            if child is None:
                node.children[distance] = _Node(digest=digest, value=value, members=[identifier])
                self._size += 1
                return
            node = child

    def search(self, digest: str, max_distance: int) -> list[Match]:
        """Return every member within max_distance, ordered nearest first."""
        if max_distance < 0:
            raise ValueError("max_distance must be non-negative")
        if self._root is None:
            return []

        target = hash_to_int(digest)
        results: list[Match] = []
        stack = [self._root]
        while stack:
            node = stack.pop()
            distance = (node.value ^ target).bit_count()
            if distance <= max_distance:
                results.extend(
                    Match(identifier=member, digest=node.digest, distance=distance)
                    for member in node.members
                )
            low = distance - max_distance
            high = distance + max_distance
            stack.extend(child for edge, child in node.children.items() if low <= edge <= high)

        results.sort(key=lambda item: (item.distance, item.identifier))
        return results

    def nearest(self, digest: str) -> Match | None:
        """Return the closest member, widening the radius until something is found."""
        for radius in range(0, HASH_BITS + 1):
            found = self.search(digest, radius)
            if found:
                return found[0]
        return None


def build_index(entries: Iterable[tuple[str, str]]) -> BKTree:
    """Build an index from (identifier, hash) pairs."""
    tree = BKTree()
    for identifier, digest in entries:
        tree.insert(digest, identifier)
    return tree


def reuse_verdict(
    distance: int,
    *,
    identical_content: bool,
    threshold: int,
    strict_distance: int = 2,
) -> Literal["reuse", "similar", "distinct"]:
    """Classify a near-duplicate hit without accusing an honest repair.

    Perceptual hashing encodes low-frequency layout, so a genuine repair
    photographed at the same location can fall inside the similarity threshold.
    Treating that as reuse would manufacture false positives against exactly the
    honest officers this system is meant to protect.

    Reuse therefore requires corroboration: byte-identical content, or a distance
    tight enough that the images are effectively the same photograph. A merely
    similar image is reported as advisory context and never blocks closure on its
    own. Comparison scope is also restricted to prior closure evidence, never to
    the complaint's own before image.
    """
    if distance < 0:
        raise ValueError("distance must be non-negative")
    if identical_content or distance <= strict_distance:
        return "reuse"
    if distance <= threshold:
        return "similar"
    return "distinct"
