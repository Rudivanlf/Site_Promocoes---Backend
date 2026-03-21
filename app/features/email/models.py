from django.db import models
from django.contrib.auth.models import User
import random
import string

class AcessoUsuario(models.Model):
    TIPOS = [
        ('login', 'Login'),
        ('registro', 'Registro'),
        ('recuperacao', 'Recuperação de Senha'),
    ]

    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='acessos')
    codigo = models.CharField(max_length=6)
    tipo = models.CharField(max_length=20, choices=TIPOS, default='login')
    verificado = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Acesso de Usuário'
        verbose_name = 'Acessos de Usuário'
        ordering = ['-criado_em']

    @staticmethod
    def gerar_codigo(tamanho=6):
        return ''.join(random.choices(string.digits, k=tamanho))

    def __str__(self):
        return f"{self.usuario.username} - {self.tipo} - {self.codigo}"
