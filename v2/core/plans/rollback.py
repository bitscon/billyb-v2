from v2.core.contracts.loader import ContractViolation


class RollbackEngine:
    """
    Deterministic rollback to a specific fingerprint.
    """

    def rollback(self, target_fingerprint: str, history) -> dict:
        if not target_fingerprint:
            raise ContractViolation("Missing rollback fingerprint")

        if not history.exists(target_fingerprint):
            raise ContractViolation("Target plan fingerprint not found or invalid")

        active_fp = history.get_active()
        if active_fp == target_fingerprint:
            raise ContractViolation("Target plan is already active")

        if active_fp:
            history.mark_rolled_back(active_fp)

        history.set_active(target_fingerprint)
        history.record_rollback(active_fp, target_fingerprint)

        return {
            "rollback": {
                "status": "complete",
                "active_fingerprint": target_fingerprint,
            }
        }
