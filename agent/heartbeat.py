import time


class Heartbeat:

    def __init__(self, entity):

        self.entity = entity
        self.running = False


    def start(self):

        print("Entity heartbeat started.")

        self.running = True

        while self.running:

            self.tick()

            time.sleep(10)


    def tick(self):

        print("Heartbeat check...")

        decision = self.entity.observe()
        event = self.entity.observe()
        
        if event:
        
            if self.entity.attention.should_interrupt(event):
        
                self.entity.act(event)
        
            else:
        
                print(
                    "Event ignored:",
                    event.message
                )
