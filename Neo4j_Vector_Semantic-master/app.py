from agent import graph
from identity import Identity

user_id = Identity.get_user()

print("Semantic Agent Ready")

while True:

    msg = input("\nYou: ")

    if msg == "exit":
        break

    res = graph.invoke({
        "user_id": user_id,
        "input": msg,
        "context": "",
        "output": ""
    })

    print("\nAI:", res["output"])
