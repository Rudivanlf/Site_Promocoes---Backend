# usuarios/views.py

"""
Views para o módulo de usuários.
Contém endpoints para cadastro, login e operações CRUD.
"""

import jwt
import datetime

from django.conf import settings
from django.http import JsonResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .models import validate_usuario_data, validate_login_data
from .services import UsuarioService
from ..utils import parse_request_body


# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")
class RegistroView(View):
    """POST /api/usuarios/registro/ — Cria uma nova conta."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = UsuarioService()

    def post(self, request):
        data, error = parse_request_body(request)
        if error:
            return JsonResponse({"success": False, "error": error}, status=400)

        # Normaliza nomes de campo vindos do frontend
        data = _normalizar_campos(data)

        is_valid, errors = validate_usuario_data(data)
        if not is_valid:
            return JsonResponse({"success": False, "errors": errors}, status=400)

        try:
            usuario = self.service.criar_usuario(data)
        except ValueError as e:
            return JsonResponse({"success": False, "error": str(e)}, status=409)
        except Exception as e:
            return JsonResponse(
                {"success": False, "error": f"Erro ao criar usuário: {str(e)}"},
                status=500,
            )

        token = _gerar_token(usuario)
        return JsonResponse(
            {
                "success": True,
                "message": "Usuário criado com sucesso",
                "token": token,
                "usuario": usuario,
            },
            status=201,
        )


@method_decorator(csrf_exempt, name="dispatch")
class LoginView(View):
    """POST /api/usuarios/login/ — Autentica e retorna um JWT."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = UsuarioService()

    def post(self, request):
        data, error = parse_request_body(request)
        if error:
            return JsonResponse({"success": False, "error": error}, status=400)

        # Normaliza nomes de campo vindos do frontend
        data = _normalizar_campos(data)

        is_valid, errors = validate_login_data(data)
        if not is_valid:
            return JsonResponse({"success": False, "errors": errors}, status=400)

        usuario = self.service.autenticar_usuario(
            email=data["email"],
            senha=data["senha"],
        )

        # Mensagem genérica para não revelar se o email existe ou não
        if not usuario:
            return JsonResponse(
                {"success": False, "error": "Email ou senha inválidos"},
                status=401,
            )

        token = _gerar_token(usuario)
        return JsonResponse(
            {
                "success": True,
                "message": "Login realizado com sucesso",
                "token": token,
                "usuario": usuario,
            }
        )


# ---------------------------------------------------------------------------
# CRUD de usuários
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")
class UsuariosListView(View):
    """GET /api/usuarios/ — Lista usuários | POST — Cria usuário (alias de registro)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = UsuarioService()

    def get(self, request):
        try:
            limit = min(int(request.GET.get("limit", 50)), 100)
            skip = int(request.GET.get("skip", 0))
        except ValueError:
            return JsonResponse(
                {"success": False, "error": "Parâmetros limit e skip devem ser inteiros"},
                status=400,
            )

        try:
            usuarios, total = self.service.listar_usuarios(skip=skip, limit=limit)
            return JsonResponse(
                {
                    "success": True,
                    "total": total,
                    "count": len(usuarios),
                    "skip": skip,
                    "limit": limit,
                    "data": usuarios,
                }
            )
        except Exception as e:
            return JsonResponse(
                {"success": False, "error": f"Erro ao buscar usuários: {str(e)}"},
                status=500,
            )

    def post(self, request):
        """POST /api/usuarios/ — Alias de /registro/ para compatibilidade com frontends."""
        return RegistroView.as_view()(request)


@method_decorator(csrf_exempt, name="dispatch")
class UsuariosDetailView(View):
    """GET/PUT/PATCH/DELETE /api/usuarios/<id>/"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = UsuarioService()

    def _parse_id(self, usuario_id):
        try:
            return int(usuario_id), None
        except (ValueError, TypeError):
            return None, JsonResponse(
                {"success": False, "error": "ID deve ser um número inteiro"},
                status=400,
            )

    def get(self, request, usuario_id):
        uid, err = self._parse_id(usuario_id)
        if err:
            return err

        try:
            usuario = self.service.buscar_por_id(uid)
            if not usuario:
                return JsonResponse(
                    {"success": False, "error": "Usuário não encontrado"}, status=404
                )
            return JsonResponse({"success": True, "data": usuario})
        except Exception as e:
            return JsonResponse(
                {"success": False, "error": f"Erro ao buscar usuário: {str(e)}"},
                status=500,
            )

    def patch(self, request, usuario_id):
        uid, err = self._parse_id(usuario_id)
        if err:
            return err

        data, error = parse_request_body(request)
        if error:
            return JsonResponse({"success": False, "error": error}, status=400)

        try:
            usuario = self.service.atualizar_usuario(uid, data)
            if not usuario:
                return JsonResponse(
                    {"success": False, "error": "Usuário não encontrado"}, status=404
                )
            return JsonResponse({"success": True, "data": usuario})
        except ValueError as e:
            return JsonResponse({"success": False, "error": str(e)}, status=409)
        except Exception as e:
            return JsonResponse(
                {"success": False, "error": f"Erro ao atualizar usuário: {str(e)}"},
                status=500,
            )

    def put(self, request, usuario_id):
        return self.patch(request, usuario_id)

    def delete(self, request, usuario_id):
        uid, err = self._parse_id(usuario_id)
        if err:
            return err

        try:
            deletado = self.service.deletar_usuario(uid)
            if not deletado:
                return JsonResponse(
                    {"success": False, "error": "Usuário não encontrado"}, status=404
                )
            return JsonResponse({"success": True, "message": "Usuário removido com sucesso"})
        except Exception as e:
            return JsonResponse(
                {"success": False, "error": f"Erro ao remover usuário: {str(e)}"},
                status=500,
            )


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _gerar_token(usuario: dict) -> str:
    """
    Gera um JWT com prazo de 24 horas contendo o id e email do usuário.
    A chave secreta vem de settings.SECRET_KEY.
    """
    payload = {
        "id": usuario.get("id"),
        "email": usuario.get("email"),
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24),
        "iat": datetime.datetime.now(datetime.timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _normalizar_campos(data: dict) -> dict:
    """
    Normaliza nomes de campo do frontend para os nomes internos do backend.
    Aceita variações comuns de frontends React/TypeScript.
    """
    normalizado = dict(data)

    # email: aceita 'username' como alias
    if "email" not in normalizado and "username" in normalizado:
        normalizado["email"] = normalizado.pop("username")

    # senha: aceita 'password', 'senha', 'pass'
    if "senha" not in normalizado:
        for alias in ("password", "pass", "pwd"):
            if alias in normalizado:
                normalizado["senha"] = normalizado.pop(alias)
                break

    return normalizado
