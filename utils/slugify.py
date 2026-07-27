import re


def slugify_filename(filename: str) -> str:
    name = filename.rsplit(".", 1)[0] if "." in filename else filename
    name = name.lower()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    name = re.sub(r"-+", "-", name)
    return name.strip("-")


def generate_video_id(filename: str, video_hash: str) -> str:
    return f"{slugify_filename(filename)}-{video_hash}"
