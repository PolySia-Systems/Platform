import os

from polysia.adapters.polymarket.secure import (
    FUNDER_ADDRESS_ENV,
    PRIVATE_KEY_ENV,
    SIGNATURE_TYPE_ENV,
    WALLET_ADDRESS_ENV,
)
from polysia.config.settings import AppSettings


def apply_secure_env_from_settings(settings: AppSettings) -> None:
    if os.environ.get(PRIVATE_KEY_ENV) is None and settings.polymarket_private_key is not None:
        os.environ[PRIVATE_KEY_ENV] = settings.polymarket_private_key.get_secret_value()
    if os.environ.get(FUNDER_ADDRESS_ENV) is None and settings.polymarket_funder_address:
        os.environ[FUNDER_ADDRESS_ENV] = settings.polymarket_funder_address
    if os.environ.get(WALLET_ADDRESS_ENV) is None and settings.polymarket_wallet_address:
        os.environ[WALLET_ADDRESS_ENV] = settings.polymarket_wallet_address
    if (
        os.environ.get(SIGNATURE_TYPE_ENV) is None
        and settings.polymarket_signature_type is not None
    ):
        os.environ[SIGNATURE_TYPE_ENV] = str(settings.polymarket_signature_type)
