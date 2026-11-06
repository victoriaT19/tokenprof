# Registro de testes

Resultados de cada rodada de testes, com data, ambiente e números. Serve de fonte para o README e o paper: só entra aqui o que foi medido de verdade.

---

## 2026-10-31: proxy de registro (v0.0.1)

### Testes automatizados

`pytest`: **8 de 8 passaram** (0,9 s). Cobrem:

- chamada normal: repasse da resposta, registro de tokens (inclusive do cache) e custo;
- streaming: bytes repassados sem alteração ao cliente e resposta remontada no registro;
- pedido automático de contagem de tokens no streaming, e a opção de desligar;
- provedor fora do ar: resposta 502 e erro registrado;
- erro do provedor (429): repassado ao cliente e registrado;
- outros endpoints (`/v1/models`) repassados sem registro;
- chamadas de ferramenta divididas em pedaços de 7 bytes, remontadas corretamente;
- tabela de preços com fallback pelo prefixo do nome do modelo;
- a chave de API é repassada ao provedor mas nunca aparece no registro.

### Teste de ponta a ponta com o Ollama

**Ambiente:** Windows 11, Ollama 0.40.13, modelo `qwen2.5:0.5b` rodando só na CPU (`qwen2.5-cpu`, com `num_gpu 0`).
**Script:** [`scripts/e2e_ollama.py`](../scripts/e2e_ollama.py)
**Registro bruto:** [`results/2026-10-31-ollama-e2e.jsonl`](results/2026-10-31-ollama-e2e.jsonl)

| Chamada | Status | Latência total | Tempo até o 1º token | Tokens de entrada | Tokens de saída | Tokens do cache |
|---|---|---|---|---|---|---|
| Normal | 200 | 2.335,8 ms | — | 45 | 133 | 24 |
| Streaming | 200 | 3.588,1 ms | 55,0 ms | 45 | 213 | 44 |
| Ferramenta em streaming | 200 | 966,0 ms | 933,2 ms | 153 | 21 | 18 |

**O que foi verificado:**

- As três chamadas passaram pelo proxy e foram registradas com o run (`e2e-1`) e a etapa de cada uma.
- No streaming com ferramenta, o proxy remontou a chamada a partir dos pedaços: `clima({"cidade":"Recife"})`, com `finish_reason: tool_calls`.
- O registro guarda os acentos corretamente em UTF-8.
- No streaming, o tempo até o primeiro token (55 ms) é bem menor que a latência total (3,6 s). Isso só aparece porque o proxy mede os dois separadamente.

### Falha real do provedor, capturada sem querer

Na primeira tentativa, o Ollama tentou usar a GPU integrada Intel pelo backend Vulkan e o driver falhou (`compute pipeline creation failed`). O proxy repassou o erro 500 ao cliente e registrou a chamada com o erro completo e a latência até a falha (30,2 s).

**Registro bruto:** [`results/2026-10-31-ollama-gpu-failure.jsonl`](results/2026-10-31-ollama-gpu-failure.jsonl)

**Solução:** uma variante do modelo só para CPU (`PARAMETER num_gpu 0` num Modelfile).

### Observações do proxy

- O `qwen2.5:0.5b` serve para testar o proxy, mas é pequeno demais para responder bem: errou fatos básicos sobre Recife. O profiler e os benchmarks vão precisar de um modelo maior ou de uma API.
- Custo não foi medido nesta rodada: o Ollama é local e não houve tabela de preços.

---

## 2026-10-31: análise e detectores (dia 1 do plano comprimido)

### Testes automatizados

`pytest`: **15 de 15 passaram** (8 do proxy + 7 novos da análise). Os novos cobrem:

- um run sintético com 4 problemas plantados (horário no system prompt, saída de ferramenta grande e não usada, chamada de ferramenta repetida, contexto reenviado sem cache): os 4 tipos são detectados, nas chamadas certas;
- um run limpo (prefixo estável vindo do cache, saída pequena e usada): **nenhum** alerta;
- requisições idênticas detectadas como repetidas;
- a divisão do prompt por tipo de conteúdo soma o total de tokens informado pelo provedor;
- chamadas com erro e outros endpoints são ignorados;
- o relatório HTML e o comando `tokenprof analyze` geram os arquivos.

### Validação com agente real: desperdício plantado vs. corrigido

**Ambiente:** o mesmo da rodada anterior (Windows 11, Ollama 0.40.13, `qwen2.5-cpu`, temperatura 0).
**Script:** [`scripts/demo_agent.py`](../scripts/demo_agent.py). É um agente de atendimento que consulta 3 pedidos com a ferramenta `buscar_pedido`.

- **Modo desperdiçador:** horário atual (com microssegundos) no system prompt, atualizado a cada chamada, e a ferramenta devolve o registro completo do pedido (cliente, 25 itens, 30 eventos de histórico, metadados), quando só o status importa.
- **Modo corrigido:** aplica as correções que o próprio relatório sugere. O system prompt fica fixo, o horário vai para a mensagem do usuário, e a ferramenta devolve só `id` e `status`.

| | Desperdiçador | Corrigido | Diferença |
|---|---|---|---|
| Chamadas | 6 (3 runs × 2) | 6 (3 runs × 2) | igual |
| Pedidos respondidos corretamente | 3/3 | 3/3 | igual |
| Tokens de prompt | 10.583 | 1.283 | **−87,9%** |
| Tokens de saída | 155 | 105 | −32,3% |
| Tokens de prompt vindos do cache | 210 (2,0%) | 954 (74,4%) | — |
| Latência somada | 53,5 s | 3,8 s | −93,0% (CPU) |

**O que o tokenprof detectou:**

- **Desperdiçador:** os dois problemas plantados, nos 3 runs. *Cache breaker*: o trecho que mudou aparece no relatório (ex.: `"22:05:32.427173."`). *Unused tool output*: saídas de ~3.100–3.300 tokens com menos de 10% das palavras usadas. Também apontou 121 tokens de contexto reenviado sem cache.
- **Corrigido:** **nenhum alerta** (0 falsos positivos neste teste).
- *Repeated tool call* não disparou em nenhum dos dois, o que está correto: o agente não entrou em loop.

**Registros e relatórios:**

- [`results/2026-10-31-demo-wasteful.jsonl`](results/2026-10-31-demo-wasteful.jsonl) → [relatório](results/2026-10-31-demo-wasteful-report.html)
- [`results/2026-10-31-demo-fixed.jsonl`](results/2026-10-31-demo-fixed.jsonl) → [relatório](results/2026-10-31-demo-fixed-report.html)

### Limites desta rodada

- É uma **validação dos detectores com desperdício plantado**, não um experimento em agentes de terceiros. Mostra que o tokenprof encontra o que existe e não acusa o que não existe. O experimento com agentes open source é o dia 3.
- 3 tarefas com um modelo de 0,5B. As respostas do modo desperdiçador citaram dados irrelevantes do registro completo (ex.: nome do cliente, SKU), mas o status estava certo nos 3.
- A queda de latência é exagerada pela CPU: num provedor com GPU a diferença absoluta seria bem menor.
- O "desperdício estimado" do relatório soma tipos que se sobrepõem e foi limitado a 100% do prompt. O número confiável é a **redução medida** entre os modos: −87,9% de tokens de prompt.
---

## 2026-11-06: Gemini (nível gratuito) pelo proxy e cache "não informado"

### Teste com o Gemini

**Ambiente:** proxy apontando para o endpoint compatível com a OpenAI do Gemini (`generativelanguage.googleapis.com/v1beta/openai`), modelo `gemini-flash-lite-latest`, chave do nível gratuito do Google AI Studio.
**Teste:** duas chamadas seguidas com o mesmo system prompt de ~6,6 mil tokens e perguntas diferentes.

| Rodada | Chamada | Status | Latência | Tokens de prompt | Tokens do cache informados |
|---|---|---|---|---|---|
| 1ª (cache frio) | 1 | 200 | 1.038 ms | 6.657 | campo ausente |
| 1ª (cache frio) | 2 | 200 | 953 ms | 6.656 | campo ausente |
| 2ª (minutos depois) | 1 | 200 | — | 6.657 | 4.073 |
| 2ª (minutos depois) | 2 | 200 | — | 6.656 | 4.073 |

**Registro bruto da 2ª rodada:** [`results/2026-11-06-gemini-cache-check.jsonl`](results/2026-11-06-gemini-cache-check.jsonl). Conferido que a chave de API não aparece no arquivo.

### O que isso revelou e a correção

- O Gemini só manda `prompt_tokens_details.cached_tokens` quando há acerto de cache. Quando não há, o campo nem vem.
- **Bug encontrado:** o proxy gravava `cached_tokens: 0` quando o campo vinha ausente. Para provedores que nunca informam cache, isso faria o detector *Uncached resend* acusar desperdício sem base: na 1ª rodada ele acusou 6.649 tokens (50%).
- **Correção:** agora o proxy grava `cached_tokens: null` quando o provedor não manda o campo. A análise só julga reenvio sem cache nas chamadas com cache informado, e o relatório mostra "n/a" quando nenhuma chamada informou cache. A escolha é conservadora: prefere deixar de acusar a acusar sem prova.
- Com o cache informado (2ª rodada), o detector apontou 2.576 tokens reenviados sem cache (19%), que é a parte do prefixo que o cache implícito do Gemini não cobriu.
- `pytest`: **16 de 16 passaram**, incluindo um teste novo para cache não informado.

### Limites

- O cache do Gemini é implícito e não controlável: o mesmo prefixo pode ou não vir do cache dependendo do momento. No experimento, rodar cada modo mais de uma vez e comparar médias.
---

## 2026-11-06: experimento piloto com frameworks de agentes open source

### Montagem

- **Modelo:** `gemini-3.5-flash-lite` (nível gratuito do Gemini, endpoint compatível com a OpenAI), temperatura 0.
- **Loja simulada:** 40 pedidos, 8 clientes e 40 produtos gerados com semente fixa ([`experiments/agents/store.py`](../experiments/agents/store.py)). Ferramentas: `get_order`, `list_customer_orders`, `get_product`.
- **Tarefas:** 10 perguntas com resposta calculada a partir da loja ([`tasks.py`](../experiments/agents/tasks.py)). Números conferidos com tolerância de R$ 0,01, texto por trecho. Clientes escolhidos para que nenhuma resposta esperada seja 0.
- **Frameworks, com as configurações padrão:** smolagents 1.26.0 (`ToolCallingAgent`) e OpenAI Agents SDK 0.24.0 (`OpenAIChatCompletionsModel`). 2 repetições de cada.
- **Linha de base:** as ferramentas devolvem o registro completo, como uma API REST típica.
- **Corrigido:** aplica a única correção que o tokenprof sugeriu na linha de base: as ferramentas devolvem só os campos necessários.

### Resultados

| | Linha de base | Corrigido | Diferença |
|---|---|---|---|
| **OpenAI Agents SDK** | | | |
| Acertos | 20/20 | 20/20 | igual |
| Chamadas por tarefa | 2,0 | 2,1 | +0,1 |
| Tokens de prompt (total) | 61.622 | 13.818 | **−77,6%** |
| Tokens de prompt por tarefa | 3.081 | 691 | **−77,6%** |
| Saídas de ferramenta, % do prompt | 76,2% | 11,4% | — |
| **smolagents** | | | |
| Acertos | 20/20 | 20/20 | igual |
| Chamadas por tarefa | 2,0 | 2,1 | +0,1 |
| Tokens de prompt (total) | 105.317 | 59.806 | **−43,2%** |
| Tokens de prompt por tarefa | 5.266 | 2.990 | **−43,2%** |
| Saídas de ferramenta, % do prompt | 43,0% | 3,3% | — |
| **Os dois juntos** | | | |
| Acertos | 40/40 | 40/40 | igual |
| Tokens de prompt (total) | 166.939 | 73.624 | **−55,9%** |
| Desperdício apontado pelo tokenprof | 72.895 (44%) | 0 | — |

**Registros brutos, respostas corrigidas e relatórios:**

- Linha de base: [`trace`](results/2026-11-06-exp-baseline.jsonl), [`respostas`](results/2026-11-06-exp-baseline-answers.jsonl), [`relatório`](results/2026-11-06-exp-baseline-report.html)
- Corrigido: [`trace`](results/2026-11-06-exp-fixed.jsonl), [`respostas`](results/2026-11-06-exp-fixed-answers.jsonl), [`relatório`](results/2026-11-06-exp-fixed-report.html)
- Resumo por framework: `python experiments/agents/summarize.py <trace>`

### Achados

1. **Saídas de ferramenta dominam o custo dos agentes:** 76% dos tokens de prompt no OpenAI Agents SDK e 43% no smolagents, na linha de base. Devolver só os campos necessários cortou 56% dos tokens sem mudar nenhum acerto.
2. **O system prompt padrão do smolagents é grande:** depois da correção, ele passa a ser 74% dos tokens de prompt (cerca de 1.100 tokens por chamada). Por isso o smolagents gasta 4,3× mais que o OpenAI Agents SDK por tarefa na versão corrigida (2.990 contra 691). Nenhum detector atual aponta isso, porque um prompt fixo pode vir do cache. É candidato a um detector novo de "prompt fixo grande".
3. **Bug do tokenprof encontrado pelo experimento e corrigido:** o smolagents envia as saídas de ferramenta como mensagem de usuário ("Observation: …"), não com o papel `tool`. Na primeira análise o tokenprof não enxergou nada no smolagents. Agora reconhece esse formato, com teste novo (17 de 17 passando).
4. **LangGraph ficou de fora:** com o adaptador `langchain-openai`, o Gemini atual recusa a segunda chamada (erro 400: falta a `thought_signature` das chamadas de função, que o adaptador descarta). O modelo antigo que não exige isso (`gemini-2.5-flash-lite`) não está disponível para contas novas.
5. **Nenhum alarme falso na versão corrigida:** 0 desperdício apontado.

### Limites

- É um **piloto**: 2 frameworks, 10 tarefas simples (cerca de 2 chamadas por tarefa), 2 repetições, um modelo.
- A loja e as respostas completas da API são sintéticas, feitas para parecer uma API REST típica. Em agentes com tarefas mais longas, o peso das saídas de ferramenta tende a ser maior, porque elas são reenviadas a cada chamada seguinte, mas isso não foi medido aqui.
- **Latência não melhorou** de forma consistente (OpenAI Agents SDK: 35,0 s → 45,8 s somados; smolagents: 43,2 s nos dois). No nível gratuito a latência varia muito, então ela não entra como resultado.
- Custo em dinheiro não foi medido (nível gratuito). Pelos tokens, a economia em uma API paga seria proporcional aos −56% de tokens de prompt.
- O cache do Gemini quase não apareceu (4 chamadas na linha de base, 0 na corrigida), então os detectores de cache não foram exercitados neste experimento.