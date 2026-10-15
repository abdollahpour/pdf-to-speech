# pdf-to-speech

A tiny command-line tool that converts a PDF into high-quality spoken audio.

You give it a PDF. It reads the text aloud and saves a `.wav` file you can play anywhere. It also saves a `.txt` file of the words it read, so you can check them.

You need Python 3.12 or newer.

## Install

Pick one.

With pip:

```bash
pip install pdf-to-speech
```

With uv:

```bash
uv tool install pdf-to-speech
```

Either one adds a `pdf-to-speech` command you can run from the terminal.

## Convert a PDF

```bash
pdf-to-speech chapter.pdf
```

That writes two files in the current folder:

- `output.wav` is the audio
- `output.txt` is the text that was read

To choose the audio file name:

```bash
pdf-to-speech chapter.pdf -o chapter.wav
```

That also writes `chapter.txt` next to the audio.

The first run needs an internet connection. It downloads a voice, and reading the PDF can take a few minutes. Later runs reuse what was already downloaded.

A long PDF makes a long audio file. Leave the command running until it says the audio was saved.

## Choose a voice

The default voice is `en_US-lessac-medium`, a clear American English voice.

```bash
pdf-to-speech chapter.pdf --voice en_US-lessac-medium -o chapter.wav
```

Each voice is downloaded the first time you use it, then kept for next time. Names and samples are listed in the [Piper voice samples](https://rhasspy.github.io/piper-samples).

## Tips

The PDF should contain text you can select and copy. A scan that is only a picture of a page may produce little or no audio.

For every option:

```bash
pdf-to-speech --help
```

## License

[MIT](LICENSE)
