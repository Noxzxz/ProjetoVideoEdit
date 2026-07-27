import argparse


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pipeline de pos-producao de video com IA",
    )
    parser.add_argument(
        "--video",
        "-v",
        type=str,
        required=True,
        help="Caminho para o arquivo de video",
    )
    parser.add_argument(
        "--from",
        "-f",
        type=str,
        dest="from_stage",
        default=None,
        help="Retomar a partir de uma etapa especifica",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Ignorar cache e reprocessar tudo",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Log nivel DEBUG",
    )
    parser.add_argument(
        "--transcript",
        type=str,
        default=None,
        help="Importar transcricao existente (JSON no formato TranscriptRaw)",
    )
    parser.add_argument(
        "--srt",
        type=str,
        default=None,
        help="Importar transcricao de arquivo SRT",
    )
    parser.add_argument(
        "--vtt",
        type=str,
        default=None,
        help="Importar transcricao de arquivo VTT",
    )
    return parser.parse_args(argv)
