# Backend do Web Scraper — Mercado Livre

Documento técnico descrevendo o backend do web scraper de Mercado Livre presente neste repositório. Destinado a outra IA que irá entender, operar ou estender o componente.

---

## Resumo

O módulo implementa um scraper para o Mercado Livre com exposição via API (Django REST). Fornece busca por termo, paginação e (opcional) coleta de detalhes de cada produto.

Principais arquivos:

- `app/features/scraper/mercadolivre/services.py` — lógica de scraping e parsing HTML.
- `app/features/scraper/mercadolivre/views.py` — view API (DRF) que orquestra as chamadas.
- `app/features/scraper/mercadolivre/urls.py` — rota do endpoint.
- `app/features/email/email.py` — integração de notificação por e-mail usada pela view.

---

## Arquitetura Geral

- Camada HTTP (Django REST): `BuscarProdutosMercadoLivreView` expõe um endpoint GET.
- Serviço de scraping/parsing: funções em `services.py` fazem requests ao Mercado Livre e parseiam com `BeautifulSoup`.
- Integrações/side-effects: envio de e-mail via `EmailFeature` (não bloqueante).

Dependências principais: `requests`, `beautifulsoup4`, `lxml`, `djangorestframework`.

---

## Fluxo de Requisição (visão geral)

1. Cliente chama endpoint GET com parâmetro `q` (termo). Parâmetros opcionais: `pagina`, `detalhes`.
2. `BuscarProdutosMercadoLivreView.get` valida os parâmetros.
3. Chama `buscar_produtos(query, pagina, detalhes)` em `services.py`.
   - `buscar_produtos` -> `buscar_produtos_basic` para resultados básicos.
   - Se `detalhes=True`, faz requisições adicionais aos links dos produtos para extrair preço preciso.
4. Resposta JSON com `query`, `pagina`, `total`, `produtos`.
5. Se o `request.user` estiver autenticado, a view tenta enviar notificações por e-mail (falhas são suprimidas).

---

## Descrição dos Componentes

### services.py

- `HEADERS`: cabeçalhos HTTP (User-Agent, Accept-Language, etc.).
- `ML_SEARCH_URL`: template da URL de busca do Mercado Livre.

Funções principais:

- `buscar_produtos_basic(query: str, pagina: int = 1) -> list[dict]`
  - Monta URL (suporta offset para páginas >1).
  - Faz `requests.get(...)` com timeout e `raise_for_status()`.
  - Usa `BeautifulSoup(..., "lxml")` e seleciona resultados com seletores CSS; tem fallback para estruturas alternativas.
  - Para cada item extrai: `titulo`, `preco`, `preco_original`, `desconto`, `imagem`, `link`, `nota`, `quantidade_avaliacoes` e retorna lista de dicionários.

- `buscar_produtos(query: str, pagina: int = 1, detalhes: bool = False) -> list[dict]`
  - Chama `buscar_produtos_basic`. Se `detalhes=True`, para cada produto com `link` faz nova requisição (timeout reduzido) e tenta extrair preço com vários seletores; fallback por regex no texto da página.
  - Erros individuais ao buscar detalhes são suprimidos para não interromper a busca global.

Helpers de parsing:

- `_extrair_preco(container) -> dict`: tenta extrair preço e preço original a partir de blocos conhecidos (`andes-money-amount`) e, se necessário, aplica regexs sobre o texto completo para localizar valores.
- `_extrair_preco_from_text(text: str) -> str | None`: normaliza valores no formato brasileiro para uma string numérica padronizada (`1234.56`).
- `_extrair_imagem`, `_extrair_link`, `_extrair_titulo`, `_extrair_desconto`, `_extrair_avaliacao`: funções que extraem valores com seletores CSS e heurísticas.

Observações implementacionais:

- Prioriza ocorrências com `R$` ao filtrar candidatos monetários.
- Normalização lida com pontos e vírgulas e garante formato `xxx.yy`.
- Timeouts: 12s–15s; falhas de rede são transformadas em exceções controladas.

### views.py

- `BuscarProdutosMercadoLivreView(APIView)` (método `get`):
  - Lê `q` (obrigatório), `pagina` (int), `detalhes` (booleano a partir de strings).
  - Retorna 400 se `q` ausente.
  - Em `ConnectionError` retorna 502.
  - Se `request.user.is_authenticated`, chama métodos de `EmailFeature` para notificações (não bloqueantes).
  - Responde 200 com JSON contendo `query`, `pagina`, `total`, `produtos`.

### urls.py

- Rota raiz do módulo registra a view:
  - `path("", BuscarProdutosMercadoLivreView.as_view(), name="scraper-mercadolivre")`

---

## Formato do objeto `produto` retornado

Cada item na lista `produtos` tem as chaves (conforme extraído no código):

- `titulo` (string)
- `preco` (string normalizada, ex.: `"1234.56"` ou `null`)
- `preco_original` (string normalizada ou `null`)
- `desconto` (string ou `null`)
- `imagem` (URL ou `null`)
- `link` (URL ou `null`)
- `nota` (string ou `null`)
- `quantidade_avaliacoes` (string ou `null`)

Exemplo de resposta (resumido):

```json
{
  "query":"smartphone",
  "pagina":1,
  "total":5,
  "produtos":[
    {"titulo":"Exemplo", "preco":"999.99", "preco_original":"1299.99", "imagem":"https://...", "link":"https://..."}
  ]
}
```

---

## Erros, exceções e robustez

- Requisições HTTP usam `timeout` e `raise_for_status()`; falhas geram `ConnectionError` para a view tratar.
- Parsers suprimem exceções onde adequado (ex.: falha ao buscar detalhes de um produto não interrompe toda a operação).
- Envio de e-mails está protegido por `try/except` para não quebrar a resposta da API.

---

## Segurança, conformidade e boas práticas

- Há `User-Agent` customizado para reduzir bloqueio, mas scraping ainda pode violar termos de uso.
- Endpoint não possui proteção específica contra abuso; recomenda-se aplicar throttle do DRF ou autenticação.
- Timeouts configurados evitam hangs longos.

---

## Limitações conhecidas

- Seletores CSS dependem da estrutura atual do Mercado Livre e podem quebrar com mudanças.
- Não há caching — cada requisição aciona scraping em tempo real.
- Operação síncrona: pode bloquear workers sob carga; considerar mover para tarefa assíncrona ou fila.
- Ausência de retry/backoff e de rotação de proxies.

---

## Recomendações de melhoria

- Adicionar caching (Redis) para consultas frequentes.
- Tornar scraping assíncrono (`aiohttp`/`asyncio`) ou usar Celery para tarefas de longa duração.
- Implementar retries com backoff e detecção de bloqueio (429/captcha).
- Adicionar testes unitários para helpers de parsing.
- Monitoramento e métricas (latência, erros, número de requests ao Mercado Livre).

---

## Exemplo de uso (HTTP)

GET /scraper-mercadolivre/?q=smartphone&pagina=1&detalhes=true

Parâmetros:
- `q` (obrigatório): termo de busca.
- `pagina` (opcional): inteiro >= 1.
- `detalhes` (opcional): `true`/`1` para coletar preços detalhados em cada link.

---

## Checklist para outra IA que for operar/estender este módulo

- Entender os seletores CSS usados em `services.py` e testar contra HTML real.
- Validar política do Mercado Livre antes de rodar em produção.
- Escrever e rodar testes para `_extrair_preco_from_text`, `_extrair_preco` e outros helpers.
- Adicionar caching e throttling conforme necessidade.

---

## Referências rápidas (caminhos no repositório)

- `services`: app/features/scraper/mercadolivre/services.py
- `view`: app/features/scraper/mercadolivre/views.py
- `urls`: app/features/scraper/mercadolivre/urls.py
- `email feature`: app/features/email/email.py

---

## Próximos passos sugeridos

- Gerar testes unitários para os helpers de parsing.
- Implementar cache para resultados de busca.
- Adicionar monitoramento e throttling ao endpoint.

---

Arquivo gerado automaticamente a pedido do usuário.
