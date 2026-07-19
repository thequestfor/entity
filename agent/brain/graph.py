from langgraph.graph import StateGraph, END

from agent.state import EntityState
from agent.brain.nodes import think_node


graph = StateGraph(EntityState)


graph.add_node(
    "think",
    think_node
)


graph.set_entry_point(
    "think"
)


graph.add_edge(
    "think",
    END
)


entity_brain = graph.compile()