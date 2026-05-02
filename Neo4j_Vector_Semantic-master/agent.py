from langgraph.graph import StateGraph, END
from typing import TypedDict
from langchain_google_genai import ChatGoogleGenerativeAI
import os
from memory import Memory

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-pro",
    google_api_key=os.getenv("GOOGLE_API_KEY"),
    temperature=0.3
)

memory = Memory()

class State(TypedDict):
    user_id: str
    input: str
    context: str
    output: str

def recall(state):

    ctx = memory.recall(state["user_id"], state["input"])
    return {"context": ctx}

def reason(state):

    prompt = f"""
Relevant past:
{state['context']}

User:
{state['input']}
"""

    out = llm.invoke(prompt).content
    return {"output": out}

def persist(state):

    memory.save(
        state["user_id"],
        state["input"],
        state["output"]
    )

    return state

builder = StateGraph(State)

builder.add_node("recall", recall)
builder.add_node("reason", reason)
builder.add_node("persist", persist)

builder.set_entry_point("recall")
builder.add_edge("recall", "reason")
builder.add_edge("reason", "persist")
builder.add_edge("persist", END)

graph = builder.compile()
