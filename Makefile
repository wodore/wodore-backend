
WITH_DEV=0

DISTRO?=alpine
PORT?=8010
# development, production prod_development # django env
ENV?=development
TAG?=$(ENV)-$(DISTRO)

# limit memory and cpu during prod run
MEMORY?=512m
CPUS?=1
WORKERS?=3

DOCKERFILE=./docker/django/Dockerfile.$(DISTRO)
DOCKER_IMAGE=wodore-backend:${TAG}
CONTAINER_NAME=wodore-api-container-${TAG}
DOCKER_CONTEXT=.    # Build context (current directory)
#SSH_SECRET=${HOME}/.ssh/id_ed25519
RUN_CMD=infisical run --env=dev --path /backend --silent --log-level warn --
DJANGO_DATABASE_HOST=django-local-postgis


TARGET=production
RUN_WEBSERVER=gunicorn -b 0.0.0.0:$(PORT) -w $(WORKERS) --preload server.wsgi:application
#RUN_BUILD_ARGS=--no-cache
BUILD_ARGS?=

show:
	@docker images | head -n 1
	@docker images | grep wodore-backend | grep "${TAG} " | head -n 1
	@echo "------------------------------------------------------------------------------------------------------------"
	@docker images | grep wodore-backend | head -n 10 | grep -v "${TAG} "

compare:
	@docker images | head -n 1
	@docker images | grep wodore-backend | grep "${TAG} " | head -n 1
	@docker images | grep wodore-backend | grep "${TAG}-slim " | head -n 1
	@echo "------------------------------------------------------------------------------------------------------------"
	@docker images | grep wodore-backend | grep -v "${TAG} " | grep -v "${TAG}-slim " | head -n 10 
# Default target
#--secret id=ssh_id_ed25519,src=$(SSH_SECRET) 
_build:
	DOCKER_BUILDKIT=1
	infisical secrets get --env dev --path /backend ZITADEL_API_PRIVATE_KEY_JSON --plain > .zitadel-api-key
	${RUN_CMD} docker buildx build --target $(TARGET) \
		--file $(DOCKERFILE) \
		--build-arg DJANGO_ENV=$(ENV) \
		--build-arg WITH_DEV=$(WITH_DEV) \
		--secret id=zitadel_api_key,src=.zitadel-api-key \
		-t "$(DOCKER_IMAGE)" \
		--ssh default \
		${BUILD_ARGS} \
		$(DOCKER_CONTEXT)
	rm .zitadel-api-key
	@echo "Build finished"

build: _build show

# --http-probe-apispec /v1/openapi.json 
_slim:
	mint slim --target $(DOCKER_IMAGE) \
		--tag "$(DOCKER_IMAGE)-slim" \
		--workdir "/code" \
		--expose $(PORT) \
		--env DJANGO_DATABASE_HOST=$(DJANGO_DATABASE_HOST) \
		--cmd "$(RUN_WEBSERVER)" \
		--publish-port $(PORT):$(PORT) \
		--network wodore-backend_postgresnet \
		--include-workdir \
		--http-probe-cmd "crawl:/v1/huts/huts.geojson?limit=5" \
		--http-probe-cmd "crawl:/v1/huts/bookings.geojson" \
		--http-probe-cmd "crawl:/" \
		--http-probe

slim: _slim compare
	
build_slim: _build _slim compare	

clean:
	docker rmi $(DOCKER_IMAGE)

clean_all:
	docker rmi -f $(shell docker images -q wodore-backend*); \
	docker builder prune -af --filter "label=wodore-backend"


# Default target: run in production mode
run_prod:
	@echo "Starting ${DOCKER_IMAGE}"
	@echo "You can now access the server at http://localhost:$(PORT)"
	docker run --rm --name $(CONTAINER_NAME) \
		-e DJANGO_DATABASE_HOST=$(DJANGO_DATABASE_HOST) \
		-p $(PORT):$(PORT) \
		--network wodore-backend_postgresnet \
		--memory="$(MEMORY)" \
		--cpus="$(CPUS)" \
		$(DOCKER_IMAGE) \
		$(RUN_WEBSERVER)


# Debug target: run the Django development server
# --name $(CONTAINER_NAME) 
run:
	@echo "You can now access the server at http://localhost:$(PORT)"
	docker run --rm \
		-p $(PORT):$(PORT) \
		-e DJANGO_DATABASE_HOST=$(DJANGO_DATABASE_HOST) \
		--network wodore-backend_postgresnet \
		$(DOCKER_IMAGE) \
		python -Wd manage.py runserver 0.0.0.0:$(PORT)


debug_container:
	@CONTAINER_NAME=$(shell docker ps | grep wodore-backend | head -n 1 | awk '{print $$NF}'); \
	echo "Container name: $$CONTAINER_NAME"; \
	docker exec -it $$CONTAINER_NAME /bin/bash
