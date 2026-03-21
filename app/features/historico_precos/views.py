from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from .price_history import get_history_for_links

class PriceHistoryView(APIView):
    permission_classes = [IsAuthenticatedOrReadOnly]  # ← era IsAuthenticated

    def get(self, request):
        links_raw = request.query_params.get("links", "")
        links = [l.strip() for l in links_raw.split(",") if l.strip()]

        if not links:
            return Response({"error": "Parâmetro 'links' obrigatório."}, status=400)

        history = get_history_for_links(links)
        return Response(history)