# favoritos/urls.py

from django.urls import path
from .views import FavoritoView

urlpatterns = [
    path("", FavoritoView.as_view(), name="favoritos"),
]
