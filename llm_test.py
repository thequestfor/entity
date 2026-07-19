from agent.brain.llm import stream


for token in stream("Say hello in one sentence."):

    print(repr(token))