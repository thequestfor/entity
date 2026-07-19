class Attention:

    def __init__(self):

        self.threshold = 5


    def should_interrupt(self, event):

        if event.priority >= self.threshold:
            return True

        return False
