import argparse
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import wave
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
AUDIO_SUFFIXES = {".mp3", ".wav"}


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


def run_piper(text_path: Path, wav_path: Path, voice: str, voices_dir: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m", "piper",
            "-m", voice,
            "-f", str(wav_path),
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


def wav_to_mp3(wav_path: Path, mp3_path: Path) -> None:
    """Encode speech audio to MP3. The WAV file is left for the caller to remove."""
    import lameenc

    with wave.open(str(wav_path), "rb") as wav:
        rate = wav.getframerate()
        channels = wav.getnchannels()
        if wav.getsampwidth() != 2 or channels not in (1, 2) or rate <= 0:
            raise SystemExit("Could not encode MP3 from the generated audio.")

        encoder = lameenc.Encoder()
        encoder.set_bit_rate(128)
        encoder.set_in_sample_rate(rate)
        encoder.set_channels(channels)
        encoder.set_quality(2)

        partial = mp3_path.with_name(mp3_path.name + ".part")
        try:
            with partial.open("wb") as mp3:
                while True:
                    pcm = wav.readframes(rate)
                    if not pcm:
                        break
                    encoded = encoder.encode(pcm)
                    if encoded:
                        mp3.write(encoded)
                tail = encoder.flush()
                if tail:
                    mp3.write(tail)
            partial.replace(mp3_path)
        finally:
            partial.unlink(missing_ok=True)


def pdf_to_speech(
    pdf_path: Path,
    output_path: Path,
    text_path: Path,
    voice: str,
    voices_dir: Path,
):
    from docling.document_converter import DocumentConverter

    logging.basicConfig(level=logging.ERROR)

    with WaitingDots("Extracting text"):
        converter = DocumentConverter()
        result = converter.convert(str(pdf_path))
        text = result.document.export_to_text().strip()

    if not text:
        raise ValueError("No text could be extracted from the PDF.")

    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(text, encoding="utf-8")
    print(f"Extracted {len(text)} characters.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with WaitingDots("Generating audio"):
        if output_path.suffix.lower() == ".mp3":
            fd, name = tempfile.mkstemp(
                prefix=".pdf-to-speech-",
                suffix=".wav",
                dir=output_path.parent,
            )
            os.close(fd)
            wav_path = Path(name)
            try:
                run_piper(text_path, wav_path, voice, voices_dir)
                wav_to_mp3(wav_path, output_path)
            finally:
                wav_path.unlink(missing_ok=True)
        else:
            run_piper(text_path, output_path, voice, voices_dir)

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
  pdf-to-speech chapter.pdf -o audiobook.mp3
  pdf-to-speech chapter.pdf -o audiobook.wav
  pdf-to-speech chapter.pdf --voice en_US-lessac-medium

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
        default=argparse.SUPPRESS,
        metavar="FILE",
        help="Audio file to write, .mp3 or .wav (default: the PDF path with .mp3)",
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
    output = getattr(args, "output", None)
    output = pdf.with_suffix(".mp3") if output is None else output.expanduser()
    text = pdf.with_suffix(".txt")
    voice = args.voice.strip()

    if not pdf.is_file():
        parser.error(f"PDF not found: {pdf}")
    if pdf.suffix.lower() != ".pdf":
        parser.error(f"expected a .pdf file: {pdf}")
    if output.suffix.lower() not in AUDIO_SUFFIXES:
        parser.error(f"output must be a .mp3 or .wav file: {output}")
    if not voice:
        parser.error("voice model name cannot be empty")
    if output.exists() and output.is_dir():
        parser.error(f"output path is a directory: {output}")
    if text.exists() and text.is_dir():
        parser.error(f"text path is a directory: {text}")
    if pdf.resolve() == output.resolve():
        parser.error("output path must be different from the PDF")
    if output.resolve() == text.resolve():
        parser.error("output path must be different from the text file")

    args.pdf = pdf
    args.output = output
    args.text = text
    args.voice = voice
    return args


def main() -> None:
    args = parse_args()
    voices_dir = ensure_voice(args.voice)
    pdf_to_speech(args.pdf, args.output, args.text, args.voice, voices_dir)
