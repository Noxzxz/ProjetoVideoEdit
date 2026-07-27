# Segunda Rodada de Implementação — Pipeline de Pós-Produção com IA

> Continuação direta do `RELATORIO_IMPLEMENTACAO.md` (teste real de 8min36s) e do `Registro_Decisoes_e_Bugs_Lessons_Learned.md` (D1-D12, B1-B11). Este documento faz duas coisas, em ordem: **(1)** fecha as correções de B8 e B9, que já estavam totalmente diagnosticadas; **(2)** solicita autorização explícita antes de iniciar o desenvolvimento dos itens restantes do "Turno 7" (voz/marcadores, silêncio, shorts) — **excluindo o Thumbnail Composer, removido do escopo por decisão sua**.

---

## Parte 1 — Fechamento das Correções B8 e B9

Estas duas correções são pequenas, isoladas e já estavam bem diagnosticadas no relatório de implementação — por isso são aplicadas diretamente aqui, sem necessidade de autorização adicional (mesmo critério usado na Segunda Rodada anterior para B1-B7: bugs já diagnosticados são corrigidos, não propostos).

### B8 — Nome de estágio aparecendo como número no relatório (bloco paralelo)

**Sintoma:** no relatório final, estágios executados dentro do `ThreadPoolExecutor` (SUBTITLE_STYLING, THUMBNAIL_FRAMES, SHORTS_EXTRACTION) apareciam como `7`, `8`, `9` em vez do nome legível.

**Causa raiz:** o caminho de execução paralela registrava o estágio usando `stage.value` (o número do enum), enquanto o caminho sequencial usava `stage.name`.

**Correção aplicada:**

```python
# pipeline/runner.py — ANTES (bug, caminho paralelo apenas)
future_to_stage = {
    executor.submit(handler, video_path, video_hash, config, state): stage.value  # <- bug
    for stage, handler in parallel_handlers.items()
}
...
result.stage = future_to_stage[future]  # registrava o int

# pipeline/runner.py — DEPOIS (corrigido)
future_to_stage = {
    executor.submit(handler, video_path, video_hash, config, state): stage.name  # <- corrigido
    for stage, handler in parallel_handlers.items()
}
...
result.stage = future_to_stage[future]  # registra a string legível, igual ao caminho sequencial
```

**Status:** corrigido. Registrado como B8 na tabela principal do lessons-learned (Seção 2).

**Teste de regressão adicionado:** `test_runner_parallel_stage_names()` — roda o `PipelineRunner` com um `PARALLEL_GROUP` mockado e valida que todo `StageResult.stage` no histórico é uma string presente em `PipelineStage.__members__`, nunca um `int`.

---

### B9 — Relatório mostrando "Incompleto" mesmo em execução com sucesso total

**Sintoma:** ao final de uma execução 100% bem-sucedida, o relatório (`report.md`/`analytics.json`) mostrava status "Incompleto".

**Causa raiz:** `PackagingAgent` lê `state.completed` para decidir o status a exibir, mas essa flag só era setada como `True` pelo `PipelineRunner` **depois** que todos os estágios retornavam — e PACKAGING é o próprio último estágio. Ou seja, o Packaging sempre executava e lia a flag *antes* dela existir.

**Correção aplicada (opção "a" das duas cogitadas no lessons-learned — setar a flag antes de invocar o último estágio):**

```python
# pipeline/runner.py — ANTES (bug)
for stage in PipelineStage.ordered():
    self._execute_stage(stage, ...)
state.completed = True   # <- setado só depois de TODAS as etapas, incluindo PACKAGING

# pipeline/runner.py — DEPOIS (corrigido)
stages = PipelineStage.ordered()
for stage in stages:
    if stage == PipelineStage.PACKAGING:
        # Se chegamos até aqui sem exceção não tratada, todas as etapas
        # anteriores tiveram sucesso ou skip — seta a flag ANTES de rodar
        # a última etapa, para que o PackagingAgent leia o valor correto.
        state.completed = all(
            s.status in ("success", "skipped") for s in state.stages
        )
    self._execute_stage(stage, ...)
```

**Status:** corrigido. Registrado como B9 na tabela principal do lessons-learned (Seção 2).

**Teste de regressão adicionado:** `test_packaging_reads_correct_completed_flag()` — roda o pipeline completo com um vídeo de fixture, intercepta o estado recebido por `PackagingAgent.run()`, e valida que `state.completed is True` no momento em que o Packaging o lê (não apenas ao final do processo todo).

---

## Parte 2 — Decisão de Escopo Já Aplicada: Remoção do Thumbnail Composer

Antes de pedir autorização para o restante, uma mudança de escopo que você já decidiu e que está refletida neste documento e no lessons-learned (nova entrada D12):

**O `ThumbnailComposerAgent` (fallback de geração de thumbnail por template/composição para vídeos sem conteúdo visual real) foi removido completamente do escopo.** Não entra em nenhuma versão futura, a menos que você reabra essa decisão explicitamente.

**Consequência prática:** a única correção que resta para o problema de thumbnail é ajustar o limiar de nitidez (`Laplacian var` de 100 para 50, ver B11 no lessons-learned). Para vídeos verdadeiramente estáticos (tela preta, caso real do seu uso), o comportamento passa a ser: `ThumbnailFramesAgent` retorna lista vazia, o pipeline **não falha**, e o relatório final mostra "0 thumbnails extraídos" sem tentar gerar nada no lugar. Isso já está formalizado como D12 no lessons-learned, incluindo o motivo (ferramenta pessoal, não vale a complexidade de manter um agente a mais para um caso de uso que você decidiu simplesmente aceitar).

O ajuste de limiar (100→50) em si é pequeno o suficiente para eu já aplicar como correção direta, junto com B8/B9 — nenhuma autorização adicional necessária. Está refletido no ajuste abaixo:

```python
# services/opencv_service.py — ajuste de threshold
SHARPNESS_THRESHOLD = 50  # antes: 100 — ainda insuficiente para vídeos totalmente estáticos,
                          # mas reduz falsos negativos em vídeos com alguma variação real de cena
```

---

## Parte 3 — Pedido de Autorização: Itens Restantes do Turno 7

Os 3 itens abaixo (dos 4 originais — o quarto era o Thumbnail Composer, já removido acima) envolvem mudança estrutural real: novo estágio de pipeline, novo schema, e/ou reescrita de lógica de detecção já existente. Por isso, ao contrário de B8/B9/limiar de thumbnail, **peço autorização explícita antes de desenvolver cada um.**

### Item A — Unificação da Detecção de Silêncio no `VideoEditAgent`

**Problema:** ainda sobra silêncio perceptível no vídeo cortado.

**Hipótese de causa raiz:** `VideoEditAgent` roda sua própria detecção de silêncio via `ffmpeg silencedetect`, **duplicando e potencialmente divergindo** da detecção que o VAD do Whisper já faz (D6 — VAD obrigatório).

**Mudança proposta:**
- Usar os timestamps de segmento do próprio VAD (já disponíveis em `TranscriptRaw`/`TranscriptCleaned`) como **fonte única de verdade** para decidir onde cortar — eliminar a segunda detecção via `ffmpeg silencedetect`.
- Padding assimétrico pequeno (~100-150ms) ao redor de cada trecho de fala, para não cortar "em cima" da palavra.
- Novo teste de QA automatizado: roda `silencedetect` sobre o vídeo de **saída** (já editado) para pegar regressões futuras — silêncio residual acima de um limiar configurável falha o teste.

**Impacto:** reescrita de `VideoEditAgent.run()` (lógica de corte), sem novo schema, sem novo estágio. Risco baixo a médio — muda uma etapa que já existe e já é testada.

**Autorizo o desenvolvimento deste item?**

---

### Item B — Novo Estágio: `MARKER_DETECTION` (Marcadores de Voz "corte"/"início")

**Funcionalidade nova:** o locutor sinaliza verbalmente "corte" antes de um erro de fala e "início" ao retomar; o pipeline remove automaticamente o trecho entre os dois marcadores (áudio e vídeo).

**Desenho proposto (retomando a análise anterior):**
- Novo estágio `MARKER_DETECTION`, entre `SPEECH_RECOGNITION` e `TRANSCRIPT_CLEANING` — **antes** da limpeza por LLM, para não arriscar que o LLM parafraseie as palavras de comando e elas deixem de casar com o termo esperado.
- Detecção por **match exato de segmento** (mesmo espírito de lista fechada do D2 — regex, não julgamento de LLM), termos configuráveis via `config.yaml` (`marker_cut_word: "corte"`, `marker_resume_word: "início"`).
- Separação clara de responsabilidades: uma função detecta e produz uma lista de pares `(corte_em, retoma_em)` — validando marcadores órfãos (um "corte" sem "início" correspondente deve gerar aviso, não falha silenciosa); o `VideoEditAgent` (já tocado pelo Item A) aplica os cortes de marcador **no mesmo passe de ffmpeg** que os cortes de silêncio, para não gerar dois reencodes.
- O segmento do próprio comando de voz ("corte", "início") também é removido do áudio final, não só o conteúdo entre eles.

**Impacto:** schema novo (`MarkerPair`, lista em `PipelineState`), agente novo (`MarkerDetectionAgent`), novo valor no enum `PipelineStage`, ajuste em `VideoEditAgent` para consumir os pares de marcador junto com os cortes de silêncio (dependência direta com o Item A — faz sentido implementar A antes de B). Risco médio — funcionalidade nova, mas isolada em uma etapa própria.

**Autorizo o desenvolvimento deste item?** *(recomendo implementar depois do Item A, pela dependência direta no `VideoEditAgent` unificado)*

---

### Item C — Curadoria de Shorts Mais Completa

**Problema:** os 4 shorts do teste real saíram quase uniformemente espaçados (125s/240s/360s/480s de um vídeo de 516s) — sinal de que o LLM está "distribuindo" cortes em vez de escolher por mérito real de conteúdo.

**Desenho proposto (retomando a análise anterior, com a ressalva já dada sobre não usar transcrições de terceiros):**
- Adicionar `hook_strength: float` (score numérico de força do gancho) a cada `ShortCandidate` no schema de `ContentIntelligenceResult` — sinal determinístico adicional ao lado do julgamento do LLM (mesmo princípio do D2: nunca confiar 100% no LLM sozinho quando dá para ter um segundo sinal barato).
- Seleção de candidatos **por capítulo/tópico** (usando os `Chapter` já gerados pelo próprio Content Intelligence) em vez de escolher do vídeo inteiro de uma vez — ataca diretamente o problema do espaçamento uniforme.
- Contagem de shorts escalando com a duração do vídeo (em vez de um número fixo), e espaçamento mínimo configurável entre candidatos.
- "Snap" de início/fim de cada short para o limite de frase mais próximo na transcrição limpa, evitando cortes no meio de uma frase.
- Em vez de colar transcrições literais de shorts virais de terceiros (descartado — custo de tokens alto, já bateu rate limit no Groq free tier no teste real, e risco de reproduzir conteúdo alheio no prompt versionado): um **"playbook" destilado de padrões reutilizáveis** (tipos de gancho, estruturas narrativas, duração ideal do gancho inicial) escrito por você ou por mim, sem transcrição de terceiros, incluído em `prompts/content_intelligence.md`.

**Impacto:** ajuste de schema (`ShortCandidate.hook_strength`), reescrita do prompt `content_intelligence.md`, ajuste em `ContentIntelligenceAgent` (chamada por capítulo em vez de uma chamada única) e em `TimelineValidatorAgent` (validar espaçamento mínimo). Sem novo estágio. Risco médio — muda a forma de chamar o LLM (de 1 chamada para N-por-capítulo), o que também muda o perfil de custo/tempo medido no teste real (mais chamadas, mas cada uma menor).

**Autorizo o desenvolvimento deste item?**

---

## Resumo da Solicitação

| Item | Ação | Autorização necessária? |
|---|---|---|
| B8 — nome de estágio como número | Corrigido nesta rodada | Não (já diagnosticado, correção direta) |
| B9 — relatório "Incompleto" indevido | Corrigido nesta rodada | Não (já diagnosticado, correção direta) |
| Ajuste de limiar de thumbnail (100→50) | Corrigido nesta rodada | Não (ajuste de parâmetro, sem mudança estrutural) |
| Thumbnail Composer | **Removido do escopo** (D12) | — (decisão sua já aplicada) |
| Item A — Unificação de silêncio | Aguardando autorização | **Sim** |
| Item B — `MARKER_DETECTION` | Aguardando autorização | **Sim** |
| Item C — Curadoria de shorts | Aguardando autorização | **Sim** |

Posso prosseguir com os itens A, B e C — todos, ou você prefere autorizar um de cada vez, na ordem sugerida (A → B → C, pela dependência entre A e B)?

---

*Fim da Segunda Rodada de Implementação.*
