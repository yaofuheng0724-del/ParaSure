from __future__ import annotations

from .models import MatchCandidate, ProductParameter, TenderRequirement
from .text import text_score


class ParameterRetriever:
    def __init__(self, parameters: list[ProductParameter]):
        self.parameters = parameters

    def search(self, requirement: TenderRequirement, limit: int = 5) -> list[MatchCandidate]:
        scored: list[MatchCandidate] = []
        query = requirement.text
        for parameter in self.parameters:
            score, terms = text_score(query, parameter.evidence_text)
            if score <= 0:
                continue
            scored.append(MatchCandidate(parameter=parameter, score=score, matched_terms=terms))
        scored.sort(key=lambda candidate: candidate.score, reverse=True)
        return scored[:limit]
