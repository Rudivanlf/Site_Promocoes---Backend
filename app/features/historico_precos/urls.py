from django.urls import path
from .views import PriceHistoryView

urlpatterns = [
    path("historico/", PriceHistoryView.as_view(), name="price-history"),
]