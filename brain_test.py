from agent.brain.graph import entity_brain


result = entity_brain.invoke(
    {
        "user_input": "Hello Entity. Who are you?",

        "response": "",

        "action": "",

        "priority": 0,

        "mode": "normal",

        "activity": None,

        "user_present": True
    }
)


print(result["response"])