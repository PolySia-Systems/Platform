"""Read-only fictional dataset rendered by the sole Console presentation."""


def publication() -> dict:
    return {
        "version": "console-example/v1",
        "dataset_role": "SYNTHETIC",
        "status": "OFFLINE_EXAMPLE",
        "next_action": "Return to retained evidence for installation status.",
        "diagnostic": {
            "discovery": {
                "candidates": [
                    {
                        "wallet_id": "example-wallet-a",
                        "state": "FICTIONAL_EXAMPLE",
                        "sources": ["synthetic"],
                        "execution_eligibility": "NOT_AUTHORIZED",
                        "exclusions": ["fictional_evidence"],
                    },
                    {
                        "wallet_id": "example-wallet-b",
                        "state": "FICTIONAL_EXAMPLE",
                        "sources": ["synthetic"],
                        "execution_eligibility": "INSUFFICIENT_EVIDENCE",
                        "exclusions": ["fictional_evidence"],
                    },
                ]
            }
        },
        "alerts": ["Synthetic example; no execution, readiness or financial evidence."],
    }
