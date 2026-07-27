# ProjetoVideoEdit

Pipeline de pós-produção de vídeo 100% local com IA — transcrição, cortes automáticos, legendas, thumbnails, shorts e empacotamento.

## Requisitos Mínimos

- Python >= 3.10
- FFmpeg + FFprobe
- Ollama (com modelo qwen2.5:3b ou gemma2:2b)
- GPU NVIDIA com 4GB+ VRAM (recomendado) ou CPU
- 32GB RAM (recomendado)

## Instalação

```powershell
# 1. Clonar o repositório
git clone <url> ProjetoVideoEdit
cd ProjetoVideoEdit

# 2. Instalar dependências Python
pip install -e .

# 3. Instalar dependências opcionais (necessárias para rodar o pipeline completo)
pip install faster-whisper torch --index-url https://download.pytorch.org/whl/cu118
# Para CPU: pip install faster-whisper torch --index-url https://download.pytorch.org/whl/cpu

# 4. Instalar FFmpeg
winget install ffmpeg
# Alternativa: https://ffmpeg.org/download.html

# 5. Iniciar Ollama e baixar o modelo
ollama serve
ollama pull qwen2.5:3b

# 6. Copiar .env.example para .env (opcional, config padrão já funciona)
copy .env.example .env
```

## Como Usar

Coloque o vídeo bruto em `data/raw/` e execute:

```powershell
python main.py --video data/raw/seu_video.mp4
```

### Flags disponíveis

| Flag | Descrição |
|------|-----------|
| `--video VIDEO` | Caminho do vídeo (obrigatório) |
| `--from ETAPA` | Retomar de uma etapa específica |
| `--force` | Ignorar cache e reprocessar tudo |
| `--verbose` | Log nível DEBUG |

### Retomar de etapa específica

```powershell
python main.py --video video.mp4 --from CONTENT_INTELLIGENCE
```

### Reprocessar tudo

```powershell
python main.py --video video.mp4 --force
```

## Etapas do Pipeline

1. **Pre-Flight Check** — verifica FFmpeg, Ollama, disco
2. **Video Processing** — extrai áudio WAV + metadados
3. **Speech Recognition** — transcrição com faster-whisper
4. **Transcript Cleaner** — regex + LLM em lote
5. **Content Intelligence** — SEO, shorts, thumbnail, resumo
6. **Timeline Validator** — valida timestamps
7. **Video Edit** — corta silêncios via FFmpeg
8. **Subtitle Styling** — gera SRT + VTT
9. **Thumbnail Frames** — extrai frames-chave
10. **Shorts Extraction** — exporta shorts .mp4
11. **Packaging** — analytics.json + report.md + ZIP

> Etapas 8, 9 e 10 rodam em paralelo.

## Estrutura de Pastas

```
ProjetoVideoEdit/
├── main.py                    # Entry point CLI
├── app/cli.py                 # Parsing de argumentos
├── config/settings.py         # Config via Pydantic
├── schemas/                   # Contratos Pydantic
├── agents/                    # 10 agentes do pipeline
├── services/                  # FFmpeg, Whisper, Ollama, OpenCV
├── pipeline/runner.py         # Orquestrador
├── shared/                    # Exceções, logging, preflight, SQLite
├── utils/                     # Hash, arquivo, tempo, slug
├── prompts/                   # Prompts LLM externos
├── app/streamlit_app.py       # Dashboard (opcional)
├── data/raw/                  # Coloque vídeos aqui
├── cache/                     # Cache intermediário (gerado)
└── outputs/                   # Artefatos finais (gerado)
```

## Dashboard Streamlit (Opcional)

```powershell
streamlit run app/streamlit_app.py
```

## Hardware Recomendado

- **CPU:** Ryzen 7 6000 ou superior
- **GPU:** NVIDIA GTX 1650 4GB (ou superior)
- **RAM:** 32GB
- **Armazenamento:** NVMe 1TB
