from django.urls import path
from .views import BuscarProdutosMercadoLivreView

urlpatterns = [
    path("", BuscarProdutosMercadoLivreView.as_view(), name="scraper-mercadolivre"),
]
