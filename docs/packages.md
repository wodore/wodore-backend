## :simple-docker: Docker

[Docker images](https://github.com/wodore/wodore-backend/pkgs/container/wodore-backend) are created with the following tags:

- `latest`: latest stable version
- `major`, `major.minor` and `major.minor.rev` tags
- `edge`: unstable development version


=== "Docker Compose"
    It is recommended to use `docker compose`:

    ```yaml title="Example docker compose fil with two databases and a backup runner container"
    services:
      wodore-backend:
        image: ghcr.io/wodore/wodore-backend:latest
        restart: unless-stopped
        container_name: wodore-backend
    ```
    Run a custom command:

    ```bash
    $ docker compose up # start services
    $ docker compose run wodore-backend [OPTIONS] COMMAND [ARGS]... # (1)!
    ```

    1. Run `db-backup-runner` subcommands.

=== "Docker"
    It is also possible to run it with docker directly:

    ```bash title="Pull latest docker image"
    $ docker pull ghcr.io/wodore/wodore-backend:latest
    $ docker run --rm -it ghcr.io/wodore/wodore-backend:latest
    ```
