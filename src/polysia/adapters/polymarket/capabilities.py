from polysia.domain.market import Venue, VenueCapabilityProfile

POLYMARKET = Venue(id="polymarket", display_name="Polymarket")

POLYMARKET_CAPABILITIES = VenueCapabilityProfile(
    venue=POLYMARKET,
    supported_order_types=("LIMIT", "MARKET", "FAK", "FOK", "POST_ONLY"),
    supports_market_data_stream=True,
    supports_authenticated_reads=True,
    supports_order_cancellation=True,
    supports_live_execution=True,
    requires_geoblock_check=True,
    metadata={
        "sdk_distribution": "polymarket-client",
        "sdk_import": "polymarket",
        "wallet_model": "signer_and_funder",
    },
)

