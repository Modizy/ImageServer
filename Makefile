.PHONY: aws clean jenkins

DOCKER_TAG := $(shell git rev-parse --short HEAD)
RELEASE_NAME := $(shell date +%Y%m%dT%H%M%S)

aws: Dockerrun.aws.json
	zip -vr $(DOCKER_TAG)-$(RELEASE_NAME).zip .ebextensions Dockerrun.aws.json

jenkins: aws env.properties

env.properties:
	echo "RELEASE_NAME = $(RELEASE_NAME)" > env.properties
	echo "DOCKER_TAG = $(DOCKER_TAG)" >> env.properties

Dockerrun.aws.json:
	sed -i "s/<DOCKER_NAME>/$(DOCKER_TAG)/" Dockerrun.aws.json
