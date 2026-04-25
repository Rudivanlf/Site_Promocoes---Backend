from django.urls import path
from .views import chat, list_providers

urlpatterns = [
    path("chat/", chat, name="agent-chat"),
    path("providers/", list_providers, name="agent-providers"),
]
