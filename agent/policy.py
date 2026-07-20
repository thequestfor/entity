class Policy:
    def __init__(self):
        self.auto_allowed_actions = {
            "diagnostics",
            "notify",
            "speak",
            "record_memory"
        }

    def allows(self, action):
        if action.requires_confirmation:
            return False

        return action.type in self.auto_allowed_actions
