from __future__ import annotations

from typing import Protocol

from polysia.domain.wallet_intelligence.research_intake import ResearchWalletPublication


class ResearchPublicationError(ValueError):
    """Safe contract failure; never embed protected source text in an error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ResearchWalletSourcePort(Protocol):
    """One validated publication, including empty and partial scope."""

    def read_publication(self) -> ResearchWalletPublication: ...
