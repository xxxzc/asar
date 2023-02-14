### ASAR: A HTTP Server to Arrange Rasa models

#### FEATURES

- Supervisor's cli and ui to manage multiple rasa models
- Async HTTP API to update config and model
- Automatically train and replace model without affecting current service<sup>1</sup>

> 1 Replacing model takes some time, during which requests for that model will be waited but not be dropped

#### RUN

##### Docker

```shell
docker build . -t asar
```

```shell
docker run -d -p 5000:5000 -p 9999:9999 -v $(pwd)/../data:/data -v $(pwd):/app --name asar asar
```

##### Local(Not Recommended)

Install the required modules listed in Dockerfile, and run `supervisord`.

#### HTTP API

http://localhost:5000/docs

#### Supervisor

http://localhost:9999

