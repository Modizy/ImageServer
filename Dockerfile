## Iceberg API Dockerfile
FROM ubuntu:precise
MAINTAINER Quentin P <quentin@izberg-marketplace.com>

RUN apt-get update
RUN apt-get install -y --force-yes build-essential git python python-dev python-setuptools supervisor libxslt-dev libxml2-dev libjpeg-dev libpng-dev make swig bash
RUN add-apt-repository -y ppa:nginx/stable; apt-get install -y nginx


RUN easy_install pip

# add the code
ADD . /home/docker/code/

WORKDIR /home/docker/code/

# nginx confs
RUN cp /home/docker/code/nginx_conf/nginx.conf /etc/nginx/nginx.conf;
RUN ln -s /home/docker/code/nginx_conf/ImageResizingServerApp.active /etc/nginx/sites-enabled/;

# install requirements
RUN pip install -r /home/docker/code/requirements.txt

EXPOSE 8000
CMD ["./docker_conf/launch_script.sh"]