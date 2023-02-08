"""
HTTP Server for Multi Rasa Node(Instance)

GET node - all node info
GET node/<name> - certain node info
POST node/<name> - redirect to Rasa HTTP API of Node
~~PUT node/<name> - init node~~
PATCH node/<name> - update node
"""

from typing import Type
from pathlib import Path

from sanic import Sanic, response, Request, HTTPResponse
from sanic.response import json as json_resp
from sanic.views import HTTPMethodView
from subprocess import check_output, STDOUT

svctl = "supervisorctl"

def sh(*args):
    return check_output(args, stderr=STDOUT).decode("utf-8")


ROOT = Path(__file__).parent
DATA_DIR = ROOT.parent / 'data'
NODE_DIR = DATA_DIR / 'node'

app: Sanic = Sanic("rama")


def Node(path: Path) -> HTTPMethodView:
    """Node
    """

    class _Node(HTTPMethodView):
        def __init__(self) -> None:
            self.name = path.name    
            self.path = path        
            super().__init__()

        
        async def get(self, r: Request) -> HTTPResponse:
            """Get node info"""
            msg = sh(svctl, "status", "app")
            return json_resp({"name": self.name, "msg": msg})


        async def patch(self, r: Request) -> HTTPResponse:
            """Update Node Data"""
            j: dict = r.json or {}
            for key, value in j.items():
                pass
            return json_resp({})


    return _Node()


NODES = {}


def create_route():
    for path in NODE_DIR.iterdir():
        name = path.name
        node = Node(path)
        NODES[name] = node
        app.add_route(node.as_view(), f"/node/{name}")


create_route()


@app.get("/node")
async def node_info(r: Request) -> HTTPResponse:
    return json_resp({
        "nodes": list(NODES.keys())
    })


app.run(host="0.0.0.0", port=5000, debug=True)
