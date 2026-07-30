"""Transcreve um vídeo com WhisperX e salva transcript JSON com timestamps por palavra.

Uso:
    python src/transcribe.py video.mp4 -o output/transcript.json [--model small] [--language pt]
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"


def probe_duration(video: Path) -> float:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def extract_audio(video: Path, wav: Path) -> None:
    subprocess.run(
        [FFMPEG, "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(wav)],
        capture_output=True, check=True,
    )


def transcribe(video: Path, model_name: str, language: str | None,
               device: str, batch_size: int) -> dict:
    import whisperx

    compute_type = "int8" if device == "cpu" else "float16"

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        extract_audio(video, wav)

        model = whisperx.load_model(model_name, device, compute_type=compute_type,
                                    language=language)
        audio = whisperx.load_audio(str(wav))
        result = model.transcribe(audio, batch_size=batch_size)

        lang = result["language"]
        align_model, metadata = whisperx.load_align_model(language_code=lang, device=device)
        result = whisperx.align(result["segments"], align_model, metadata, audio, device,
                                return_char_alignments=False)

    segments = []
    for seg in result["segments"]:
        words = [
            {
                "word": w["word"].strip(),
                "start": round(w["start"], 3),
                "end": round(w["end"], 3),
                "score": round(w.get("score", 0.0), 3),
            }
            for w in seg.get("words", [])
            if "start" in w and "end" in w
        ]
        segments.append({
            "start": round(seg["start"], 3),
            "end": round(seg["end"], 3),
            "text": seg["text"].strip(),
            "words": words,
        })

    return {
        "source": {"path": str(video.resolve()), "duration": round(probe_duration(video), 3)},
        "language": lang,
        "model": model_name,
        "segments": segments,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=Path("output/transcript.json"))
    parser.add_argument("--model", default="small")
    parser.add_argument("--language", default=None,
                        help="código ISO (pt, en...); detecta automaticamente se omitido")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()

    if not args.video.exists():
        sys.exit(f"vídeo não encontrado: {args.video}")

    result = transcribe(args.video, args.model, args.language, args.device, args.batch_size)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    total_words = sum(len(s["words"]) for s in result["segments"])
    print(f"transcript salvo em {args.output} "
          f"({len(result['segments'])} segmentos, {total_words} palavras, "
          f"idioma={result['language']})")


if __name__ == "__main__":
    main()
