from django.urls import path

from .views import BuscarProdutosKabumView


urlpatterns = [
    path("", BuscarProdutosKabumView.as_view(), name="scraper-kabum"),
]
