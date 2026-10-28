"""Default-disabled administrative account-read entry point; no SDK imports."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from polysia.deployment.financial_session_runtime import SessionRuntimeConfig
from polysia.domain.financial_session import InstrumentScope
from polysia.storage.acquisition_authority import AcquisitionAuthority


async def qualify_account(
    config: SessionRuntimeConfig,
    instruments: tuple[InstrumentScope, ...],
    acquisition: AcquisitionAuthority,
    *,
    read_account: bool,
    clock: Callable[[], datetime],
) -> dict[str, Any]:
    if not read_account:
        return {"status": "DISABLED", "account_read": "NOT_PERFORMED", "network": "NOT_CONSTRUCTED"}
    from polysia.adapters.polymarket.session_account_qualification import qualify_account as read

    return await read(config, instruments, acquisition, read_account=True, clock=clock)
