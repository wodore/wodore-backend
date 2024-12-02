import base64
import datetime
from typing import Any

import requests

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

# https://github.com/zitadel/example-quote-generator-app/tree/main/backend


class Command(BaseCommand):
    help = "Get acces token for user ..."

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.suppressed_base_arguments = {
            "--version",
            "--settings",
            "--pythonpath",
            "--traceback",
            "--no-color",
            "--force-color",
        }
        self.requires_system_checks = []  # type: ignore pyright

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("-t", "--token-url", help="Token endpoint", default=settings.OIDC_OP_TOKEN_ENDPOINT)
        parser.add_argument("-p", "--project-id", help="Zitadel project ID", default=settings.ZITADEL_PROJECT)
        parser.add_argument("-u", "--user", help="Zitadel user", default="api-tester")
        parser.add_argument("-l", "--list-users", help="List available users", action="store_true")

    def handle(
        self,
        token_url: str,
        project_id: str,
        user: str,
        list_users: bool,
        verbosity: int,
        *args: Any,
        **options: Any,
    ) -> None:
        user_secrets = settings.ZITADEL_API_MACHINE_USERS
        if list_users:
            for u in user_secrets:
                print(u)
            return
        if user in user_secrets and user_secrets:
            client_secret = user_secrets[user]
        else:
            self.stdout.write(self.style.ERROR(f"user '{user}' not in 'settings.oidc.ZITADEL_API_MACHINE_USERS'."))
            return

        # Encode the client ID and client secret in Base64
        client_credentials = f"{user}:{client_secret}".encode()
        base64_client_credentials = base64.b64encode(client_credentials).decode("utf-8")

        # Request an OAuth token from ZITADEL
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {base64_client_credentials}",
        }

        data = {
            "grant_type": "client_credentials",
            "scope": f"openid profile email urn:zitadel:iam:org:project:id:{project_id}:aud",
        }

        response = requests.post(token_url, headers=headers, data=data)

        if response.status_code == 200:
            resp = response.json()
            access_token = resp["access_token"]
            token_type = resp["token_type"].lower()
            expires_in = resp["expires_in"]
            expires_date = datetime.datetime.now() + datetime.timedelta(seconds=expires_in)
            if verbosity > 1:
                self.stdout.write(self.style.NOTICE("Server response:"))
                self.stdout.write(self.style.HTTP_INFO(resp))
            if verbosity > 0:
                self.stdout.write(
                    self.style.NOTICE(
                        f"Access {token_type} token for user '{user}' (valid until {expires_date:%d.%m.%y %H:%M}):"
                    )
                )
                self.stdout.write(self.style.SUCCESS(access_token))
            else:
                print(access_token)
        else:
            self.stdout.write(self.style.ERROR(f"error: {response.status_code} - {response.text}"))
