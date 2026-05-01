from django.urls import path
from .views import chat, list_providers, recommend

urlpatterns = [
    path("chat/", chat, name="agent-chat"),
    path("providers/", list_providers, name="agent-providers"),
    path("recommend/", recommend, name="agent-recommend"),
]
