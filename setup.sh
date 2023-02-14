docker rm -f asar
docker rmi -f asar
docker build . -t asar
docker run -d -p 5000:5000 -p 9999:9999 -v ~/data:/data -v $(pwd):/app --name asar asar
docker logs -f --tail 1000 asar