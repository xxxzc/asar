from sanic import Sanic, response, Request, HTTPResponse
from sanic.response import json as json_resp
from node import Node

app: Sanic = Sanic("rama")

nodes: dict[str, Node] = {}

@app.get("init/<name:str>")
async def init(r: Request, name: str) -> HTTPResponse:
    node = nodes.get(name, None)
    if node is None:
        node = nodes[name] = Node(name)
    return json_resp({
        "path": node.root.as_posix()
    })


app.run(host="0.0.0.0", port=5000, debug=True)
