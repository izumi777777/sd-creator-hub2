"""ローカル画像からメタデータを除き、指定レイアウトで書き出す。"""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

from PIL import Image
from werkzeug.utils import secure_filename

# 対応拡張子（大文字小文字は Path.suffix で比較）
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

# Windows 等で使えない文字
_BAD_PATH_CHARS = frozenset('<>:"/\\|?*\n\r\t\x00')


def safe_path_component(name: str, max_len: int = 200) -> str:
    """
    パス1セグメントとして安全な文字列にする。
    secure_filename は日本語を落とすため、落ちた場合は禁止文字のみ除去する。
    """
    raw = (name or "").strip()
    s = secure_filename(raw)
    if s:
        return s[:max_len]
    cleaned = "".join(c for c in raw if c not in _BAD_PATH_CHARS).strip() or "unnamed"
    return cleaned[:max_len]


def _is_image_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES


def _iter_image_files(root: Path, recursive: bool) -> Iterator[Path]:
    if recursive:
        for p in sorted(root.rglob("*")):
            if _is_image_file(p):
                yield p
    else:
        for p in sorted(root.iterdir()):
            if _is_image_file(p):
                yield p


def _validate_io_paths(input_dir: Path, output_dir: Path) -> tuple[Path, Path]:
    """入力・出力パスを解決し、危険な包含関係を拒否する。"""
    inp = input_dir.expanduser().resolve()
    out = output_dir.expanduser().resolve()
    if not inp.is_dir():
        raise ValueError("インプットパスが存在しないか、フォルダではありません。")
    if inp == out:
        raise ValueError("インプットとアウトプットに同じパスは指定できません。")
    try:
        out.relative_to(inp)
        raise ValueError(
            "アウトプットをインプットフォルダの内側に指定できません（誤上書き防止）。"
        )
    except ValueError as e:
        if "アウトプットをインプット" in str(e):
            raise
    try:
        inp.relative_to(out)
        raise ValueError(
            "インプットをアウトプットフォルダの内側に指定できません（誤上書き防止）。"
        )
    except ValueError as e:
        if "インプットをアウトプット" in str(e):
            raise
    return inp, out


def _unique_dest(dest: Path) -> Path:
    """同名があれば連番でずらす。"""
    if not dest.exists():
        return dest
    stem, suf = dest.stem, dest.suffix
    parent = dest.parent
    n = 1
    while True:
        cand = parent / f"{stem}_{n}{suf}"
        if not cand.exists():
            return cand
        n += 1


def strip_metadata_from_bytes(data: bytes) -> bytes:
    """
    画像バイト列から主要メタデータを除いたバイト列を返す（API 応答の保存用）。

    PNG / JPEG を想定。WebP は PIL が開ける場合は PNG バイトで返す。
    """
    bio_in = io.BytesIO(data)
    with Image.open(bio_in) as im:
        im.load()
        fmt = (im.format or "").upper()
        out = io.BytesIO()
        if fmt == "JPEG" or data[:2] == b"\xff\xd8":
            im.convert("RGB").save(out, format="JPEG", quality=95, optimize=True)
            return out.getvalue()
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            buf = im.convert("RGBA")
        else:
            buf = im.convert("RGB")
        buf.save(out, format="PNG", optimize=True)
        return out.getvalue()


def strip_metadata_to_file(src: Path, dest: Path) -> None:
    """
    EXIF 等を除いた画像を dest に保存する。

    ピクセルを新規 Image に載せ替えることで、主要なメタデータを落とす。
    """
    suffix = src.suffix.lower()

    with Image.open(src) as im:
        im.load()

        if suffix in (".jpg", ".jpeg"):
            rgb = im.convert("RGB")
            final = _unique_dest(dest.with_suffix(".jpg"))
            final.parent.mkdir(parents=True, exist_ok=True)
            rgb.save(final, format="JPEG", quality=95, optimize=True)
        elif suffix == ".png":
            if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                buf = im.convert("RGBA")
            else:
                buf = im.convert("RGB")
            final = _unique_dest(dest.with_suffix(".png"))
            final.parent.mkdir(parents=True, exist_ok=True)
            buf.save(final, format="PNG", optimize=True)
        elif suffix == ".webp":
            buf = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
            final = _unique_dest(dest.with_suffix(".webp"))
            final.parent.mkdir(parents=True, exist_ok=True)
            buf.save(final, format="WEBP", quality=90, method=6)
        else:
            raise ValueError(f"未対応の形式です: {suffix}")


def process_single_character(
    input_dir: str,
    output_dir: str,
    character_folder_name: str,
    *,
    recursive: bool = False,
) -> tuple[int, list[str]]:
    """
    インプット内の画像をすべてメタデータ除去し、
    アウトプット/{キャラフォルダ名}/ に保存する。

    Returns:
        (成功件数, エラーメッセージのリスト)
    """
    inp, out_root = _validate_io_paths(Path(input_dir), Path(output_dir))
    safe_char = safe_path_component(character_folder_name, max_len=80) or "character"
    target_root = out_root / safe_char
    target_root.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    ok = 0
    for src in _iter_image_files(inp, recursive):
        try:
            name = safe_path_component(src.name)
            dest = target_root / name
            strip_metadata_to_file(src, dest)
            ok += 1
        except Exception as e:
            errors.append(f"{src.name}: {e}")
    return ok, errors


def process_subfolders(
    input_dir: str,
    output_dir: str,
    *,
    recursive: bool = False,
) -> tuple[int, list[str], list[str]]:
    """
    インプット直下の各サブフォルダをキャラ（カテゴリ）名とみなし、
    アウトプット/{サブフォルダ名}/ にメタデータなしで保存する。

    インプット直下のファイル（ルートに置かれた画像）は対象外とし、warnings に記録。

    Returns:
        (成功件数, エラーメッセージ, 警告メッセージ)
    """
    inp, out_root = _validate_io_paths(Path(input_dir), Path(output_dir))
    errors: list[str] = []
    warnings: list[str] = []
    ok = 0

    root_files = [p for p in inp.iterdir() if p.is_file() and _is_image_file(p)]
    if root_files:
        warnings.append(
            f"インプット直下の画像 {len(root_files)} 件はスキップしました（サブフォルダ内のみ処理）。"
        )

    for sub in sorted(inp.iterdir()):
        if not sub.is_dir():
            continue
        folder_label = safe_path_component(sub.name, max_len=80)
        target_root = out_root / folder_label
        target_root.mkdir(parents=True, exist_ok=True)

        if recursive:
            files = [p for p in sub.rglob("*") if _is_image_file(p)]
        else:
            files = [p for p in sub.iterdir() if _is_image_file(p)]

        for src in files:
            try:
                name = safe_path_component(src.name)
                # 再帰時はサブパスで重複しうるため相対パスを含める
                if recursive and src.parent != sub:
                    rel = src.relative_to(sub)
                    parent_parts = [safe_path_component(p) for p in rel.parts[:-1]]
                    dest = (
                        target_root.joinpath(*parent_parts) / name
                        if parent_parts
                        else target_root / name
                    )
                    dest.parent.mkdir(parents=True, exist_ok=True)
                else:
                    dest = target_root / name
                strip_metadata_to_file(src, dest)
                ok += 1
            except Exception as e:
                errors.append(f"{sub.name}/{src.name}: {e}")

    return ok, errors, warnings
