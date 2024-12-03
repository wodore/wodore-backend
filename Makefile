
WITH_DEV=0

TARGET=production
DOCKERFILE=./docker/django/Dockerfile
DOCKER_TAG?=${DJANGO_ENV}
DOCKER_IMAGE=wodore-backend:${DOCKER_TAG}
CONTAINER_NAME=wodore-api-container-${DOCKER_TAG}
DOCKER_CONTEXT=.    # Build context (current directory)
#SSH_SECRET=${HOME}/.ssh/id_ed25519
RUN_CMD=infisical run --env=dev --path /backend --silent --log-level warn --
DJANGO_DATABASE_HOST=django-local-postgis

DEFAULT_PORT=8010
# Port argument (override with `PORT=XXXX`)
PORT?=$(DEFAULT_PORT)

RUN_WEBSERVER=gunicorn -b 0.0.0.0:$(PORT) -w 3 --preload server.wsgi:application
#RUN_BUILD_ARGS=--no-cache
BUILD_ARGS?=
DJANGO_ENV?=development

# Default target
#--secret id=ssh_id_ed25519,src=$(SSH_SECRET) 
build:
	DOCKER_BUILDKIT=1
	infisical secrets get --env dev --path /backend ZITADEL_API_PRIVATE_KEY_JSON --plain > .zitadel-api-key
	${RUN_CMD} docker buildx build --target $(TARGET) \
		--file $(DOCKERFILE) \
		--build-arg DJANGO_ENV=$(DJANGO_ENV) \
		--build-arg WITH_DEV=$(WITH_DEV) \
   	--secret id=zitadel_api_key,src=.zitadel-api-key \
		-t $(DOCKER_IMAGE) \
		--ssh default \
		${BUILD_ARGS} \
		$(DOCKER_CONTEXT)
	rm .zitadel-api-key
	@echo "Build finished:"
	@docker images | head -n 1
	@docker images | grep wodore-backend | grep ${DJANGO_ENV} | head -n 1

#--ssh default \
# TODO
slim:
	slim build --dockerfile $(DOCKERFILE)

clean:
	docker rmi $(DOCKER_IMAGE)

clean_all:
	docker rmi $(shell docker images -q wodore-backend*); \
	docker builder prune -af --filter "label=wodore-backend"


# Default target: run in production mode
run_prod:
	@echo "You can now access the server at http://localhost:$(PORT)"
	docker run --rm --name $(CONTAINER_NAME) \
		-e DJANGO_DATABASE_HOST=$(DJANGO_DATABASE_HOST) \
		-p $(PORT):$(PORT) \
		--network wodore-backend_postgresnet \
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
