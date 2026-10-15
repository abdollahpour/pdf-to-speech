import argparse
import logging
import os
import re
import subprocess
import sys
import threading
from pathlib import Path


class WaitingDots:
    """Cycle `.` `..` `...` on one line until the step finishes."""

    def __init__(self, message: str, interval: float = 0.4):
        self.message = message
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        suffix = "failed" if exc_type else "done"
        sys.stdout.write(f"\r{self.message}... {suffix}\n")
        sys.stdout.flush()
        return False

    def _run(self):
        if not sys.stdout.isatty():
            self._stop.wait()
            return

        frame = 0
        while not self._stop.is_set():
            dots = "." * (frame % 4)
            padding = " " * (3 - len(dots))
            sys.stdout.write(f"\r{self.message}{dots}{padding}")
            sys.stdout.flush()
            frame += 1
            self._stop.wait(self.interval)


VOICES_URL = "https://rhasspy.github.io/piper-samples"
VOICE_NAME = re.compile(r"^[^-]+_[^-]+-[^-]+-.+$")


def default_voices_dir() -> Path:
    """User cache, so a reinstall does not throw away downloaded models."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "pdf-to-speech" / "voices"


def voice_is_saved(voice: str, voices_dir: Path) -> bool:
    for suffix in (".onnx", ".onnx.json"):
        path = voices_dir / f"{voice}{suffix}"
        if not path.is_file() or path.stat().st_size == 0:
            return False
    return True


def ensure_voice(voice: str, voices_dir: Path | None = None) -> Path:
    """Download the voice model on first use and reuse the saved files."""
    if voices_dir is None:
        voices_dir = default_voices_dir()

    if VOICE_NAME.match(voice) is None:
        raise SystemExit(
            f"Unknown voice name '{voice}'.\n"
            f"Find names in the Piper project: {VOICES_URL}"
        )

    if voice_is_saved(voice, voices_dir):
        return voices_dir

    from urllib.error import URLError

    from piper.download_voices import download_voice

    voices_dir.mkdir(parents=True, exist_ok=True)
    try:
        with WaitingDots("Downloading voice"):
            download_voice(voice, voices_dir)
    except (OSError, URLError, ValueError) as exc:
        raise SystemExit(f"Could not download voice '{voice}': {exc}") from exc

    return voices_dir


def pdf_to_speech(pdf_path: Path, output_path: Path, voice: str, voices_dir: Path):
    from docling.document_converter import DocumentConverter

    logging.basicConfig(level=logging.ERROR)

    with WaitingDots("Extracting text"):
        converter = DocumentConverter()
        result = converter.convert(str(pdf_path))
        text = result.document.export_to_text().strip()

    if not text:
        raise ValueError("No text could be extracted from the PDF.")

    text_path = output_path.with_suffix(".txt")
    text_path.write_text(text, encoding="utf-8")
    print(f"Extracted {len(text)} characters.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with WaitingDots("Generating audio"):
        completed = subprocess.run(
            [
                sys.executable,
                "-m", "piper",
                "-m", voice,
                "-f", str(output_path),
                "--input-file", str(text_path),
                "--data-dir", str(voices_dir),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip()
        if detail:
            print(detail, file=sys.stderr)
        raise SystemExit(completed.returncode)

    print(f"Audio saved to: {output_path}")
    print(f"Extracted text saved to: {text_path}")


class HelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.RawDescriptionHelpFormatter,
):
    def __init__(self, prog: str):
        super().__init__(prog, max_help_position=28, width=100)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf-to-speech",
        description="Read a PDF and write it out as spoken audio.",
        epilog=f"""
examples:
  pdf-to-speech chapter.pdf
  pdf-to-speech chapter.pdf -o chapter.wav
  pdf-to-speech chapter.pdf --voice en_US-lessac-medium -o chapter.wav

voices:
  The model is downloaded the first time a name is used, then saved for later runs.
  Saved models live in {default_voices_dir()}.
  Find names in the Piper project:
  {VOICES_URL}
        """.strip(),
        formatter_class=HelpFormatter,
    )
    parser.add_argument(
        "pdf",
        type=Path,
        metavar="PDF",
        help="PDF file to read",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("output.wav"),
        metavar="WAV",
        help="WAV file to write",
    )
    parser.add_argument(
        "--voice",
        default="en_US-lessac-medium",
        metavar="NAME",
        help=(
            "Voice to speak with, downloaded on first use and saved after that. "
            f"Find names in the Piper project: {VOICES_URL}"
        ),
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)

    pdf = args.pdf.expanduser()
    output = args.output.expanduser()
    voice = args.voice.strip()

    if not pdf.is_file():
        parser.error(f"PDF not found: {pdf}")
    if pdf.suffix.lower() != ".pdf":
        parser.error(f"expected a .pdf file: {pdf}")
    if not voice:
        parser.error("voice model name cannot be empty")
    if output.exists() and output.is_dir():
        parser.error(f"output path is a directory: {output}")
    if pdf.resolve() == output.resolve():
        parser.error("output path must be different from the PDF")

    args.pdf = pdf
    args.output = output
    args.voice = voice
    return args


def main() -> None:
    args = parse_args()
    voices_dir = ensure_voice(args.voice)
    pdf_to_speech(args.pdf, args.output, args.voice, voices_dir)
