import logging

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .base import ProviderQuotaExceeded
from .serializers import AgentRequestSerializer, AgentResponseSerializer
from .services import AgentService, PROVIDERS

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def chat(request):
    """
    Send a chat message to an AI provider.

    Request body:
        {
            "provider": "gemini",           // optional if a default is configured
            "messages": [
                {"role": "user", "content": "Hello!"}
            ],
            "system_prompt": "...",         // optional
            "temperature": 0.7,             // optional
            "max_tokens": 2048              // optional
        }

    Response:
        {
            "content": "...",
            "provider": "gemini",
            "model": "gemini-1.5-flash",
            "input_tokens": 10,
            "output_tokens": 42
        }
    """
    serializer = AgentRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)

    data = serializer.validated_data

    # Resolve provider: use request value or fall back to first configured provider
    provider_name = data.get("provider")
    if not provider_name:
        from django.conf import settings
        configured = [
            name
            for name, cfg in getattr(settings, "AGENT_PROVIDERS", {}).items()
            if cfg.get("api_key")
        ]
        if not configured:
            return Response(
                {"error": "No provider configured. Set AGENT_PROVIDERS in settings or pass 'provider' in the request."},
                status=400,
            )
        provider_name = configured[0]

    try:
        response = AgentService.chat(
            provider_name=provider_name,
            messages=data["messages"],
            system_prompt=data["system_prompt"],
            model=data["model"],
            temperature=data["temperature"],
            max_tokens=data["max_tokens"],
        )
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    except ProviderQuotaExceeded as e:
        logger.warning("Quota exceeded: provider=%s retry_after=%s", e.provider, e.retry_after)
        body = {
            "error": "Provider quota exceeded",
            "provider": e.provider,
            "message": e.message,
        }
        headers = {}
        if e.retry_after is not None:
            headers["Retry-After"] = str(int(e.retry_after))
        return Response(body, status=429, headers=headers)
    except Exception:
        logger.exception("Unexpected error calling provider")
        return Response({"error": "Falha ao processar a resposta do provedor."}, status=502)

    return Response(AgentResponseSerializer(response).data, status=200)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_providers(request):
    """
    List all registered providers and whether they are configured.

    Response:
        {
            "providers": [
                {"provider": "gemini", "default_model": "gemini-1.5-flash", "configured": true}
            ]
        }
    """
    from django.conf import settings
    cfg = getattr(settings, "AGENT_PROVIDERS", {})
    return Response({
        "providers": [
            {
                "provider": name,
                "default_model": cls.DEFAULT_MODEL,
                "configured": bool(cfg.get(name, {}).get("api_key")),
            }
            for name, cls in PROVIDERS.items()
        ]
    })
