### ASAR: A HTTP Server to Arrange Rasa models

#### Features

- [Supervisor](http://supervisord.org/) cli and ui to manage multiple rasa models
- Async HTTP API to put file and update model
- Train and replace model without affecting current service<sup>1</sup>

> 1 Replacing model takes some time, during which requests for that model will be waited but not be dropped

#### RUN

##### Docker

```shell
docker build . -t asar
```

```shell
docker run -d -p 5000:5000 -v ~/data:/data -v $(pwd):/app --name asar asar
```

- 5000: This server
- 9999: Supervisor
- /data: store model files in /data/model/<name>/
- /app: auto reload code

```shell
docker logs -f --tail 1000 asar # server log, not supervisor log
```

##### Local(Not Recommended)

install rasa and the required modules listed in Dockerfile, then run `supervisord`

#### HTTP API

Just see app.py, or http://localhost:5000/docs

- GET /model/name get model info
- POST /model/name communicate to Rasa HTTP API
- PUT /model/name put files and update model
- GET /supervisor supervisor ui

#### Supervisor

http://localhost:5000/supervisor

#### Claims

I'm not good at async, state, docker, supervisor, etc. 

If you have any suggestion, please let me know.

