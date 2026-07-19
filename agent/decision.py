class Decision:

    def __init__(self):

        self.priority = 0
        self.action = None
        self.reason = None


    def evaluate(self, state, message):

        decision = Decision()

        if message:
            decision.priority = 1
            decision.action = "respond"
            decision.reason = "User requested interaction"

        return decision
