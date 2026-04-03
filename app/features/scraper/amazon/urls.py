from django.urls import path

from .views import BuscarProdutosAmazonView


urlpatterns = [
    path("", BuscarProdutosAmazonView.as_view(), name="scraper-amazon"),
]
