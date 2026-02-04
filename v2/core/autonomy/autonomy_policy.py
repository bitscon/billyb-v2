class AutonomyPolicy:
    """
    Declarative autonomy policy definition.
    """

    def __init__(self, policy: dict):
        self.policy = policy

    def to_dict(self) -> dict:
        return self.policy
