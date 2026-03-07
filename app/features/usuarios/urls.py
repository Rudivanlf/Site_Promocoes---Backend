# usuarios/urls.py

from django.urls import path
from .views import LoginView, RegistroView, UsuariosListView, UsuariosDetailView

urlpatterns = [
    path("login/", LoginView.as_view(), name="usuarios-login"),
    # Aliases de cadastro para compatibilidade com o frontend
    path("registro/", RegistroView.as_view(), name="usuarios-registro"),
    path("cadastro/", RegistroView.as_view(), name="usuarios-cadastro"),
    path("register/", RegistroView.as_view(), name="usuarios-register"),
    path("", UsuariosListView.as_view(), name="usuarios-list"),
    path("<int:usuario_id>/", UsuariosDetailView.as_view(), name="usuarios-detail"),
]
