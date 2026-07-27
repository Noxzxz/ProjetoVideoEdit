# Registro de Decisões e Bugs Já Corrigidos — Lessons Learned

> Pipeline de Pós-Produção com IA | Consolidado do ADR v3 (Relatório de Análise Crítica) + Changelog v1.1 do Documento de Desenvolvimento Completo + `RELATORIO_IMPLEMENTACAO.md` (teste real de 8min36s, PC sem GPU, provedor Groq).
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

## 2. Bugs Já Corrigidos (origem: Changelog v1.1)

Estes já eram problemas **reais identificados em código de exemplo**, corrigidos antes do início da implementação. Tratá-los como "hipotéticos" é o erro mais fácil de cometer — eles já se manifestaram uma vez.

| # | Sintoma | Causa raiz | Correção aplicada | Módulo/Regra de não-regressão |
|---|---|---|---|---|
| B1 | Resume (`--from`) quebrava silenciosamente — agentes liam/escreviam cache em diretórios diferentes | `generate_video_id()` truncava o hash para 8 caracteres enquanto `PipelineRunner`/`VideoProcessingAgent` usavam o hash completo (16 caracteres) | Centralizada a extração do hash em `utils/hash_utils.get_video_hash_from_id()`, usada por **todos** os agentes | Nunca reimplementar lógica de hash em um agente individual — sempre importar de `utils/hash_utils.py` |
| B2 | `analytics.json` corrompido — cada etapa gerava **dois** registros no histórico | Cada `run_stage()` de agente fazia seu próprio `state.stages.append(...)`, e o `PipelineRunner` também fazia o append | Removido o append de dentro dos 10 agentes; registro de `StageResult` é responsabilidade **exclusiva** do `PipelineRunner` | `run_stage()` de agente nunca chama `state.stages.append(...)` — teste de regressão obrigatório: após um `run()` completo, `state.stages` tem exatamente 1 entrada por etapa |
| B3 | Carregar `PipelineState`/`StageResult` do cache em disco podia falhar (`ValidationError`) | `strict=True` rejeitava a coerção automática `str→Path`/`str→datetime` que `json.load` sempre produz (JSON só tem strings) | Removido `strict=True` desses dois schemas especificamente (mantido nos demais, que não fazem esse round-trip disco→objeto) | Nunca adicionar `strict=True` a `PipelineState`/`StageResult`; teste de regressão obrigatório: salvar → recarregar → todos os campos batem |
| B4 | Risco de segurança no parsing de FPS (`ffmpeg_service.py`) | Uso de `eval()` sobre string vinda de metadata externa (`r_frame_rate`, ex. `"30000/1001"`) | Substituído por `fractions.Fraction(fps_str)` | Nunca usar `eval()` sobre qualquer dado vindo de fonte externa, mesmo "normalmente confiável" (ffprobe) |
| B5 | Vídeos de 20-30 min inviáveis em CPU — processamento levaria horas | `TranscriptCleanerAgent` fazia **1 chamada LLM por segmento** (centenas de chamadas por vídeo) | Reescrito para processar em **batches de 15 segmentos por chamada** *(valor real da implementação — corrige o "25" registrado nas versões anteriores deste documento e na Referência Rápida de Contratos; ver Nota de Sincronização após esta tabela)*, com checkpoint parcial (`cleaned.partial.json`) para não reprocessar tudo em caso de falha no meio | Nunca voltar a fazer 1 chamada LLM por segmento; qualquer nova etapa de LLM sobre texto longo deve, por padrão, processar em lote |
| B10 | Resposta do LLM no caminho de sucesso da limpeza vinha sem score de confiança, quebrando o contrato `TranscriptSegment` | Código esquecia de repassar `confidence=seg.confidence` do segmento original ao montar o segmento limpo | Adicionado `confidence=seg.confidence` na montagem do segmento de saída | Qualquer refatoração do `TranscriptCleanerAgent` deve testar explicitamente que todos os campos de `TranscriptSegment` (não só `text`) sobrevivem ao caminho de sucesso do LLM, não só ao caminho de fallback |
| B8 | Relatório final mostrava o nome do estágio como número (ex. `7` em vez de `SUBTITLE_STYLING`) especificamente nos estágios do bloco paralelo | O caminho de execução paralela (`ThreadPoolExecutor`) registrava o estágio usando o valor do enum (`.value`, int) em vez de `.name` — o caminho sequencial não tinha esse problema | Padronizado: todo registro de estágio (sequencial ou paralelo) usa `PipelineStage(x).name` | Nenhum ponto do código deve registrar/logar um `PipelineStage` pelo valor bruto do enum — sempre `.name` |
| B9 | Relatório final mostrava status "Incompleto" mesmo em execuções com 100% de sucesso | `PackagingAgent` lia `state.completed`, mas essa flag só era setada `True` pelo `PipelineRunner` **depois** que todos os estágios — incluindo o próprio PACKAGING (o último) — retornavam; o Packaging sempre lia a flag antes dela existir | `PipelineRunner` agora seta `completed=True` **antes** de invocar o último estágio, já sabendo que todos os anteriores tiveram sucesso (opção "a" das duas cogitadas) | Nenhuma etapa deve depender de uma flag de "conclusão total" que só é setada depois da própria etapa rodar — se uma etapa precisa saber o status agregado, ele deve estar disponível antes dela ser invocada |
| B6 | Vazamento de VRAM em sessões longas do Streamlit (processo não reinicia entre vídeos) | Nenhuma gestão explícita de descarregamento do modelo Whisper da GPU | Adicionado `unload_whisper_model()`, chamado ao final da etapa `SPEECH_RECOGNITION` | Toda etapa que carrega modelo em VROM/GPU deve ter uma função de unload simétrica, chamada ao fim da etapa — não só o Whisper |
| B7 | Tempo total do pipeline mais alto que o necessário | `SUBTITLE_STYLING`, `THUMBNAIL_FRAMES` e `SHORTS_EXTRACTION` não dependem umas das outras, mas rodavam sequencialmente | `PipelineRunner` agora agrupa e executa esse trio em paralelo via `ThreadPoolExecutor` (`PARALLEL_GROUP`) | Antes de adicionar uma nova etapa a esse pipeline, verificar se ela realmente depende do output de outra etapa ou se pode entrar no grupo paralelo |

> **Nota de Sincronização (pós-teste real de 8min36s):** o valor "25 segmentos por lote" registrado nas seções D2/B5 deste documento e na Referência Rápida de Contratos **estava desatualizado**. A implementação real usa **15 segmentos por lote** — valor confirmado no `RELATORIO_IMPLEMENTACAO.md` (18 lotes para 255 segmentos = 8min36s de vídeo). Corrigido acima; **a Referência Rápida de Contratos precisa do mesmo ajuste** (pendente, ver Seção 3).

### 2.1 Bugs Identificados em Teste Real — Pendentes de Correção

Estes dois foram diagnosticados durante o teste real de 8min36s e **corrigidos na Segunda Rodada de Implementação** — ver `Segunda_Rodada_de_Implementacao.md` para o detalhe do patch aplicado a cada um. Movidos para a tabela principal (Seção 2) como B8/B9.

**Novo achado, também pendente (candidato a B11):** critério de nitidez do `ThumbnailFramesAgent` (`Laplacian var ≥ 100`) é restritivo demais — no teste real, 0 frames foram selecionados de um vídeo inteiro. Isso se soma ao problema de fundo já identificado em conversa anterior (vídeos de bate-papo com tela preta não têm de fato conteúdo visual variável a extrair). Correção proposta: baixar para `Laplacian var ≥ 50`. **Decisão do usuário (Segunda Rodada de Implementação): o fallback de composição por template (`ThumbnailComposerAgent`) foi removido completamente do escopo** — não será implementado. Para vídeos sem conteúdo visual real (tela preta), o comportamento aceito é **0 frames extraídos, sem geração de imagem substituta** — a etapa apenas registra isso no relatório final, sem falhar o pipeline. Ver D12 na Seção 3.

---

## 3. Novas Decisões Arquiteturais Confirmadas em Implementação Real

Estas duas decisões existem no código real (`RELATORIO_IMPLEMENTACAO.md`) mas não estavam em nenhum documento de arquitetura anterior deste projeto — registradas aqui para sincronizar.

### D10 — Abstração `LLMProvider` Plugável (Ollama / Gemini / Groq)

- **Contexto:** Rodar o Content Intelligence e a limpeza de transcrição só em Ollama local exige hardware capaz (D1); em hardware mais fraco ou sem GPU, isso é inviável.
- **Decisão:** Interface `LLMProvider(ABC)` com um único método `generate(system_prompt, user_prompt, temperature, json_mode, timeout) -> str`, com 3 implementações intercambiáveis: `OllamaProvider`, `GeminiProvider`, `GroqProvider` (compatível OpenAI, com retry automático para HTTP 429). Seleção via `get_provider()`, lendo `settings.llm_provider`.
- **Por quê:** Mantém Ollama como default gratuito/local, mas permite fallback em nuvem gratuita sem reescrever os agentes — exatamente a mitigação que já havia sido cogitada (ver conversa anterior sobre Ollama vs. nuvem) e agora está implementada.
- **Como não regredir:** Nenhum agente deve chamar um provedor de LLM diretamente (`requests.post` para a API do Ollama, por exemplo) — sempre passar por `LLMProvider`/`get_provider()`.
- **Risco medido no teste real:** o free tier do Groq (6.000 TPM) já se mostrou insuficiente para vídeos de 1h — ver estimativa na Seção 4.

### D11 — Importação de Transcrição Externa (`--transcript` / `--srt` / `--vtt`)

- **Contexto:** Nem todo vídeo precisa passar pelo Whisper — o usuário pode já ter uma transcrição pronta (de outra ferramenta, ou de uma edição manual).
- **Decisão:** Flags de CLI que permitem pular `VIDEO_PROCESSING` e `SPEECH_RECOGNITION`. `PipelineRunner._import_transcript()` parseia o arquivo (SRT/VTT/JSON), salva como `cache/<hash>/transcript.json`, gera um `metadata.json` mínimo com duração inferida dos timestamps, marca as duas primeiras etapas como concluídas e ajusta `current_stage` para `TRANSCRIPT_CLEANING`.
- **Por quê:** Evita reprocessar Whisper (o maior gargalo em CPU, ver Seção 4) quando a transcrição já existe por outro meio.
- **Como não regredir:** O `metadata.json` gerado por importação é **mínimo** (duração inferida, não real do vídeo) — qualquer etapa que dependa de metadados completos do vídeo (fps, codec, resolução) precisa tratar esse caso como dado potencialmente incompleto, não assumir que sempre veio do `VideoProcessingAgent`.

### D12 — Thumbnail Composer Removido do Escopo (decisão explícita do usuário)

- **Contexto:** Para vídeos de bate-papo/podcast sem conteúdo visual real (tela preta), a extração de frame via OpenCV nunca vai funcionar bem. A ideia inicialmente cogitada (Turno 7 da conversa anterior) era um `ThumbnailComposerAgent` — gerar uma thumbnail por template/composição (Pillow: fundo + texto do gancho) como fallback quando nenhum frame aproveitável fosse encontrado.
- **Decisão:** Essa ideia foi **descartada por decisão explícita do usuário** (Segunda Rodada de Implementação) — não será implementada em nenhuma versão futura, a menos que reaberta explicitamente.
- **Por quê:** Decisão de escopo do dono do projeto — projeto é uma ferramenta pessoal (D-não-numerada: "não é produto escalável"), e o valor de gerar uma thumbnail de rascunho automática não justificou a complexidade adicional (dependência de Pillow, lógica de composição, mais um agente para manter).
- **Comportamento resultante:** Quando `ThumbnailFramesAgent` não encontra nenhum frame que passe no critério de nitidez (mesmo após o ajuste do limiar, ver B11), a etapa **retorna lista vazia sem falhar o pipeline**, e isso é refletido no `analytics.json`/relatório final como "0 thumbnails extraídos" — nenhuma imagem é sintetizada como substituta.
- **Como não regredir:** Não reintroduzir geração de thumbnail sintética (por template, por IA de imagem, ou qualquer outra forma) sem antes confirmar explicitamente com o usuário que a decisão D12 foi revertida — esta não é uma lacuna técnica esquecida, é uma escolha deliberada de escopo.

### D13 — Detecção de Silêncio Unificada no VAD (Terceira Rodada, Item A)

- **Contexto:** `VideoEditAgent` rodava sua própria detecção via `ffmpeg silencedetect`, duplicando e podendo divergir do VAD do Whisper (D6), causando silêncio residual no vídeo cortado.
- **Decisão:** `ffmpeg silencedetect` removido do `VideoEditAgent`. Fonte única de verdade sobre onde há fala: os segmentos do VAD (`TranscriptSegment.start/end`). Padding assimétrico configurável (`silence_pre_padding_ms`, `silence_post_padding_ms`).
- **Por quê:** Duas detecções independentes do mesmo fenômeno é a própria causa raiz de divergência — unificar elimina a classe de bug, não só o sintoma.
- **Como não regredir:** Nenhuma etapa deve reimplementar detecção de silêncio própria — sempre derivar de `TranscriptSegment`. Teste de regressão `test_output_video_has_no_long_silence` roda `silencedetect` sobre o vídeo de **saída** para pegar qualquer regressão futura.

### D14 — Novo Estágio `MARKER_DETECTION` (Terceira Rodada, Item B)

- **Contexto:** Funcionalidade nova solicitada pelo usuário — remover automaticamente trechos de fala marcados verbalmente ("corte" ... "início").
- **Decisão:** Estágio dedicado `MARKER_DETECTION`, entre `SPEECH_RECOGNITION` e `TRANSCRIPT_CLEANING`, com match exato de segmento (lista fechada, mesmo espírito do D2) sobre o texto **bruto** do Whisper — nunca sobre texto já limpo pelo LLM.
- **Por quê:** Rodar depois da limpeza por LLM arrisca que o modelo parafraseie/remova as palavras de comando, quebrando o match exato.
- **Como não regredir:** Não mover `MARKER_DETECTION` para depois de `TRANSCRIPT_CLEANING` mesmo que pareça "mais natural" no fluxo — a ordem é uma decisão deliberada de robustez, não um detalhe de implementação. Marcador órfão (sem par) nunca deve falhar o pipeline — apenas gerar aviso.

### D15 — Curadoria de Shorts por Capítulo + Score de Gancho (Terceira Rodada, Item C)

- **Contexto:** Teste real mostrou shorts quase uniformemente espaçados (125s/240s/360s/480s de 516s) — sinal de que o LLM distribui cortes em vez de escolher por mérito de conteúdo.
- **Decisão:** `ContentIntelligenceAgent` passa de 1 chamada única para 2 fases: (1) SEO/capítulos/resumo em 1 chamada; (2) candidatos de short **por capítulo**, cada um com `hook_strength` (score determinístico adicional ao lado do julgamento do LLM). Contagem-alvo de shorts escalando com a duração do vídeo (fórmula no código, não no LLM). `TimelineValidatorAgent` ganha a responsabilidade de impor espaçamento mínimo e fazer snap para limite de frase.
- **Por quê:** Pedir candidatos por trecho temático elimina a possibilidade de "distribuição uniforme sem mérito" — cada capítulo é avaliado isoladamente. Mesmo princípio do D2: um sinal determinístico (fórmula de contagem, espaçamento mínimo) ao lado do julgamento do LLM, nunca confiar 100% nele sozinho.
- **Como não regredir:** Não voltar a pedir todos os shorts do vídeo inteiro em 1 chamada única — isso é exatamente o padrão que causou o problema original. Rejeitado explicitamente: usar transcrições literais de shorts virais de terceiros como exemplo no prompt (custo de tokens alto, já bateu rate limit no teste real com Groq free tier, e risco de reproduzir conteúdo alheio em um prompt versionado) — no lugar, um playbook de padrões genéricos escrito para este projeto.
- **Pendência conhecida:** os pesos `0.6`/`0.4` (hook_strength vs. score) na fórmula de ranqueamento são um ponto de partida, não um valor validado — ajustável em `config.yaml`.

---

## 4. Riscos Conhecidos — Atualizados com Medições Reais (substituindo estimativas teóricas)

O teste real de 8min36s (PC mais fraco que o hardware-alvo, sem GPU, Whisper em CPU, Groq como provedor) substitui as estimativas da versão anterior deste documento por números medidos:

| Risco | Estimativa anterior (teórica) | Medição real | Conclusão |
|---|---|---|---|
| Whisper `small` em CPU | "confirmar se cabe no tempo esperado" | 8min36s de vídeo → **~5 min** de transcrição em CPU (sem GPU) | Extrapolando: **1h de áudio ≈ 3-4h em CPU pura** — este é o gargalo real do pipeline, não o LLM |
| Qwen2.5 3B / LLM em geral | "confirmar se responde em <60s para 2000 tokens" | Cleaning (18 lotes) ≈ **3 min**; Content Intelligence ≈ **37s** (via Groq nuvem, não Qwen local) | As duas etapas de LLM juntas já são **mais rápidas** que qualquer etapa não-LLM pesada (Whisper, Thumbnail) — não é o gargalo |
| Corte de silêncio / sincronismo A/V | "testar com vídeos de diferentes codecs" | `VIDEO_EDIT` completou em **~2.7s** sem erro relatado, para H.264+AAC 1080p60 | Sem evidência de problema neste teste — mas só 1 combinação de codec foi testada |
| Extração de thumbnail | Não estimado antes | **4min44s gastos, 0 frames aproveitados** | Confirma o problema já registrado (vídeo sem conteúdo visual real) **e** revela que o limiar de nitidez também está calibrado errado (ver B11 acima) — corrigido apenas ajustando o limiar (D12: sem fallback de composição, aceita-se 0 thumbnails para vídeos sem conteúdo visual real) |
| Free tier de LLM em nuvem (Groq, 6.000 TPM) | Levantado como preocupação genérica na escolha Ollama vs. nuvem | Para 1h de vídeo (~1800 segmentos ≈ 120 chamadas de cleaning + 1 de intelligence ≈ 68.000 tokens): **~12 min só de espera por rate limit**, além do tempo de processamento | Confirma a preocupação levantada anteriormente sobre tiers gratuitos — a mitigação real (D10, provider plugável) já existe, mas o usuário precisa escolher Ollama local para vídeos longos e frequentes, ou usar um tier pago do Groq |

**Conclusão consolidada do teste real:** o gargalo do pipeline **não é o LLM** (nem local nem nuvem) — é o **Whisper em CPU** e a **extração de thumbnail ineficiente**. Qualquer esforço futuro de otimização de performance deve priorizar essas duas etapas, não a camada de LLM.

---

## 4. Testes de Regressão Obrigatórios (consolidado)

Estes testes existem especificamente porque um dos bugs acima já aconteceu uma vez — não são testes "de boa prática genérica", são proteção direta contra B1, B2 e B3:

1. **Hash consistente:** `get_video_hash_from_id(generate_video_id(...))` retorna exatamente o hash original, para todo agente que dependa disso. *(protege contra B1)*
2. **Um `StageResult` por etapa:** após `PipelineRunner.run()` completo, `state.stages` tem exatamente 1 entrada por etapa executada, nunca 2. *(protege contra B2)*
3. **Round-trip de estado:** salvar `PipelineState` em disco → recarregar → todos os campos (`Path`, `datetime`, `output_paths`) batem sem erro de validação. *(protege contra B3)*

---

*Fim do Registro de Decisões e Bugs Já Corrigidos.*
