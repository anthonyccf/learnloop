"""Deterministic lexical candidate retrieval for Expert concept review.

Retrieval suggests possible matches only. It must not be used as evidence that
two concepts are equivalent, or that an unreturned concept is different.
"""

import math
import re
from collections import Counter, defaultdict


def _tokens(concept):
    text = f"{concept.get('title', '')} {concept.get('summary', '')}".casefold()
    return Counter(token for token in re.findall(r"[^\W_]+", text) if len(token) > 1)


class ConceptCandidateIndex:
    """In-memory inverted index with stable ranking and bounded results."""

    def __init__(self, concepts):
        self._concepts = {concept["id"]: concept for concept in concepts}
        if len(self._concepts) != len(concepts):
            raise ValueError("Concept IDs must be unique")
        self._postings = defaultdict(dict)
        for concept_id, concept in self._concepts.items():
            for token, count in _tokens(concept).items():
                self._postings[token][concept_id] = count

    def search(self, candidate, limit=24):
        if limit < 1:
            return []
        scores = defaultdict(float)
        total = len(self._concepts)
        for token, query_count in _tokens(candidate).items():
            posting = self._postings.get(token, {})
            weight = math.log((total + 1) / (len(posting) + 1)) + 1
            for concept_id, count in posting.items():
                if concept_id != candidate.get("id"):
                    scores[concept_id] += weight * min(query_count, count)
        ranked = sorted(scores, key=lambda concept_id: (-scores[concept_id], concept_id))
        return [self._concepts[concept_id] for concept_id in ranked[:limit]]
