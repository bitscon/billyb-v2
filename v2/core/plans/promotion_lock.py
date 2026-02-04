from datetime import datetime

class PromotionLock:
    """
    Blocks promotion unless a meaningful diff exists and approval is explicit.
    """

    def check(self, current_fp: str, previous_fp: str | None, diff: dict) -> dict:
        if previous_fp is None:
            return {
                "allowed": False,
                "reason": "No previous plan exists",
            }

        if current_fp == previous_fp:
            return {
                "allowed": False,
                "reason": "Identical plan fingerprint",
            }

        if not diff or not diff.get("diff"):
            return {
                "allowed": False,
                "reason": "No diff computed",
            }

        d = diff.get("diff", {})
        has_changes = any([
            d.get("added_steps"),
            d.get("removed_steps"),
            d.get("modified_steps"),
            d.get("artifact_changes"),
            d.get("risk_changes"),
        ])

        if not has_changes:
            return {
                "allowed": False,
                "reason": "No meaningful diff",
            }

        return {
            "allowed": True,
            "reason": "Diff present",
        }

    def metadata(self, from_fp: str, to_fp: str, diff_summary: str) -> dict:
        return {
            "from_fingerprint": from_fp,
            "to_fingerprint": to_fp,
            "diff_summary": diff_summary,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
