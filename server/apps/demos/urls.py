from django.urls import path

from server.apps.demos.views import mapcompare

app_name = "demos"

urlpatterns = [
    path("mapcompare/", mapcompare, name="mapcompare"),
]
