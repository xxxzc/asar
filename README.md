### ASAR: A HTTP Server to manage A few Rasa models

#### Features

- Supervisor's cli and ui to manage multiple rasa models
- Async HTTP API to update config and model
- Automatically train and replace model without affecting current service<sup>1</sup>

> 1 Replacing model takes some time, during which requests for that model will be waited but not be dropped

#### HTTP API

See http://localhost:5000/docs

#### Supervisor



#### Run

##### Docker

```shell
docker build . -t asar < Dockerfile
```

```shell
docker run -d -p 5000:5000 -p 9999:9999 -v $(pwd)/../data:/data -v $(pwd):/app asar
```

##### Local

```shell
pip install -r requirements.txt
```

```shell
supervisord
```

