### ASAR: A HTTP Server to Arrange Rasa models

#### FEATURES

- Supervisor's cli and ui to manage multiple rasa models
- Async HTTP API to update config and model
- Train and replace model without affecting current service<sup>1</sup>

> 1 Replacing model takes some time, during which requests for that model will be waited but not be dropped

#### RUN

##### Docker

```shell
docker build . -t asar
```

```shell
docker run -d -p 5000:5000 -p 9999:9999 -v $(pwd)/../data:/data -v $(pwd):/app --name asar asar
```

- 5000: This Server
- 9999: Supervisor
- /data: store model files
- /app: auto reload code

```shell
docker logs -f --tail 1000 asar # service log, not supervisor log
```

##### Local(Not Recommended)

install rasa and the required modules listed in Dockerfile, then run `supervisord`

#### HTTP API

http://localhost:5000/docs

#### Supervisor

http://localhost:9999

