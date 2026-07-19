from agent.state import EntityState


state = EntityState()


print(state.describe())


state.set_mode("focus")

state.set_activity(
    "Ben is studying"
)

state.set_priority(5)


print(state.describe())