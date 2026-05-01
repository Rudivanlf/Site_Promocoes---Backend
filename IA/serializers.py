from rest_framework import serializers


class MessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["user", "assistant"])
    content = serializers.CharField()


class AgentRequestSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(
        choices=["gemini"],
        required=False,
        allow_null=True,
        default=None,
    )
    messages = MessageSerializer(many=True, min_length=1)
    system_prompt = serializers.CharField(required=False, default="", allow_blank=True)
    model = serializers.CharField(required=False, default="", allow_blank=True)
    # Mantido para compatibilidade com clientes antigos; a chave agora vem da env.
    api_key = serializers.CharField(required=False, default="", allow_blank=True, write_only=True)
    temperature = serializers.FloatField(required=False, default=0.7, min_value=0.0, max_value=2.0)
    max_tokens = serializers.IntegerField(required=False, default=2048, min_value=1)
    auto_recommend = serializers.BooleanField(required=False, default=True)
    sources = serializers.ListField(
        child=serializers.ChoiceField(choices=["mercadolivre", "amazon", "kabum"]),
        required=False,
        allow_empty=True,
    )
    pagina = serializers.IntegerField(required=False, default=1, min_value=1)
    limite_por_fonte = serializers.IntegerField(required=False, default=10, min_value=1, max_value=50)
    max_resultados = serializers.IntegerField(required=False, default=5, min_value=1, max_value=10)


class AgentResponseSerializer(serializers.Serializer):
    content = serializers.CharField()
    provider = serializers.CharField()
    model = serializers.CharField()
    input_tokens = serializers.IntegerField()
    output_tokens = serializers.IntegerField()


class RecommendRequestSerializer(serializers.Serializer):
    query = serializers.CharField()
    pedido = serializers.CharField()
    sources = serializers.ListField(
        child=serializers.ChoiceField(choices=["mercadolivre", "amazon", "kabum"]),
        required=False,
        allow_empty=True,
    )
    pagina = serializers.IntegerField(required=False, default=1, min_value=1)
    limite_por_fonte = serializers.IntegerField(required=False, default=10, min_value=1, max_value=50)
    max_resultados = serializers.IntegerField(required=False, default=5, min_value=1, max_value=10)
    provider = serializers.ChoiceField(
        choices=["gemini"],
        required=False,
        allow_null=True,
        default=None,
    )
    model = serializers.CharField(required=False, default="", allow_blank=True)
    temperature = serializers.FloatField(required=False, default=0.2, min_value=0.0, max_value=2.0)
    max_tokens = serializers.IntegerField(required=False, default=2048, min_value=1)
