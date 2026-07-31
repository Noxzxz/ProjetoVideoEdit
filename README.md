# ProjetoVideoEdit

Pipeline de pós-produção de vídeo com IA — transcrição, cortes automáticos, legendas, curadoria de shorts e empacotamento. Otimizado para o nicho **World of Darkness** (sessões de RPG de mesa, mecânica, lore e podcast): conteúdo *audio-first*, com suporte a glossário de vocabulário de sistema, contexto de campanha persistente e hashtags curadas por linha de jogo.

## Requisitos Mínimos

- Python >= 3.10
- FFmpeg + FFprobe
- **LLM provider** (um dos três):
  - Ollama (local, gratuito) — requer 4GB+ RAM extra
  - Groq API (nuvem, gratuito 6K TPM)
  - Gemini API (nuvem, gratuito 1500 req/dia)
- GPU NVIDIA 4GB+ (recomendado para Whisper) ou CPU
- 32GB RAM (recomendado)

## Instalação

```powershell
# 1. Clonar o repositório
git clone <url> ProjetoVideoEdit
cd ProjetoVideoEdit

# 2. Instalar dependências Python
pip install -e .

# 3. Instalar FFmpeg (se não tiver)
winget install ffmpeg
# Alternativa: https://ffmpeg.org/download.html

# 4. Configurar provedor LLM
copy .env.example .env
# Edite .env: escolha LLM_PROVIDER e preencha a chave da API (se for Groq/Gemini)

# 5. Se for usar Ollama (opcional):
#    ollama serve
#    ollama pull qwen2.5:3b
```

> `faster-whisper` **não** precisa de PyTorch. O `pip install -e .` instala todas as dependências necessárias. O `torch` que aparecia em versões anteriores do README não é usado pelo projeto.

## Como Usar

```powershell
python main.py --video data/raw/seu_video.mp4
```

### Flags disponíveis

| Flag | Descrição |
|------|-----------|
| `--video CAMINHO` | Caminho do vídeo (obrigatório) |
| `--from ETAPA` | Retomar de uma etapa específica |
| `--force` | Ignorar cache e reprocessar tudo |
| `--verbose` | Log nível DEBUG |
| `--transcript ARQUIVO` | Importar transcrição externa (JSON) |
| `--srt ARQUIVO` | Importar transcrição de arquivo SRT |
| `--vtt ARQUIVO` | Importar transcrição de arquivo VTT |

### Retomar de etapa específica

```powershell
python main.py --video video.mp4 --from CONTENT_INTELLIGENCE
```

### Reprocessar tudo

```powershell
python main.py --video video.mp4 --force
```

### Importar transcrição externa (pular Speech Recognition)

```powershell
python main.py --video video.mp4 --srt legenda.srt
```

## Etapas do Pipeline

1. **Pre-Flight Check** — verifica FFmpeg, provedor LLM, disco
2. **Video Processing** — extrai áudio WAV + metadados
3. **Speech Recognition** — transcrição com faster-whisper, VAD obrigatório (ou importada via `--srt`/`--vtt`); glossário injetado como hotwords
4. **Marker Detection** — detecta marcadores de corte de erro de fala (`"corte"`/`"inicio"`) e de conteúdo fora de personagem OOC (`"pausa"`/`"retomando"`)
5. **Transcript Cleaner** — regex (lista fechada) + LLM em lote
6. **Content Intelligence** — map-reduce com checkpoint por chunk: SEO, capítulos, shorts por capítulo, resumo; consolidação com contexto de campanha + hashtags curadas; crítico de autocontenção (D19) e picos de energia RMS (D21)
7. **Timeline Validator** — valida timestamps, espaçamento e duração dos shorts
8. **Video Edit** — corta silêncios via FFmpeg (com padding configurável)
9. **Subtitle Styling** — gera SRT + VTT
10. **Shorts Extraction** — exporta shorts .mp4 ancorados deterministicamente
11. **Packaging** — analytics.json + report.md + ZIP

> Etapas 9 e 10 rodam em paralelo. Não existe etapa de thumbnail — decisão específica para o formato *audio-first* (ver D16).

## Invalidação de Cache (Fingerprint por Etapa)

O cache é invalidado **por etapa**, não globalmente. Cada etapa tem um fingerprint de configuração (D27) calculado a partir dos settings e arquivos que a afetam (prompts, glossário, campanha, hashtags). Se o fingerprint mudou, a etapa e **todas as subsequentes** são reprocessadas automaticamente — as etapas anteriores são preservadas. Ou seja: mudar só o prompt de shorts não reprocessa a transcrição.

- Alterou um prompt/glossário/campanha? A próxima execução reprocessa só o que depende daquilo.
- Quer reprocessar tudo mesmo assim? Use `--force`.

## Provedores LLM

| Provider | Requer | Custo | Ideal para |
|----------|--------|-------|------------|
| `ollama` | Ollama rodando local | Gratuito | Uso offline, sem internet |
| `groq` | Chave de API Groq (gratuita) | 6K TPM, 14.4K req/dia | Testes rápidos, sem GPU |
| `gemini` | Chave de API Google Gemini | 1500 req/dia grátis | Qualidade superior, nuvem |

Defina via `LLM_PROVIDER` no `.env`.

Todos os provedores usam retry/backoff automático (D29): em 429/5xx/falha de conexão, a chamada é repetida até `LLM_MAX_RETRIES` vezes com espera crescente (`LLM_RETRY_BACKOFF_SECONDS` × tentativa).

## Configuração (`config/settings.py`)

O pipeline é configurado via arquivo `.env` ou variáveis de ambiente (Pydantic `BaseSettings`, modelo flat). Principais opções:

### Nicho World of Darkness
| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `GLOSSARY_NAME` | `""` | Glossário em `glossaries/` (ex: `vampiro`, `lobisomem`, `mago`). Usado como hotwords do Whisper e correção fuzzy pós-transcrição. Vazio = desativado |
| `CAMPAIGN_CONTEXT_FILE` | `""` | Arquivo `.md` de contexto de campanha (PCs/NPCs recorrentes, resumo de eventos) injetado na consolidação |
| `HASHTAGS_FILE` | `""` | Lista curada de hashtags por linha de jogo (ex: `hashtags_vampiro.md`) |
| `CONTENT_TYPE` | `sessao` | Tipo de conteúdo: `sessao` \| `mecanica` \| `lore` \| `podcast` — muda o critério de curadoria de shorts |
| `OOC_PAUSE_WORD` | `pausa` | Palavra que marca início de trecho fora de personagem (excluído de shorts) |
| `OOC_RESUME_WORD` | `retomando` | Palavra que marca retorno ao personagem |
| `WHISPER_INITIAL_PROMPT` | `""` | Hotwords manuais; vazio = usa o glossário (se configurado) |

### Shorts
| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `SHORTS_TARGET_COUNT` | `4` | Número alvo de shorts por capítulo |
| `SHORTS_MIN_SPACING_SECONDS` | `30` | Espaçamento mínimo entre shorts |
| `SHORTS_MAX_DURATION_SECONDS` | `60` | Duração máxima de cada short |
| `SHORTS_MIN_DURATION_SECONDS` | `15` | Duração mínima de cada short |
| `SHORTS_MIN_STANDALONE_SCORE` | `0.5` | Abaixo disso o short é descartado (crítico de autocontenção) |

### LLM
| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `LLM_CALL_DELAY_SECONDS` | `3.0` | Delay entre chamadas LLM (rate limit / Ollama local) |
| `LLM_MAX_RETRIES` | `3` | Tentativas por chamada em 429/5xx/falha de conexão |
| `LLM_RETRY_BACKOFF_SECONDS` | `2.0` | Backoff base (multiplicado pela tentativa) |

### Edição / Silêncio
| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `SILENCE_THRESHOLD_DB` | `-35.0` | (Não implementado — reservado para detecção de silêncio via FFmpeg `silencedetect`) |
| `MIN_GAP_SECONDS` | `0.6` | Gap mínimo entre cortes |
| `SILENCE_PRE_PADDING_MS` | `100` | ms de padding antes do silêncio |
| `SILENCE_POST_PADDING_MS` | `150` | ms de padding depois do silêncio |

### Marcadores de corte de fala
| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `MARKER_CUT_WORD` | `"corte"` | Palavra que marca início de corte |
| `MARKER_RESUME_WORD` | `"inicio"` | Palavra que marca retorno |

## Estrutura de Pastas

```
ProjetoVideoEdit/
├── main.py                    # Entry point CLI
├── config/settings.py         # Config via Pydantic + .env (flat, injetado via DI)
├── schemas/                   # Contratos Pydantic (video, transcript, marker, content, edit, ...)
├── agents/                    # 10 agentes do pipeline
│   ├── video_processing/
│   ├── speech_recognition/
│   ├── marker_detection/      # Marcadores de corte de fala + OOC
│   ├── transcript_cleaner/
│   ├── content_intelligence/  # SEO, capítulos, shorts por capítulo, resumo (map-reduce)
│   ├── timeline_validator/
│   ├── video_edit/
│   ├── subtitle_styling/
│   ├── shorts_extractor/
│   └── packaging/
├── services/                  # FFmpeg, Whisper, LLM provider (retry/backoff), análise RMS, transcript import
├── pipeline/
│   ├── runner.py              # Orquestrador com paralelismo (ThreadPoolExecutor)
│   └── fingerprint.py         # Fingerprint de config por etapa (invalidação seletiva de cache)
├── shared/                    # Exceções, logging, preflight
├── utils/                     # Hash (por amostra), arquivo (escrita atômica), tempo, slug, ancoragem, glossário
├── prompts/                   # Prompts LLM externos (.md)
├── glossaries/                # Vocabulário por linha de jogo + hashtags curadas (.md)
├── campanha/                  # Contexto de campanha por crônica (.md)
├── app/streamlit_app.py       # Dashboard (opcional)
├── .env.example               # Template de configuração
├── data/raw/                  # Coloque vídeos aqui
├── cache/                     # Cache intermediário (gerado)
└── outputs/                   # Artefatos finais (gerado)
```

## Hardware Recomendado

- **CPU:** Ryzen 7 6000 ou superior
- **GPU:** NVIDIA GTX 1650 4GB (ou superior) — acelera Whisper ~5x
- **RAM:** 32GB
- **Armazenamento:** NVMe 1TB

## Documentação

- `Registro_Decisoes_e_Bugs_Lessons_Learned.md` — *por que* cada decisão (D1-D33) e correção (B1-B33) existe; consulte antes de "otimizar" o código.
- `Referencia_Rapida_Contratos.md` — schemas e assinaturas atuais.
- `RESUMO_PLANEJAMENTO.md` / `Epics_e_Backlog_Pipeline_IA.md` / `RELATORIO_IMPLEMENTACAO.md` — histórico de planejamento (snapshots).
