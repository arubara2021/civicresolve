"""Closure-remark duplication detection.

Normalisation deliberately preserves spelling errors. The Panchkula pattern was
identical remarks including identical typos, so a spell-correcting or stemming
pipeline would destroy the strongest signal available. Only case, punctuation and
whitespace are collapsed.

Two complementary signals are returned. An exact signature match is the
bulk-closure fingerprint. TF-IDF cosine catches lightly reworded variants. The
ward matrix is cached and rebuilt lazily after invalidation, which keeps repeated
queries cheap at prototype scale.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from app.core.logging import get_logger

log = get_logger(__name__)

_PUNCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+", flags=re.UNICODE)


def normalize_remarks(text: str) -> str:
    """Collapse case, punctuation and whitespace. Never correct spelling."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    without_punctuation = _PUNCTUATION.sub(" ", folded)
    return _WHITESPACE.sub(" ", without_punctuation).strip()


def exact_signature(text: str) -> str:
    """Stable digest of the normalised remark, for exact-match grouping."""
    return hashlib.sha256(normalize_remarks(text).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class TextMatch:
    """One duplicated or near-duplicated remark."""

    identifier: str
    score: float
    exact: bool


@dataclass(slots=True)
class _Corpus:
    identifiers: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)
    signatures: dict[str, list[str]] = field(default_factory=dict)
    vectorizer: TfidfVectorizer | None = None
    matrix: object | None = None
    dirty: bool = True


class DuplicationIndex:
    """Per-ward remark corpus with lazy TF-IDF rebuilds."""

    def __init__(self, *, ngram_max: int = 2) -> None:
        self._wards: dict[str, _Corpus] = {}
        self._ngram_max = ngram_max

    def upsert(self, ward: str, identifier: str, text: str) -> None:
        """Add or replace a remark and mark the ward matrix stale."""
        corpus = self._wards.setdefault(ward, _Corpus())
        normalized = normalize_remarks(text)
        if not normalized:
            return

        if identifier in corpus.identifiers:
            position = corpus.identifiers.index(identifier)
            previous = corpus.documents[position]
            corpus.signatures.get(exact_signature(previous), []).remove(identifier)
            corpus.documents[position] = normalized
        else:
            corpus.identifiers.append(identifier)
            corpus.documents.append(normalized)

        corpus.signatures.setdefault(exact_signature(text), []).append(identifier)
        corpus.dirty = True

    def invalidate(self, ward: str | None = None) -> None:
        """Force a rebuild, or drop a ward entirely."""
        if ward is None:
            self._wards.clear()
            return
        self._wards.pop(ward, None)

    def _ensure_matrix(self, corpus: _Corpus) -> None:
        if not corpus.dirty:
            return
        vectorizer = TfidfVectorizer(
            analyzer="word",
            ngram_range=(1, self._ngram_max),
            min_df=1,
            sublinear_tf=True,
            norm="l2",
            lowercase=False,
            token_pattern=r"(?u)\b\w+\b",
        )
        corpus.matrix = vectorizer.fit_transform(corpus.documents)
        corpus.vectorizer = vectorizer
        corpus.dirty = False

    def query(
        self,
        ward: str,
        text: str,
        *,
        threshold: float = 0.92,
        exclude_identifier: str | None = None,
    ) -> list[TextMatch]:
        """Return remarks at or above the similarity threshold, strongest first.

        Exact signature matches are always reported with score 1.0, even if the
        vectoriser would score them marginally lower due to floating point.
        """
        corpus = self._wards.get(ward)
        normalized = normalize_remarks(text)
        if corpus is None or not normalized or not corpus.documents:
            return []

        self._ensure_matrix(corpus)
        signature = exact_signature(text)
        exact_ids = set(corpus.signatures.get(signature, []))

        vector = corpus.vectorizer.transform([normalized])
        if vector.nnz == 0:
            scores = np.zeros(len(corpus.documents))
        else:
            scores = (corpus.matrix @ vector.T).toarray().ravel()

        matches: list[TextMatch] = []
        for identifier, score in zip(corpus.identifiers, scores, strict=True):
            if identifier == exclude_identifier:
                continue
            is_exact = identifier in exact_ids
            value = 1.0 if is_exact else float(score)
            if is_exact or value >= threshold:
                matches.append(TextMatch(identifier=identifier, score=value, exact=is_exact))

        matches.sort(key=lambda item: (-item.score, item.identifier))
        return matches

    def size(self, ward: str) -> int:
        """Number of remarks held for a ward."""
        corpus = self._wards.get(ward)
        return len(corpus.documents) if corpus else 0


_index = DuplicationIndex()


def get_index() -> DuplicationIndex:
    """Return the process-wide index. Services invalidate it on new closures."""
    return _index
