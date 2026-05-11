# Prompt para IA do Front: Grafico de Historico de Precos

Voce e a IA do front-end. Sua tarefa e renderizar um grafico de historico de precos para produtos favoritados. Use as instrucoes abaixo para interpretar e mostrar os dados corretamente.

## Fonte de dados

Endpoint:

- `GET /api/scraper/historico/?links=<url1>,<url2>,...`

Resposta esperada:

- Objeto onde cada chave e o link original do produto.
- Cada valor e um array de pontos com `price` e `recorded_at` (ISO 8601).

Exemplo de resposta:

```json
{
  "https://loja.com/produto/123": [
    {"price": 249.90, "recorded_at": "2026-05-01T12:00:00+00:00"},
    {"price": 252.50, "recorded_at": "2026-05-03T12:00:00+00:00"}
  ]
}
```

## Regras de exibicao

1) Sempre ordenar os pontos por `recorded_at` ascendente.
2) Converter `recorded_at` para o fuso local do usuario ao exibir no eixo X.
3) O eixo Y deve usar moeda BRL, com duas casas decimais.
4) Se o array de pontos estiver vazio, exibir estado vazio: "Sem historico de preco".
5) Se existir apenas 1 ponto, renderizar um grafico com linha plana ou um ponto destacado.

## Consistencia do grafico

- Os dados sao persistidos no banco, entao o grafico deve ser estavel entre recargas.
- Nao gere dados fake no front.
- Se o usuario favoritou agora, o historico pode ter pontos ficticios consistentes com o preco atual. Exiba normalmente.

## Sugestao de UX

- Titulo: "Historico de preco".
- Tooltip: mostrar data formatada e preco (ex.: "05/05/2026 - R$ 249,90").
- Linha suave e pontos discretos.

## Tratamento de erro

- Se o endpoint falhar, exibir: "Falha ao carregar historico".
- Opcional: botao de tentar novamente.
