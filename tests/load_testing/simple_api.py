import time
from locust import HttpUser, task, between
import random


def get_lang() -> str:
    langs = ("de", "fr", "en", "it")
    return random.choice(langs)


def get_bool() -> str:
    bools = ("true", "false")
    return random.choice(bools)


def get_includes(fields: list[str]) -> str:
    if random.randint(0, 10) > 5:
        return ",".join(random.choices(fields, k=random.randint(1, len(fields))))
    return "__all__"


class QuickstartUser(HttpUser):
    wait_time = between(1, 5)

    @task(4)
    def get_huts(self):
        lang = get_lang()
        limit = random.randint(4, 8)
        offset = random.randint(0, 10)
        embed_all = get_bool()
        flat = get_bool()
        path = "/v1/huts/huts.geojson"
        url = f"{path}?lang={lang}&offset={offset}&limit={limit}&embed_all={embed_all}&flat={flat}"
        self.client.get(url, name=f"{path}?limit={limit}")

    @task(2)
    def get_hut_types_records(self):
        lang = get_lang()
        path = "/v1/huts/types/records"
        fields = ["slug", "name", "description", "symbol", "level", "symbol_simple", "icon"]
        include = get_includes(fields)
        url = f"{path}?lang={lang}&include={include}"
        self.client.get(url, name=path)

    @task
    def get_orgs(self):
        lang = get_lang()
        path = "/v1/organizations"
        url = f"{path}?lang={lang}"
        self.client.get(url, name=path)

    # @task(3)
    # def view_items(self):
    #    for item_id in range(10):
    #        self.client.get(f"/item?id={item_id}", name="/item")
    #        time.sleep(1)
