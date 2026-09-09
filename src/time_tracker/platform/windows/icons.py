"""Best-effort executable icons, cached outside SQLite by normalized path hash."""

import hashlib
import logging
from pathlib import Path

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from time_tracker.diagnostics.performance import measured

logger = logging.getLogger(__name__)
ICON_RENDER_VERSION = "2"


def icon_key(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()


class IconCache:
    def __init__(self, directory: Path):
        self.directory = directory
        self._attempted = set()

    @measured("icons.ensure")
    def ensure(self, path: str) -> Path | None:
        destination = self.directory / f"{icon_key(path)}.png"
        if path in self._attempted:
            return destination if self._is_current(destination) else None
        self._attempted.add(path)
        try:
            if self._is_current(destination):
                return destination
            self.directory.mkdir(parents=True, exist_ok=True)
            image = extract_icon(path)
            if image is None:
                return None
            temporary = destination.with_suffix(".tmp")
            try:
                metadata = PngInfo()
                metadata.add_text("time_tracker_render_version", ICON_RENDER_VERSION)
                image.save(temporary, format="PNG", pnginfo=metadata)
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
            return destination
        except Exception:
            # An icon is optional; malformed resources or cache failures cannot stop tracking.
            logger.debug("Executable icon unavailable", exc_info=True)
            return None

    @staticmethod
    def _is_current(path: Path) -> bool:
        try:
            with Image.open(path) as image:
                return image.info.get("time_tracker_render_version") == ICON_RENDER_VERSION
        except (OSError, ValueError):
            return False


def extract_icon(path: str) -> Image.Image | None:
    import win32con
    import win32gui
    import win32ui

    large, small = win32gui.ExtractIconEx(path, 0, 1)
    icons = large + small
    if not icons:
        return None

    def render(background):
        screen = win32gui.GetDC(0)
        source = win32ui.CreateDCFromHandle(screen)
        target = source.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        previous = None
        try:
            bitmap.CreateCompatibleBitmap(source, 32, 32)
            previous = target.SelectObject(bitmap)
            target.FillSolidRect((0, 0, 32, 32), background)
            win32gui.DrawIconEx(
                target.GetSafeHdc(), 0, 0, icons[0], 32, 32, 0, 0, win32con.DI_NORMAL
            )
            return Image.frombuffer(
                "RGB", (32, 32), bitmap.GetBitmapBits(True), "raw", "BGRX", 0, 1
            )
        finally:
            if previous is not None:
                target.SelectObject(previous)
            target.DeleteDC()
            win32gui.DeleteObject(bitmap.GetHandle())
            win32gui.ReleaseDC(0, screen)

    try:
        black, white = render(0), render(0xFFFFFF)
        pixels = []
        dark_bytes, light_bytes = black.tobytes(), white.tobytes()
        for offset in range(0, len(dark_bytes), 3):
            dark, light = dark_bytes[offset : offset + 3], light_bytes[offset : offset + 3]
            alpha = 255 - max(w - b for b, w in zip(dark, light, strict=True))
            rgb = tuple(min(255, round(c * 255 / alpha)) for c in dark) if alpha else (0, 0, 0)
            pixels.append((*rgb, alpha))
        result = Image.new("RGBA", (32, 32))
        result.putdata(pixels)
        return result
    finally:
        for icon in icons:
            win32gui.DestroyIcon(icon)
