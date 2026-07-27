# ProjetoVideoEdit

Pipeline de pós-produção de vídeo com IA — transcrição, cortes automáticos, legendas, thumbnails, shorts e empacotamento.

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
3. **Speech Recognition** — transcrição com faster-whisper (ou importada via `--srt`/`--vtt`)
4. **Marker Detection** — detecta palavras de corte/retorno na transcrição
5. **Transcript Cleaner** — regex + LLM em lote
6. **Content Intelligence** — SEO, shorts por capítulo, thumbnail, resumo
7. **Timeline Validator** — valida timestamps, espaçamento entre shorts
8. **Video Edit** — corta silêncios via FFmpeg (com padding configurável)
9. **Subtitle Styling** — gera SRT + VTT
10. **Thumbnail Frames** — extrai frames-chave
11. **Shorts Extraction** — exporta shorts .mp4
12. **Packaging** — analytics.json + report.md + ZIP

> Etapas 9, 10 e 11 rodam em paralelo.

## Provedores LLM

| Provider | Requer | Custo | Ideal para |
|----------|--------|-------|------------|
| `ollama` | Ollama rodando local | Gratuito | Uso offline, sem internet |
| `groq` | Chave de API Groq (gratuita) | 6K TPM, 14.4K req/dia | Testes rápidos, sem GPU |
| `gemini` | Chave de API Google Gemini | 1500 req/dia grátis | Qualidade superior, nuvem |

Defina via `LLM_PROVIDER` no `.env`.

## Configuração (`config/settings.py`)

O pipeline é configurado via arquivo `.env` ou variáveis de ambiente. Principais opções:

### Shorts
| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `SHORTS_TARGET_COUNT` | `4` | Número alvo de shorts por capítulo |
| `SHORTS_MIN_SPACING_SECONDS` | `20` | Espaçamento mínimo entre shorts |
| `SHORTS_MAX_DURATION_SECONDS` | `60` | Duração máxima de cada short |
| `SHORTS_MIN_DURATION_SECONDS` | `15` | Duração mínima de cada short |

### Edição / Silêncio
| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `SILENCE_THRESHOLD_DB` | `-35.0` | Limiar de silêncio em dB |
| `MIN_GAP_SECONDS` | `0.6` | Gap mínimo entre cortes |
| `SILENCE_PRE_PADDING_MS` | `100` | ms de padding antes do silêncio |
| `SILENCE_POST_PADDING_MS` | `150` | ms de padding depois do silêncio |

### Marcadores
| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `MARKER_CUT_WORD` | `"corte"` | Palavra que marca início de corte |
| `MARKER_RESUME_WORD` | `"início"` | Palavra que marca retorno |

## Estrutura de Pastas

```
ProjetoVideoEdit/
├── main.py                    # Entry point CLI
├── config/settings.py         # Config via Pydantic + .env
├── schemas/                   # Contratos Pydantic (video, transcript, marker, content, edit, ...)
├── agents/                    # 11 agentes do pipeline
│   ├── video_processing/
│   ├── speech_recognition/
│   ├── marker_detection/      # Detecta palavras de corte/retorno
│   ├── transcript_cleaner/
│   ├── content_intelligence/  # SEO, shorts por capítulo, thumbnail, resumo
│   ├── timeline_validator/
│   ├── video_edit/
│   ├── subtitle_styling/
│   ├── thumbnail_frames/
│   ├── shorts_extractor/
│   └── packaging/
├── services/                  # FFmpeg, Whisper, LLM provider, OpenCV, transcript import
├── pipeline/runner.py         # Orquestrador com paralelismo
├── shared/                    # Exceções, logging, preflight, SQLite
├── utils/                     # Hash, arquivo, tempo, slug
├── prompts/                   # Prompts LLM externos (.md)
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
