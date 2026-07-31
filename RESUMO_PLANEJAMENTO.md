# Pipeline de Pós-Produção com IA — Resumo para Planejamento

> Compilado de tudo feito até o commit `cf46bb4` (31/07/2026). Feito para anexar em um chat de planejamento e ter o quadro completo sem precisar ler 5 documentos.

---

## 1. O que o projeto faz

Pipeline que recebe um vídeo MP4 cru e entrega:
- Vídeo editado (silêncios removidos) + legendas SRT/VTT
- SEO (título, descrição, hashtags, capítulos) + resumo + prompts de thumbnail
- Shorts recortados por mérito de conteúdo
- Relatório de analytics + ZIP empacotado

Tudo local e gratuito por padrão (Ollama), com fallback para nuvem gratuita (Groq/Gemini).

---

## 2. Hardware de referência

| Componente | Especificação |
|---|---|
| CPU | Ryzen 7 6000 (ou i7 equivalente) |
| GPU | NVIDIA GTX 1650 4GB VRAM |
| RAM | 32GB |
| Disco | NVMe 1TB |
| OS | Windows 11 |

---

## 3. Tecnologias

| Camada | Escolha |
|---|---|
| Transcrição | `faster-whisper` modelo `small`, device `cpu` ou `cuda` |
| LLM local | Ollama com Qwen2.5 3B (CPU ou GPU leve) |
| LLM nuvem | Groq (Llama 3.1 8B, free 6K TPM) ou Gemini (2.0 Flash) |
| Vídeo | FFmpeg (stream copy quando possível) |
| Thumbnails | OpenCV (Laplacian var ≥ 50) |
| Config | Settings Pydantic flat + `.env` |
| Orquestração | PipelineRunner com ThreadPoolExecutor para estágios paralelos |
| Cache | JSON por hash de vídeo (`cache/<hash>/`) |
| Testes | 50 testes com pytest + ruff lint |

---

## 4. Estágios do pipeline (12 etapas)

| # | Estágio | Função |
|---|---|---|
| 1 | PRE_FLIGHT | Verifica FFmpeg, LLM provider, disco, CUDA |
| 2 | VIDEO_PROCESSING | Extrai áudio WAV + metadados |
| 3 | SPEECH_RECOGNITION | faster-whisper (ou importação externa via `--srt`/`--vtt`) |
| 4 | MARKER_DETECTION | Detecta palavras de corte/retorno ("corte"..."início") |
| 5 | TRANSCRIPT_CLEANING | Regex + LLM em batch (15 segmentos/chamada) |
| 6 | CONTENT_INTELLIGENCE | Fase 1: SEO+chapters+summary+thumbnail; Fase 2: shorts por capítulo |
| 7 | TIMELINE_VALIDATION | Valida timestamps, espaçamento entre shorts |
| 8 | VIDEO_EDIT | Corta silêncios (VAD) + marcadores, com padding configurável |
| 9-11 | SUBTITLE + THUMBNAIL + SHORTS | Paralelo |
| 12 | PACKAGING | ZIP + analytics + report.md |

---

## 5. Decisões arquiteturais (D1-D15) — resumo

| # | Decisão |
|---|---|
| D1 | Hardware baseline definido — nunca exigir LLM 7B+ como requisito da V1 |
| D2 | Limpeza de transcrição: regex + LLM (não LLM puro). Lista fechada: hum, ah, ahn, ãhn, ehm |
| D3 | Content Intelligence unificado (SEO+shorts+thumbnail+summary) + validator separado |
| D4 | PipelineRunner sequencial (sem LangGraph). Paralelismo via ThreadPoolExecutor |
| D5 | Pre-flight check obrigatório — fail fast |
| D6 | VAD obrigatório no Whisper (não expor como opção desabilitável) |
| D7 | Cache JSON por hash + `--from <stage>` / `--force` |
| D8 | Configuração única (Settings flat, prompts externos em `./md`) |
| D9 | Burn-in remove nave V1 |de legenda removido do escopo |
| D10 | LLM provider plugável (Ollama/Groq/Gemini) — agentes nunca chamam API diretamente |
| D11 | Transcrição externa: `--transcript` / `--srt` / `--vtt` |
| D12 | Shorts por capítulo com `hook_strength`, 2 fases de Content Intelligence. Thumbnail Composer REMOVIDO |
| D13 | Detecção de silos unificada no VAD (não mais ffmpeg silencedetect separado) |
| D14 | Novo estágio MARK_DETECTION para marcadores de voz (`"corte"..."início"`) |
| D15 | Curadoria de shorts por capítulo + score de gancho |

---

## 6. Bugs já corrigidos (B1-B11)

| # | Bug | Fix |
|---|---|---|
| B1 | Resume quebrava silenciosamente — hash diferente entre agentes | Centralizado hash em `utils/hash_utils.py` |
| B2 | analytics corrompido — 2 registros por etapa | Só Runner faz append, agentes nunca |
| B3 | PipelineState/StageResult quebrava no round-trip disco | Removido strict=True desses 2 schemas |
| B4 | eval() no parsing de FPS | Fragment.Fraction |
| B5 | Cleaner 1 chamada/segmento (300+ calls) | Batch de 15 segmentos/chamada |
| B6 | Vazamento de VRAM do Whisper | unload_whisper_model() ao provar |
| B7 | Pipeline 100% sequencial | Tripla paralela (ThreadPoolExecutor) |
| B8 | Nome de saga como número no relatório (paralelo) | stage.name (string) no future_to_stage |
| B9 | Relatório "Incompleto" com 100% sucesso | completed=True antes PACKAGING |
| B10 | confidence ausente no cleaner LLM path | confidence=seg.confidence |
| B11 | 0 thumbnails extraídos (limiar 100) | Laplacian var ≥ 50 |

---

## 7. Testes reais executados

### Teste 1 — Vídeo 8min36s (PC sem GPU, Groq free tier)
- Commit: `1eabc93`
- 50/50 testes passam
- **Tempo total: ~13 min** (Whisper CPU ~5min, cleaning ~3min, CI ~37s, edit ~2.7s)
- 4 shorts extraídos
- 0 thumbnails (limiar antigo 100 — corrigido depois para 50)
- **Gargal. identificado:** Whisper em CPU (não o LLM)

### Teste 2 — Vídeo 2h45min (PC com GTX 1650 4GB, CUDA)
- Commit: `cf46bb4`
- **Tempo total: ~1h07min**
- 50/50 testes passam
- 4 shorts extraídos, 5 thumbnails
- **3 problemas NOVOS encontrados** (ver seção 8)

---

## 7. status final do commit `cf46bb4`

| Item | Status |
|---|---|
| 50/50 testes | ✅ |
| Ruff lint | ✅ 0 erros |
| `pipe install -e .` | ✅ |
| `.env.example` | ✅ |
| README.md atualizado | ✅ |
| REFERENCIA_CONTRATOS.md atualizado (D10-D15)| ✅ |
| Todo código commitado | ✅ |
| Exportável para outro PC | ✅ |

---

## 8. Bugs/Melhorias IDENTIFICADOS MAS NÃO CORRIGIDOS

Estes foram descobertos no **teste 2** (vídeo 2h45min) — **ainda pendentes**:

### [PENDENTE 1] CRÍTICO — Content Intelligence só vê o começo de vídeos longos

> **Status: ✅ RESOLVIDO por D17** (chunking map-reduce + consolidação) — ver `Registro_Decisoes_e_Bugs_Lessons_Learned.md`.

**Arquivo:** `agents/content_intelligence/agent.py:30`

 **Sintoma:** Para o vídeo de 2h45min, todos os capítulos ficaram entre 0-15min e todos os 4 shorts entre 11-14min. O restante dos 2h30min do vídeo foi *completamente ignorado*.

**Causa raiz:** `_format_transcript(transcript, max_segments=400)` trunca os **primeiros** 400 segmentos. Um vídeo de 2h45min gera ~1300 segmentos Whisper — a IA só viu o começo.

**atituded:** A ref. list da chamada SEO (fase 1) cobre apenas ~30% do vídeo, e dos capítul gerados a partir desse pedaço parcial, a fase 2 (shorts) herda esses capítulos truncados.

**Correção proposta:** Em vez de truncar os N primeiros segmentos, **amostrar uniformemente pela duração total** — ex: pegar N segmentos espalhados proporcionalmente ao longo do vídeo, ou dividir o transcription em chunkys e pedir capítulos por trecho.

---

### [PENDENTE 2] GRAVE: Thumbnails levam 13min22s para 5 frames (298 mil frames sequential)

> **Status: ✅ OBSOLETO/resolvido por REMOÇÃO (D16)** — a etapa de thumbnail foi removida inteiramente (conteúdo *audio-first*), não otimizada. Ver D16 no registro oficial.

**Arquivos:** `services/opencv_service.py:35` + `agents/thumbnail_frames/agent.py`

**Sintoma:** Extração de 5 thumbnails do vídeo 2h45min levou 13min22s no total. Para comparação: Whisper CUDA transcreveu 2h45min em 22min — a extração de 5 frames levou mais da metade disso.

**Causa raiz:** `extract_candidate_frames()` fazes `cap_read()` **frame a frame** decimal de todos os ~298.000 frames do vídeo (só calculate histograma/Laplaciano a 1fps, mas descriptografa TUDO). Para 2h45min, 9939 segundos de vídeo * 300% de laqueza = ~780s.

Adicional: a seleção por scene_dist (mudança de cena) + min_spacing_percent=5% (497s de espaçamento) acabou returnando frames só da primeira metade do vídeo (000s, 646s, 1150s, 3344s, 4406s)  — nada entre 4406s e 9939s.

**Correcção props :** Em vez de scanando o vídeo inteiro, usar iterações direcionais por timestamp:  
`cap.aSet(cv2.CAP_PROPCD_POS_MSEC, t)` em ~50* pontos uniformemente espalhados pela duração, compute Laplacian em cada um, ranquez por `lap_var * scene_dist` e selecione os top N com espaçamento mínimo.

**Impacto estimado:** de ~13 min para ~2 segundos.

### [PENDENTE 3] GROQ FREE TIER INVÁLIDO para vídeos de 2h+ (Expected, não precisa de code)

**Métrica real:** Cleaner teve 24 min de rate limit e 429 backoff para ~44 chamadas no vídeo de 2h45min.

**Status:** Já existe mitigação (Ollama local é a rota recomendada para vídeos longos), e o logger já funciona. Só é -> usar Ollama ou banco pago para vídeos muito longos.

---

## 9. Estrutura de arquivos do projeto

```
ProjetoVideoEdit/
├── main.py
├── config/settings.py
├── schemas/                 # Content, transcript, marker, video, edit, subtitle, analyzes
├── agents/                  # 11 agentes
│   └── (video_proc, speech_rec, marken_detecting, transcript_cleaner,
│        content_intelligence, timeline_validator, video_edit,
│        subtitle_styling, thumbnails_frames, shorts_extractor, packaging)
├── services/                # ffmpeg, whisper, llm_provider, opencv, transcript_import
├── pipeline/runner.py
├── shared/                  # preflight, exceptionsão_s, logging
├── utils/                   # hash, slug, file_io
├── prompts/*.md             # content_intelligence, cleaning, shorts, thumbnail
├── tests/                   # 50 testes
├── NewDocs/                 # Documentação (LESSONS_LEARNED.md, REFERENCIA_CONTRATOS.md...)
├── .env.example
├── .githubignore
└── README.md
```

---

## 10. Prompts de sistema

| distribuir | Usado por |
|---|---|
| `prompts/cleaning_llm.md` | TranscriptCleanerAgent |
| `prompts/content_intelligence.md` | ContentIntelligenceAgent (Fase 1: SEO+2+summary+thumbnail) |
| `prompts/ shorts_prompt.md ` | ContentIntelligenceAgent (Fase 2: shorts per chapter) |
| `prompts/thumbnail_prompt.md` | ContentIntelligenceAgent (paragraph de thumbnail) |

---

## 11. Flags CLI

| Flage | Função |
|---|---|
| `--video` | Caminho do vídeo (obrigatório) |
| `--from` | Retomar de etapa específica |
| `--force` | Ignorar cache e reprocessar tudo |
| `--verbose` | DEBUG logging |
| `--transcript` | Importação de JSON de transcrição externa |
| `--srt` | Import via SRT |
| `--vtt` | Import via VTT |

---

## 12. Configurações importantes (.env / Settings)

| Variável | Default | Descrição |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | ollama / gemini / gr |
| `WHISPER_DEVICE` | `cuda` | cuda ou cpu |
| `WHISPER_MODEL_SIZE` | `small` | tiny \| base \| small \| medium \| large-v3 |
| `SHORTS_TARGET_COUNT` | `4` | Alvo de shorts por capítulo |
| `USE_MIN_SPDELAY_SECONDS` | `20` | Espaçamento mínimo entre shorts |
| `SHORTS_MAX_DURATION_SECONDS` | `60` | Duração máxima por short |
| `SHORTS_MIN_DURATION_SECONDS` | `15` | Duração mínima por short |
| `SILENCE_PRE_PADDING_MS` | `100` | ..segundos antes do começo do fala |
| `SILENCE_POST_PADDING_MS` | `150` |..segundos depois do fim da fala |
| `MARKER_CUT_WORD` | `"corte"` | Palavra que indica início de corte (o `"cor"` abaixo era erro de digitação deste resumo — confirmado como `corte` no Settings) |
| `MARKER_RESUME_WORD` | `"início"` | Palavra que indica retomar |

---

## 13. Próximos passos recomendados

Prioridade decrescente:

1. **Corrigir truncamento do Content Intelligence (PENDENTE 1)** — bug que inutiliza a feature principal (shorts) em vídeos >~40min
2. **Substituir scan sequencial de frames por seeking (PENDENTE 2)** — reduz esta etapa de ~13 min para 2s
3. **Rodar 50 testes + lint** após View
4. _(opcional)_ Ajusto espaçamento padrão da thumbnail (5% dá 500s para 2h45 min — 5 frames só cobrem metade do vídeo)
5. _(opcional)_ Otimiza Whisper GPU (7.3x temporal para modelo small é o farelo — o exploit de modelagramento já é a forma de acelerar isso)

---

*Incluir este arquivo como anexo em qualquer chat de planejamento para ter o contexto completo. Todos os documentos-código (LESSONS_LEARNED.md, REFERENCIA_CONTRATOS.md, RELATORIO_IMPLEMENTACAO.md, RELATORIO_EXECUCAO.md) contêm detalhes adicionais para consulta.*