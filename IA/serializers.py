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


class AgentResponseSerializer(serializers.Serializer):
    content = serializers.CharField()
    provider = serializers.CharField()
    model = serializers.CharField()
    input_tokens = serializers.IntegerField()
    output_tokens = serializers.IntegerField()
