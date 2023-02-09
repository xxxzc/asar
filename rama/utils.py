from pathlib import Path

from sanic.response import json as json_resp
import orjson

from ruamel.yaml import YAML


def dict_deepcopy(o):
    return orjson.loads(orjson.dumps(o))


yaml = YAML(typ='safe')


def yaml_load(path):
    with open(path, "r") as f:
        return yaml.load(f)


def yaml_dump(data, path):
    with open(path, "w") as f:
        return yaml.dump(data, path)


class Result(dict):
    """Result to return

    {
        "text": "ret_code",
        "custom": {
            "success": true,
            "msg": "explain text ret_code",
            "data": [],
            **kwargs
        }
    }

    it will do a deepcopy for item that add to custom
    """

    def __init__(self, text="utter_default", success=True, msg="Rasa fallback", **kwargs):
        super().__init__()
        self.text = text or "unknown"
        self['custom'] = {"data": []}
        self.custom(success=success, msg=msg, **kwargs)

    @classmethod
    def from_dict(cls, d: dict):
        """Deepcopy dict and convert to Result"""
        return cls(text=d.get("text", ""), **d.get("custom", {}))

    def deepcopy(self):
        """Deepcopy Result"""
        return Result.from_dict(self)

    """text"""

    @property
    def text(self) -> str:
        return self['text']

    def set_text(self, text):
        self['text'] = str(text)
        return self

    @text.setter
    def text(self, text):
        self.set_text(text)

    def custom(self, **kwargs):
        """Update kwargs to custom, kwargs will be deepcopyed"""
        self["custom"].update(dict_deepcopy(kwargs))
        return self

    """custom:success
    
    why success does not have setter:
    success itself is meaningless, need text and msg to explain it
    """

    def is_success(self):
        return self['custom']['success']

    def set_success(self, text, msg, success=True):
        self.text = text
        return self.custom(success=success, msg=msg)

    def set_failure(self, text, msg):
        return self.set_success(text, msg, False)

    """custom:data"""

    @property
    def data(self) -> list[dict]:
        return self['custom']['data']

    def append(self, item: dict):
        """Add item to data"""
        self.data.append(item)
        return self

    def as_dict(self):
        return dict_deepcopy(self)

    @property
    def resp(self):
        return json_resp(self)

    @classmethod
    def to_yaml(cls, representer, data):
        return representer.represent_dict(data)


yaml.register_class(Result)


if __name__ == '__main__':
    result = Result()
