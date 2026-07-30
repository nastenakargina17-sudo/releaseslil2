from copy import deepcopy
import io
from pathlib import Path, PurePosixPath
from typing import Iterable
import zipfile

from jinja2 import Environment

from app.models import DigestItem, DigestRelease
from app.services.publication import build_live_digest_content


class StaticExportError(Exception):
    pass


BRAND_ASSETS = (
    "brand/Logo_Skillaz_Black.png",
    "brand/OnestRegular1602-hint.ttf",
    "brand/OnestBold1602-hint.ttf",
)


def build_static_digest_zip(
    release: DigestRelease,
    items: Iterable[DigestItem],
    uploads_dir: Path,
    static_dir: Path,
    template_env: Environment,
) -> bytes:
    root = _safe_release_root(release.id)
    content = deepcopy(build_live_digest_content(items))
    archive_assets: list[tuple[str, Path]] = []
    used_names: set[str] = set()

    for relative_path in BRAND_ASSETS:
        source = static_dir / relative_path
        if not source.is_file():
            raise StaticExportError(f"Missing brand asset: {relative_path}")
        asset_name = Path(relative_path).name
        used_names.add(asset_name.casefold())
        archive_assets.append((asset_name, source))

    for section in content["sections"]:
        for item in section["items"]:
            for media in item["media"]:
                source = _resolve_upload(media["path"], uploads_dir)
                if not source.is_file():
                    raise StaticExportError(f"Missing digest media: {media['path']}")
                asset_name = _unique_asset_name(source.name, used_names)
                archive_assets.append((asset_name, source))
                media["path"] = f"assets/{asset_name}"

    html = template_env.get_template("digest.html").render(
        release=release,
        page_mode="export",
        sections=content["sections"],
        metrics=content["metrics"],
        metric_labels=content["metric_labels"],
        brand_asset_prefix="assets",
    )

    output = io.BytesIO()
    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{root}/index.html", html.encode("utf-8"))
            for asset_name, source in archive_assets:
                archive.writestr(f"{root}/assets/{asset_name}", source.read_bytes())
    except (OSError, zipfile.BadZipFile) as exc:
        raise StaticExportError("Could not build digest archive") from exc
    return output.getvalue()


def _safe_release_root(release_id: str) -> str:
    safe = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in release_id
    ).strip("-")
    return safe or "digest"


def _resolve_upload(public_path: str, uploads_dir: Path) -> Path:
    prefix = "/uploads/"
    if not public_path.startswith(prefix):
        raise StaticExportError(f"Unsupported media path: {public_path}")
    relative = PurePosixPath(public_path[len(prefix):])
    if relative.is_absolute() or ".." in relative.parts:
        raise StaticExportError(f"Unsafe media path: {public_path}")
    candidate = uploads_dir.joinpath(*relative.parts)
    try:
        candidate.resolve().relative_to(uploads_dir.resolve())
    except ValueError as exc:
        raise StaticExportError(f"Unsafe media path: {public_path}") from exc
    return candidate


def _unique_asset_name(original_name: str, used_names: set[str]) -> str:
    source_name = Path(original_name).name
    stem = Path(source_name).stem or "media"
    suffix = Path(source_name).suffix
    candidate = f"{stem}{suffix}"
    number = 2
    while candidate.casefold() in used_names:
        candidate = f"{stem}-{number}{suffix}"
        number += 1
    used_names.add(candidate.casefold())
    return candidate
