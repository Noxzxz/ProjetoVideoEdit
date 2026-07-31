# Registro de Decisões e Bugs Já Corrigidos — Lessons Learned

> Pipeline de Pós-Produção com IA | Consolidado do ADR v3 (Relatório de Análise Crítica) + Changelog v1.1 do Documento de Desenvolvimento Completo.
> **Propósito deste documento:** registrar *por que* cada decisão/correção existe, para que um agente de código ou desenvolvedor futuro não a reverta acidentalmente ao "otimizar" ou "simplificar" o código sem esse contexto. Cada entrada segue o formato: **Sintoma/Contexto → Decisão/Correção → Por quê → Como não regredir.**

---

## Como usar este documento

Antes de alterar qualquer um dos módulos citados abaixo, verifique se a mudança proposta não reintroduz um problema já resolvido aqui. Se um agente de código sugerir "simplificar" algo que está descrito nesta lista, trate isso como um alerta — não como uma melhoria automática.

---

## 1. Decisões Arquiteturais (origem: ADR v3)

### D1 — Hardware Baseline e Modelos Homologados

- **Contexto:** Projeto nasceu "100% gratuito" sem hardware definido. Um LLM 7B exige ~4.2-4.8GB VRAM em 4-bit; somado ao Whisper (~1.5GB), excede uma GTX 1650 4GB.
- **Decisão:** Hardware oficial declarado (Ryzen 7 6000, GTX 1650 4GB, 32GB RAM, NVMe 1TB). Modelos homologados: `faster-whisper small` (GPU) + `Qwen2.5 3B` / `Gemma 2 2B` (CPU ou GPU leve). Modelos 7B+ nunca são requisito da V1.
- **Por quê:** Elimina OOM e expectativas irreais de performance; `small` é o sweet spot para PT-BR em 4GB VRAM (`base` impreciso, `medium` não cabe).
- **Como não regredir:** Não trocar o modelo default para `medium`/`large` nem para um LLM 7B+ sem antes confirmar que o hardware-alvo comporta ambos simultaneamente. Ver testes de viabilidade (Seção 4 deste documento).

### D2 — Limpeza de Transcrição: Regex + LLM (não LLM puro)

- **Contexto:** Limpeza original previa apenas LLM, gerando 300+ chamadas para 30 min de vídeo — inviável em CPU. Regex genérico sem word boundaries destrói palavras ("você **é**" → some o "é" de "planeta").
- **Decisão:** Regex com **lista fechada** (`hum`, `ah`, `ahn`, `ãhn`, `ehm`) e `\b` obrigatório. Palavras ambíguas (`é`, `tipo`, `né`) **nunca** entram no regex — só o LLM as avalia, com contexto.
- **Por quê:** Regex resolve ~80% do ruído em milissegundos, sem custo de inferência; restringir a uma lista fechada reduz a quase zero o risco de destruir conteúdo factual.
- **Como não regredir:** Nunca adicionar `é`/`tipo`/`né` (ou qualquer palavra ambígua semanticamente) à lista fechada de regex, mesmo que pareça "mais um caso simples de remover".

### D3 — Content Intelligence Unificado + Timeline Validator

- **Contexto:** SEO, Shorts, Thumbnail e Resumo eram 4 agentes separados (~4-9 chamadas LLM). O LLM também precisa ver os **timestamps reais** dos segmentos, não texto puro, para sugerir cortes precisos — e pode gerar timestamps inválidos (negativos, fora da duração, overlaps).
- **Decisão:** Um único agente `ContentIntelligenceAgent` recebe segmentos com timestamps e retorna `seo` + `shorts` + `thumbnail` + `summary` em 1-2 chamadas. Um módulo separado, `TimelineValidatorAgent`, corrige/descarta timestamps inválidos antes de qualquer corte real de vídeo.
- **Por quê:** Coerência temática (o LLM vê o conteúdo como um todo) + menos chamadas + isola o FFmpeg de erros de LLM.
- **Como não regredir:** Não voltar a dividir isso em agentes separados sem também replicar a validação de timeline centralizada — validação espalhada por agente é o padrão que gerou o problema original.

### D4 — PipelineRunner Sequencial (não LangGraph)

- **Contexto:** O fluxo real da V1 é 100% linear e single-user. LangGraph adicionava overhead de serialização e complexidade sem paralelismo real a explorar (naquele desenho).
- **Decisão:** Remover LangGraph. Orquestração via classe Python simples (`PipelineRunner`), com cache em JSON substituindo checkpoints de grafo.
- **Por quê:** Menos dependências, código mais simples de depurar via Vibe Coding.
- **Como não regredir:** Não reintroduzir LangGraph "para ficar mais elegante" sem uma necessidade real de paralelismo/múltiplos vídeos simultâneos que justifique a complexidade de volta.
- **Nota de evolução (v1.1):** Esta decisão foi refinada, não revertida — ver B7 abaixo: um paralelismo real (via `ThreadPoolExecutor`, não framework de grafo) foi introduzido para o trio de etapas mutuamente independentes.

### D5 — Pre-flight Check (System Check)

- **Contexto:** Descobrir que o Ollama está offline após 10 minutos de transcrição é frustrante e desperdiça tempo, especialmente para usuários leigos.
- **Decisão:** `PreFlightCheck` roda antes de qualquer processamento, validando GPU, FFmpeg+codecs, Ollama respondendo, modelos baixados, espaço em disco, versão do Python, CUDA. Aborta com mensagem clara em português se algo falhar.
- **Por quê:** Fail fast evita 90% dos problemas de suporte.
- **Como não regredir:** Não pular o Pre-flight Check "para acelerar a inicialização" — o custo é de poucos segundos; o ganho evita minutos/horas de processamento desperdiçado.

### D6 — VAD Obrigatório no Whisper

- **Contexto:** Sem VAD, o Whisper transcreve música de fundo, ruído e silêncio como se fossem fala, gerando alucinações que se propagam para toda a cadeia downstream.
- **Decisão:** `vad_filter=True` como padrão obrigatório, não exposto como opção desabilitável na V1.
- **Por quê:** Custo computacional insignificante frente ao ganho de qualidade; casos de borda (ASMR/sussurro) não justificam a complexidade de configuração ainda.
- **Como não regredir:** Não desabilitar VAD por padrão nem tornar isso configurável na V1 só porque um caso de uso específico pediu — isso é explicitamente adiado para V2.

### D7 — Cache com Reprocessamento Parcial

- **Contexto:** Reprocessar 1h de vídeo do zero só para ajustar o tom do SEO é inviável.
- **Decisão:** Cache em arquivos JSON por hash de vídeo (`cache/<hash>/*.json`), com flags `--from <etapa>` e `--force`.
- **Por quê:** Iteração rápida sem Redis/banco de cache adicional — arquivo no NVMe já é suficiente para uso single-user.
- **Como não regredir:** Não migrar o cache para um banco/serviço externo sem necessidade real de multiusuário — isso reintroduziria a complexidade que essa decisão evitou deliberadamente.

### D8 — Configuração Única (`config.yaml` + `prompts/*.md`)

- **Contexto:** Configuração dispersa entre `.env`, `config.yaml` e prompts hardcoded no código dificultava ajustes por não-programadores.
- **Decisão:** Um único `config.yaml` (formato **flat**, sem aninhamento) + prompts de sistema externos em `prompts/*.md`, carregados em runtime.
- **Por quê:** Fonte única de verdade; facilita A/B testing de prompts (trocar um `.md` e reexecutar) sem tocar em código.
- **Como não regredir:** Não aninhar campos no `Settings` Pydantic (regra fixa, ver Notas para Vibe Coding do documento-fonte) e não voltar a hardcodar prompt de sistema com mais de 2 linhas dentro de um agente.

### D9 — Burn-in de Legenda Removido do Escopo da V1

- **Contexto:** Queimar legenda estilizada no vídeo era uma Epic inteira com complexidade de fontes/libass e risco de falha silenciosa.
- **Decisão:** V1 entrega apenas `.srt`/`.vtt`. Burn-in fica para o Roadmap (pós-V1).
- **Por quê:** Simplifica a V1 sem perder o valor essencial (o usuário ainda recebe legenda pronta, só precisa aplicá-la em um editor externo se quiser o vídeo "queimado").
- **Como não regredir:** Não reintroduzir burn-in "de brinde" no meio de outra Epic sem tratá-lo como uma Epic própria, com sua análise de risco (ex. fonte ausente no ambiente do usuário).

---

## 1b. Sessão de Planejamento — Nicho World of Darkness (D16-D26)

> Origem: `Decisoes_Validadas_Sessao_Planejamento_WoD.md`. As entradas D16-D25 foram **validadas e implementadas** (commits `967791c`, `2b7eae4`, `3582b0c`). D26 é **proposta em aberto** (não fechada). A numeração continua de D15 (ver resumo no `RESUMO_PLANEJAMENTO.md`); D10-D15 permanecem lá resumidos.
> **Contexto de negócio:** o pipeline é usado para pré-edição de um canal de nicho de **World of Darkness** (sessões de RPG de mesa, mecânica, lore, podcast). Vídeos gravados *audio-first* — a imagem é adicionada em pós-produção. Por isso o vídeo é tratado como **inexistente ou irrelevante** no momento do processamento.

### D16 — Remoção completa da extração de thumbnail via OpenCV (sem substituto na V1)

- **Contexto:** `ThumbnailFramesAgent` extraía frames candidatos via variância de Laplaciano. No nicho WoD (mesa fixa/tela preta) 13min22s de processamento para frames que nunca são "a melhor imagem" — não existe frame melhor que outro em conteúdo estático.
- **Decisão:** Remover **inteiramente** a etapa de thumbnail — sem extração por frame, sem fallback por template (descartado explicitamente pelo usuário).
- **Por quê:** Libera orçamento de tempo para o Content Intelligence (D17). Decisão específica ao formato *audio-first*, não limitação técnica.
- **Como não regredir:** Não reintroduzir extração por frame "de brinde" sem confirmar que o canal passou a gravar conteúdo visual variável.
- **Implementado:** agente/serviço/prompt/`opencv-python`/enum/testes removidos; `PARALLEL_GROUP` agora tem 2 membros (`SUBTITLE_STYLING`, `SHORTS_EXTRACTION`); `ContentIntelligenceResult.thumbnail_suggestions` virou sugestão textual (sem processamento de vídeo).

### D17 — Cobertura total do vídeo via chunking (map-reduce), substituindo truncamento

- **Contexto:** `_format_transcript(transcript, max_segments=400)` trunca os primeiros 400 segmentos — em sessões de 2h45min+ cobre ~15min, concentrando capítulos e shorts no começo.
- **Decisão:** Dividir a transcrição em chunks de ~20-30min. Uma passada de candidatos por chunk e **uma chamada final de consolidação** (recebe só os candidatos, não a transcrição inteira) que decide capítulos finais + SEO global.
- **Por quê:** Cobre o vídeo inteiro sem estourar a janela de contexto do modelo local (Qwen 3B/Gemma 2B).
- **Como não regredir:** Nunca voltar a um `max_segments` fixo que trunca; qualquer "resumir tudo em 1 chamada" deve usar map-reduce. Trade-off explícito: mais chamadas LLM (rate limit em free tier) — mitigado por `LLM_CALL_DELAY_SECONDS` e Ollama local (D26).
- **Implementado:** `_split_into_chunks` + consolidação em `prompts/content_consolidation.md` com fallback para o melhor SEO por chunk (nunca vazio).

### D18 — Curadoria de shorts em dois passos: identificação narrativa + ancoragem determinística

- **Contexto:** Shorts "sem nexo" — cortes no meio de frase, escolhidos por tópico em vez de arco completo.
- **Decisão:** Dois passos: (1) **Identificação (LLM)** por capítulo com `momento`/`gancho`/`payoff`/`emocao` (gancho/payoff devem ser texto **literal** da transcrição); (2) **Ancoragem (determinística, sem LLM)** por similaridade do gancho/payoff contra segmentos cronometrados. Candidatos sem match são descartados (anti-alucinação).
- **Por quê:** Replica o padrão D2 (determinístico resolve o volume, LLM só julga). Auto-valida alucinação sem chamada extra de verificação.
- **Como não regredir:** Nunca pedir timestamp direto do LLM para short; ancoragem texto-contra-segmento é obrigatória para qualquer corte derivado de julgamento de LLM.
- **Implementado:** `utils/shorts_anchoring.py` + `prompts/shorts_prompt.md` reescrito em 2 passos. **Bug crítico corrigido na implementação:** `run_stage` não passava `video_hash`, anulando a ancoragem (shorts sempre vazios).

### D19 — Crítico de autocontenção (self-containment check) para candidatos finais de short

- **Contexto:** Mesmo com arco completo, um trecho pode depender de contexto dito minutos antes (ex: NPC apresentado há 40min).
- **Decisão:** Chamada LLM barata (recebe só o trecho já cortado) que avalia se é compreensível sozinho e aponta o que falta. Roda **depois** da ancoragem (D18), sobre os poucos candidatos finais.
- **Por quê:** Mesmo padrão do `TimelineValidatorAgent` (D3) — separar geração de validação, agora sobre qualidade narrativa.
- **Como não regredir:** Este passo nunca roda sobre todos os candidatos brutos — só sobre finais, para não multiplicar custo.
- **Implementado:** `prompts/standalone_check_prompt.md` + `_check_standalone` + filtro `SHORTS_MIN_STANDALONE_SCORE` (default 0.5) + re-ranking ponderado.

### D20 — Hotwords/glossário de vocabulário de sistemas WoD

- **Contexto:** Termos de sistema (Camarilla, Frenzy, Auspex...) não são vocabulário comum em PT-BR; Whisper transcreve foneticamente errado e o LLM pode "corrigir" pior.
- **Decisão:** Duas camadas: (1) `initial_prompt`/hotwords do `faster-whisper` enviesando a transcrição; (2) glossário determinístico de correção fuzzy (Levenshtein) rodando **entre** `SPEECH_RECOGNITION` e `TRANSCRIPT_CLEANING`.
- **Por quê:** Corrigir na fonte é mais barato que corrigir depois; mesmo padrão D2.
- **Como não regredir:** O glossário nunca inclui palavras ambíguas do português comum — só termos técnicos do sistema, sem risco de falso positivo.
- **Implementado:** `glossaries/{vampiro,lobisomem,mago}.md`, `utils/glossary_correction.py`, `WHISPER_INITIAL_PROMPT`/`GLOSSARY_NAME`.

### D21 — Detecção de pico de energia de áudio como sinal complementar para candidatos a short

- **Contexto:** Sessão de RPG tem assinatura acústica de clímax (rolagem, gritaria) — sinal de emoção real, mais barato que inferência textual.
- **Decisão:** Calcular energia RMS (determinístico, sem LLM) e usar picos como **segundo critério** ao lado da identificação narrativa (D18) — somando, não substituindo.
- **Como não regredir:** Nunca usar picos de RMS como único critério (ruído/tosse também gera pico) — sempre cruzar com a identificação narrativa.
- **Implementado:** `services/audio_analysis_service.py` (stdlib `wave`, sem numpy); picos entram como contexto no prompt de shorts por capítulo.

### D22 — Classificação de tipo de conteúdo direcionando critério de curadoria de shorts

- **Contexto:** Sessão, mecânica, lore e podcast têm estruturas de "bom corte" diferentes; um critério único de "short viral" falha em conteúdo educativo/lore.
- **Decisão:** Campo `content_type` manual (sessão/mecânica/lore/podcast) com critério de curadoria distinto por tipo no `shorts_prompt.md`.
- **Como não regredir:** Ao adicionar novo tipo de vídeo, definir o critério específico antes de rodar o pipeline — não assumir que o critério de sessão serve para tudo.
- **Implementado:** `CONTENT_TYPE` no Settings + seções condicionais no prompt.

### D23 — Contexto de campanha persistente entre episódios

- **Contexto:** O canal produz uma campanha contínua, mas o agente trata cada execução como unidade isolada.
- **Decisão:** Arquivo `campanha/<nome_da_cronica>.md` (PCs/NPCs recorrentes, resumo dos eventos) injetado como contexto extra na **fase de consolidação** do D17.
- **Como não regredir:** O arquivo de campanha é atualizado **manualmente** pelo usuário entre episódios — não é gerado automaticamente na V1.
- **Implementado:** `campanha/exemplo_cronica.md` + `CAMPAIGN_CONTEXT_FILE`.

### D24 — Vocabulário controlado de hashtags por linha de jogo

- **Contexto:** Hashtags geradas livremente são inconsistentes entre episódios, prejudicando descoberta/agrupamento.
- **Decisão:** Lista curada por linha de jogo, da qual o LLM escolhe, complementando com 1-2 tags livres específicas do episódio.
- **Como não regredir:** Não deixar a lista controlada crescer sem curadoria manual — o valor está em ser pequena e consistente.
- **Implementado:** `glossaries/hashtags_vampiro.md` + `HASHTAGS_FILE` + instrução no prompt de consolidação.

### D25 — Extensão do MARKER_DETECTION para conteúdo fora de personagem (OOC)

- **Contexto:** Sessão real tem momentos fora do jogo (pausa, discussão de regra, comentário) que não devem ir para o vídeo público nem para shorts.
- **Decisão:** Segundo par de palavras-chave (`OOC_PAUSE_WORD`/`OOC_RESUME_WORD`, ex. `"pausa"`/`"retomando"`), tratado separadamente do corte de erro de fala. OOC é excluído do corte físico **e** da curadoria de shorts.
- **Como não regredir:** Os dois pares são listas **distintas e configuráveis** — nunca misturar a lógica, pois o tratamento downstream difere (erro de fala é removido do vídeo final; OOC sempre excluído de shorts).
- **Nota:** `MARKER_CUT_WORD` confirmado como `"corte"` no Settings (o `"cor"` do `RESUMO_PLANEJAMENTO.md` era erro de digitação do resumo).
- **Implementado:** `MarkerPair.kind` (`erro_fala`/`ooc`), detecção dupla em `marker_detection`, exclusão de OOC na curadoria.

### D26 (proposta, não validada) — Paralelizar chunks do map-reduce (D17) contra Ollama local

- **Proposta:** processar os chunks em paralelo contra o Ollama (reaproveitando o padrão `ThreadPoolExecutor`), em vez de sequencial.
- **Por que não é decisão fechada:** falta validar quanta concorrência a GPU de 4GB aguenta antes de virar padrão (risco de OOM ou de degradar o tempo por chamada a ponto de anular o ganho).
- **Ação necessária para fechar:** testar 2-3 chamadas concorrentes ao Ollama local em chunks reais, medir VRAM e tempo por chamada, comparar com sequencial.

---

## 2. Bugs Já Corrigidos (origem: Changelog v1.1)

Estes já eram problemas **reais identificados em código de exemplo**, corrigidos antes do início da implementação. Tratá-los como "hipotéticos" é o erro mais fácil de cometer — eles já se manifestaram uma vez.

| # | Sintoma | Causa raiz | Correção aplicada | Módulo/Regra de não-regressão |
|---|---|---|---|---|
| B1 | Resume (`--from`) quebrava silenciosamente — agentes liam/escreviam cache em diretórios diferentes | `generate_video_id()` truncava o hash para 8 caracteres enquanto `PipelineRunner`/`VideoProcessingAgent` usavam o hash completo (16 caracteres) | Centralizada a extração do hash em `utils/hash_utils.get_video_hash_from_id()`, usada por **todos** os agentes | Nunca reimplementar lógica de hash em um agente individual — sempre importar de `utils/hash_utils.py` |
| B2 | `analytics.json` corrompido — cada etapa gerava **dois** registros no histórico | Cada `run_stage()` de agente fazia seu próprio `state.stages.append(...)`, e o `PipelineRunner` também fazia o append | Removido o append de dentro dos 10 agentes; registro de `StageResult` é responsabilidade **exclusiva** do `PipelineRunner` | `run_stage()` de agente nunca chama `state.stages.append(...)` — teste de regressão obrigatório: após um `run()` completo, `state.stages` tem exatamente 1 entrada por etapa |
| B3 | Carregar `PipelineState`/`StageResult` do cache em disco podia falhar (`ValidationError`) | `strict=True` rejeitava a coerção automática `str→Path`/`str→datetime` que `json.load` sempre produz (JSON só tem strings) | Removido `strict=True` desses dois schemas especificamente (mantido nos demais, que não fazem esse round-trip disco→objeto) | Nunca adicionar `strict=True` a `PipelineState`/`StageResult`; teste de regressão obrigatório: salvar → recarregar → todos os campos batem |
| B4 | Risco de segurança no parsing de FPS (`ffmpeg_service.py`) | Uso de `eval()` sobre string vinda de metadata externa (`r_frame_rate`, ex. `"30000/1001"`) | Substituído por `fractions.Fraction(fps_str)` | Nunca usar `eval()` sobre qualquer dado vindo de fonte externa, mesmo "normalmente confiável" (ffprobe) |
| B5 | Vídeos de 20-30 min inviáveis em CPU — processamento levaria horas | `TranscriptCleanerAgent` fazia **1 chamada LLM por segmento** (centenas de chamadas por vídeo) | Reescrito para processar em **batches de 25 segmentos por chamada**, com checkpoint parcial (`cleaned.partial.json`) para não reprocessar tudo em caso de falha no meio | Nunca voltar a fazer 1 chamada LLM por segmento; qualquer nova etapa de LLM sobre texto longo deve, por padrão, processar em lote |
| B6 | Vazamento de VRAM em sessões longas do Streamlit (processo não reinicia entre vídeos) | Nenhuma gestão explícita de descarregamento do modelo Whisper da GPU | Adicionado `unload_whisper_model()`, chamado ao final da etapa `SPEECH_RECOGNITION` | Toda etapa que carrega modelo em VROM/GPU deve ter uma função de unload simétrica, chamada ao fim da etapa — não só o Whisper |
| B7 | Tempo total do pipeline mais alto que o necessário | `SUBTITLE_STYLING`, `THUMBNAIL_FRAMES` e `SHORTS_EXTRACTION` não dependem umas das outras, mas rodavam sequencialmente | `PipelineRunner` agora agrupa e executa esse trio em paralelo via `ThreadPoolExecutor` (`PARALLEL_GROUP`) | Antes de adicionar uma nova etapa a esse pipeline, verificar se ela realmente depende do output de outra etapa ou se pode entrar no grupo paralelo |

---

## 3. Riscos Conhecidos Ainda Em Aberto (não são bugs corrigidos — são apostas não validadas)

| Risco | Por que ainda é uma aposta | Ação necessária antes de confiar na arquitetura |
|---|---|---|
| Qwen2.5 3B pode ser lento demais no hardware-alvo | Nenhum benchmark real foi rodado ainda — só a estimativa de "deveria caber" | Rodar teste com prompt de ~2000 tokens; se > 60s, considerar fallback (Groq/OpenRouter) só para o Content Intelligence, mantendo Whisper local |
| faster-whisper `small` pode não atingir o tempo esperado em GPU 4GB | Estimativa teórica, não medida no hardware real | Medir 30 min de áudio real na GTX 1650; meta é < 5 min |
| Corte de silêncio pode gerar erro de sincronismo A/V em alguns codecs | `-c copy` nem sempre é seguro dependendo de keyframes do vídeo de entrada | Testar com vídeos de diferentes codecs/origens antes de assumir que o fallback de reencode nunca é necessário |

---

## 4. Testes de Regressão Obrigatórios (consolidado)

Estes testes existem especificamente porque um dos bugs acima já aconteceu uma vez — não são testes "de boa prática genérica", são proteção direta contra B1, B2 e B3:

1. **Hash consistente:** `get_video_hash_from_id(generate_video_id(...))` retorna exatamente o hash original, para todo agente que dependa disso. *(protege contra B1)*
2. **Um `StageResult` por etapa:** após `PipelineRunner.run()` completo, `state.stages` tem exatamente 1 entrada por etapa executada, nunca 2. *(protege contra B2)*
3. **Round-trip de estado:** salvar `PipelineState` em disco → recarregar → todos os campos (`Path`, `datetime`, `output_paths`) batem sem erro de validação. *(protege contra B3)*

---

*Fim do Registro de Decisões e Bugs Já Corrigidos.*
