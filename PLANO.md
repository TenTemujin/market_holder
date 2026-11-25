# Market Holder: plano de implementação

Simulador de mercado multi-ativo com interface inspirada no Bloomberg Terminal (grade de painéis, barra de comando por texto, teclado primeiro, alta densidade). Dados de fontes abertas, execução simulada.

Observação: a interface é inspirada no conceito, não copia marca, logotipo, fontes ou código da Bloomberg. Os mnemônicos de comando são genéricos e próprios (ver Fase 4).

## Decisões de stack (a confirmar)

| Camada | Escolha | Motivo |
|---|---|---|
| Backend | Python 3.12, FastAPI, WebSocket | Ecossistema de dados, ambiente já existente |
| Armazenamento | DuckDB + Parquet | Consulta rápida de séries históricas, sem servidor |
| Simulação | Python puro (módulo isolado, sem dependência de web) | Testável sozinho; pode migrar para Rust depois se medir gargalo |
| Frontend | TypeScript, React, Vite | Padrão para painéis |
| Gráficos | lightweight-charts (TradingView, open source) | Gráfico financeiro leve |
| Painéis | flexlayout-react | Grade arrastável e layouts salvos |

## Arquitetura

```
providers/ (Binance, BCB, Stooq, FRED, Tesouro, ...)
      -> cache (Parquet/DuckDB)
      -> MarketClock (ao vivo ou replay)
      -> Engine (carteira, ordens, execução, P&L)
      -> API (REST + WebSocket)
      -> UI (grade de painéis + barra de comando)
```

Regras de desenho:
- O motor de simulação não conhece web nem provedores. Recebe eventos de preço e ordens, devolve execuções.
- Todo provedor implementa a mesma interface: `search`, `history(symbol, start, end, freq)`, `stream(symbol)` (opcional), `capabilities` (declara frequência, atraso e classes de ativo).
- Um relógio único (`MarketClock`) alimenta tudo. Ao vivo e replay usam o mesmo caminho de código, só muda a fonte do tempo.
- Simbologia própria: `CLASSE:MERCADO:SIMBOLO` (ex.: `EQ:B3:PETR4`, `CRYPTO:BINANCE:BTCUSDT`, `FX:BCB:USDBRL`, `RATE:FRED:DGS10`).

## Grafo de execução e arquitetura (graphify)

Regra do projeto: o grafo é gerado e atualizado com o graphify (`/graphify`), com saída em `graphify-out/`.
- Gerar o grafo ao fim da Fase 0 (primeiro código) e atualizá-lo ao fim de cada fase e a cada mudança estrutural (novo provedor, novo módulo, mudança de fluxo).
- Perguntas sobre arquitetura e fluxo (quem chama quem, de onde vem um preço até a tela) consultam o grafo antes de ler arquivos.
- O grafo deve mostrar dois níveis: arquitetura (módulos e dependências) e execução (caminho evento de preço -> relógio -> motor -> API -> UI).

## Fases

Cada fase termina com critério de aceite verificável e com o grafo atualizado. Nenhum número de desempenho entra em documentação sem medição.

### Fase 0: fundação
- Estrutura do repositório, `pyproject.toml`, lint e testes, repositório git.
- Modelo de domínio: `Instrument`, `Bar`, `Tick`, `Order`, `Fill`, `Position`, `Portfolio`.
- Interface `Provider` e esquema de simbologia.
- Primeira geração do grafo com graphify.
- Aceite: testes de tipos e de serialização passam; `graphify-out/` existe.

### Fase 1: motor de simulação
- Carteira em múltiplas moedas, posição comprada e vendida, margem simples.
- Ordens: a mercado, limitada, stop, stop-limite. OCO depois.
- Execução contra barras (OHLC) e contra ticks; modelo de slippage e spread configurável; taxas por mercado.
- Cálculo de P&L realizado e não realizado, e exposição.
- Aceite: testes com casos calculados à mão para cada tipo de ordem, incluindo gap de abertura e ordem que atravessa a barra.

### Fase 2: camada de dados
- Adaptadores, nesta ordem: Binance (cripto), BCB SGS/PTAX (câmbio, Selic, CDI, IPCA), Stooq (ações e commodities globais), FRED (juros EUA, macro), Tesouro Direto (títulos).
- Cache em Parquet com controle de lacunas; limite de taxa e retentativa por provedor.
- Aceite: para cada provedor, baixar uma série conhecida e comparar com a fonte oficial em pelo menos 3 pontos de data.

### Fase 3: API e relógio
- `MarketClock` com modos ao vivo e replay (velocidade 1x a 1000x, pausa, salto para data).
- REST para histórico, ordens e carteira; WebSocket para preços e execuções.
- Aceite: replay de um dia de BTCUSDT reproduz as mesmas execuções em duas rodadas (determinismo).

### Fase 4: shell da interface
- Layout em grade com painéis arrastáveis e layouts salvos.
- Barra de comando por texto. Mnemônicos próprios: `GP` (gráfico), `HP` (histórico), `DES` (descrição), `MON` (watchlist), `ORD` (ordem), `PORT` (carteira), `BOOK` (livro), `CURVE` (curva de juros), `ECO` (macro), `FX` (câmbio), `REPLAY` (controle de tempo). Formato: `<ativo> <função>`.
- Tema escuro denso, teclado primeiro, atalhos para tudo.
- Aceite: abrir 6 painéis, salvar e recarregar o layout, navegar só pelo teclado.

### Fase 5: painéis de operação
- `GP`: gráfico com ordens desenhadas, arrastar para mudar stop e alvo.
- `MON`: watchlist multi-mercado com variação e atraso do dado visível.
- `ORD`: entrada de ordem com atalhos de percentual do saldo.
- `BOOK` e time & sales: real para cripto; simulado, e marcado como tal, para os demais.
- `PORT`: posições, P&L ao vivo, exposição e margem.
- `CURVE` e `ECO`: curva de juros e séries macro.
- Aceite: operar uma ordem completa (enviar, ver no gráfico, executar, ver na carteira) em cripto ao vivo e em ação no replay.

### Fase 6: cenários e replay avançado
- Cenários prontos (2008, 2015, 2020) com múltiplos mercados no mesmo relógio.
- Eventos macro no replay (decisão de juros, divulgação de inflação).
- Aceite: cenário 2020 roda com cripto, câmbio, juros e ações juntos.

### Fase 7: expansão
- B3 (COTAHIST e brapi), opções por Black-Scholes sobre o ativo-base com cadeia simulada, futuros simulados, ANBIMA, commodities adicionais.
- Placar, histórico de sessões e métricas (Sharpe, drawdown).

## Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Fontes não oficiais (Yahoo) mudam ou quebram | Stooq e fontes oficiais primeiro; adaptador isolado e trocável |
| Dados atrasados enganam o usuário | Cada preço exibe a origem e o atraso; `capabilities` do provedor é obrigatório |
| Execução irrealista deixa o jogo fácil | Slippage, spread e taxas desde a Fase 1; teste de sensibilidade |
| Limites de taxa das APIs | Cache agressivo e fila por provedor |
| Escopo grande demais | Fases 0 a 5 formam o MVP; a Fase 7 só depois |

## Primeiro passo concreto

Fases 0 e 1 (domínio e motor) são independentes de dados e de interface. Dá para começar já e validar com testes antes de tocar na rede.
