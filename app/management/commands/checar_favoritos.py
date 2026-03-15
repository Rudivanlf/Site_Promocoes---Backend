from django.core.management.base import BaseCommand

from app.features.busca_inteligente.tasks import buscar_promocoes_para_favoritos


class Command(BaseCommand):
    help = (
        "Executa uma busca de promoções sobre os produtos favoritados de todos os "
        "usuários. Pode rodar uma única vez ou em loop com intervalo customizável."
    )
    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=int,
            default=0,
            help="segundos entre execuções repetidas; 0 executa apenas uma vez",
        )

    def handle(self, *args, **options):
        interval = options.get("interval", 0)

        def _run_once():
            self.stdout.write("iniciando verificação de favoritos")
            try:
                resultado = buscar_promocoes_para_favoritos()
                if resultado is not None:
                    total, atualizados = resultado
                    self.stdout.write(
                        f"relatório: {total} favoritos verificados, {atualizados} atualizados"
                    )
            except Exception as exc:  # pragma: no cover
                self.stderr.write(f"erro ao processar favoritos: {exc}")
                raise
            self.stdout.write("verificação concluída")

        if interval and interval > 0:
            import time

            self.stdout.write(f"executando em loop a cada {interval} segundos")
            while True:
                _run_once()
                time.sleep(interval)
        else:
            _run_once()
