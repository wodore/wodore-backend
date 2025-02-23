
WITH_DEV=0

DISTRO?=alpine
PORT?=8010
# development, production prod_development # django env
ENV?=development
REPO=wodore-backend

PKG_VERSION=$(shell grep '^version =' pyproject.toml | sed -E "s/version = \"([^\"]+)\"/\1/")
TAG?=$(PKG_VERSION)-$(DISTRO)
NEXT_TAG?=edge-$(DISTRO)

# limit memory and cpu during prod run
MEMORY?=512m
CPUS?=1
WORKERS?=3


DOCKERFILE=./docker/django/Dockerfile.$(DISTRO)
DOCKER_IMAGE=${REPO}:${TAG}
DOCKER_IMAGE_SLIM=${REPO}:${TAG}-slim
CONTAINER_NAME=wodore-api-container-${TAG}
DOCKER_CONTEXT=.    # Build context (current directory)
#SSH_SECRET=${HOME}/.ssh/id_ed25519

RUN_CMD=infisical run --env=dev --path /backend --silent --log-level warn --

INFISICAL_EXPORT := infisical export --env=dev --path /backend | sed "s/='\(.*\)'$/=\1/"

DJANGO_DATABASE_HOST=django-local-postgis


TARGET=production
RUN_WEBSERVER=gunicorn -b 0.0.0.0:$(PORT) -w $(WORKERS) --preload server.wsgi:application
#RUN_BUILD_ARGS=--no-cache
BUILD_ARGS?=

ORGANIZATION=wodore
REGISTRY=ghcr.io

NEXT_DOCKER_IMAGE=${REPO}:${NEXT_TAG}
NEXT_DOCKER_IMAGE_SLIM=${REPO}:${NEXT_TAG}-slim
runserver:
	${RUN_CMD} app runserver 8093

migrate:
	${RUN_CMD} app migrate

docker-show:
	@docker images | head -n 1
	@docker images | grep wodore-backend | grep "${TAG} " | head -n 1
	@echo "------------------------------------------------------------------------------------------------------------"
	@docker images | grep wodore-backend | head -n 10 | grep -v "${TAG} "

docker-compare:
	@docker images | head -n 1
	@docker images | grep wodore-backend | grep "${TAG} " | head -n 1
	@docker images | grep wodore-backend | grep "${TAG}-slim " | head -n 1
	@echo "------------------------------------------------------------------------------------------------------------"
	@docker images | grep wodore-backend | grep -v "${TAG} " | grep -v "${TAG}-slim " | head -n 10
# Default target
#--secret id=ssh_id_ed25519,src=$(SSH_SECRET)
#--secret id=env,src=.env.docker \
#--secret id=zitadel_api_key,src=.zitadel-api-key
_build:
	DOCKER_BUILDKIT=1
	docker buildx build --target $(TARGET) \
		--file $(DOCKERFILE) \
		--build-arg DJANGO_ENV=$(ENV) \
		--build-arg WITH_DEV=$(WITH_DEV) \
		--tag "$(DOCKER_IMAGE)" \
		--tag "$(NEXT_DOCKER_IMAGE)" \
		--tag "${REGISTRY}/${ORGANIZATION}/${DOCKER_IMAGE}" \
		--tag "${REGISTRY}/${ORGANIZATION}/${NEXT_DOCKER_IMAGE}" \
		--ssh default \
		--label org.opencontainers.image.description="Wodore backend based on ${DISTRO} (gdal) image" \
		${BUILD_ARGS} \
		$(DOCKER_CONTEXT)
	@echo "Build finished"

docker-build: _build docker-show

# --http-probe-apispec /v1/openapi.json
_slim:
	bash -c 'mint slim --target $(DOCKER_IMAGE) \
		--tag "$(DOCKER_IMAGE_SLIM)" \
		--tag "$(NEXT_DOCKER_IMAGE_SLIM)" \
		--tag "${REGISTRY}/${ORGANIZATION}/${DOCKER_IMAGE_SLIM}" \
		--tag "${REGISTRY}/${ORGANIZATION}/${NEXT_DOCKER_IMAGE_SLIM}" \
		--workdir "/code" \
		--expose $(PORT) \
		--env DJANGO_DATABASE_HOST=$(DJANGO_DATABASE_HOST) \
		--env-file <(./docker/django/get_env.sh --env dev) \
		--cmd "$(RUN_WEBSERVER)" \
		--publish-port $(PORT):$(PORT) \
		--label org.opencontainers.image.description="Wodore backend based on ${DISTRO} (gdal) image and slimmed down" \
		--network wodore-backend_postgresnet \
		--include-workdir \
		--http-probe-cmd "crawl:/v1/huts/huts.geojson?limit=5" \
		--http-probe-cmd "crawl:/v1/huts/bookings.geojson" \
		--http-probe-cmd "crawl:/" \
		--http-probe'

docker-slim: _slim docker-compare

docker-build-slim: _build _slim docker-compare

docker-clean:
	docker rmi $(DOCKER_IMAGE)

docker-clean-all:
	docker rmi -f $(shell docker images -q wodore-backend*); \
	docker builder prune -af --filter "label=wodore-backend"


# Default target: run in production mode
docker-run-prod:
	@echo "Starting ${DOCKER_IMAGE}"
	@echo "You can now access the server at http://localhost:$(PORT)"
	@mkdir -p .tmp/py_file_cache/joblib
	docker run --rm --name $(CONTAINER_NAME) \
		-e DJANGO_DATABASE_HOST=$(DJANGO_DATABASE_HOST) \
		-p $(PORT):$(PORT) \
		--network wodore-backend_postgresnet \
		--volume ./.tmp:/tmp/py_file_cache/joblib \
		--memory="$(MEMORY)" \
		--env-file <(./docker/django/get_env.sh --env prod) \
		--cpus="$(CPUS)" \
		$(DOCKER_IMAGE) \
		$(RUN_WEBSERVER)
	@rm -r .tmp


# Debug target: run the Django development server
# --name $(CONTAINER_NAME)
docker-run:
	@echo "Starting ${DOCKER_IMAGE}"
	@echo "You can now access the server at http://localhost:$(PORT)"
	@mkdir -p .tmp/py_file_cache/joblib
	@chmod -R 0777 .tmp
	bash -c 'docker run --rm \
		-p $(PORT):$(PORT) \
		-e DJANGO_DATABASE_HOST=$(DJANGO_DATABASE_HOST) \
		--network wodore-backend_postgresnet \
		--volume ./.tmp:/tmp/py_file_cache/joblib \
		--env-file <(./docker/django/get_env.sh --env dev) \
		$(DOCKER_IMAGE) \
		python -Wd manage.py runserver 0.0.0.0:$(PORT)'
	@rm -r .tmp

docker-run_ghcr:
	@echo "Starting ${DOCKER_IMAGE}"
	@echo "You can now access the server at http://localhost:$(PORT)"
	bash -c 'docker run --rm \
		-p $(PORT):$(PORT) \
		-e DJANGO_DATABASE_HOST=$(DJANGO_DATABASE_HOST) \
		--network wodore-backend_postgresnet \
		--env-file <(./docker/django/get_env.sh --env dev) \
		ghcr.io/wodore/$(DOCKER_IMAGE) \
		python -Wd manage.py runserver 0.0.0.0:$(PORT)'



debug_container:
	@CONTAINER_NAME=$(shell docker ps | grep wodore-backend | head -n 1 | awk '{print $$NF}'); \
	echo "Container name: $$CONTAINER_NAME"; \
	docker exec -it $$CONTAINER_NAME /bin/bash

docker-login:
	@echo "Loggin broken"
#@infisical run --env=dev --path /keys/wodore-backend --silent --log-level warn --  \
#	echo ${GITHUB_TOKEN} | docker login ghcr.io -u ${GITHUB_USERNAME} --password-stdin

docker-push: docker-build docker-login
	docker push ${REGISTRY}/${ORGANIZATION}/${DOCKER_IMAGE}
	docker push ${REGISTRY}/${ORGANIZATION}/${NEXT_DOCKER_IMAGE}

docker-push-alpine:
	DISTRO=alpine make docker-push

docker-push-ubuntu:
	DISTRO=ubuntu make docker-push

docker-push-slim: docker-build-slim docker-login
	docker push ${REGISTRY}/${ORGANIZATION}/${DOCKER_IMAGE_SLIM}
	docker push ${REGISTRY}/${ORGANIZATION}/${NEXT_DOCKER_IMAGE_SLIM}

docker-push-alpine-slim:
	DISTRO=alpine make docker-push-slim

docker-push-ubuntu-slim:
	DISTRO=ubuntu make docker-push-slim


# we do not push normal ubuntu
docker-push-all: docker-push-alpine docker-push-alpine-slim docker-push-ubuntu-slim
