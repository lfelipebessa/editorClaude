"""Núcleo compartilhado pelos dois pipelines (Reel do canal e cortes de YouTube).

Antes isto morava dentro de adapters/render_ffmpeg.py, que é um CLI — e por
isso 25 arquivos carregavam `sys.path.insert` só para conseguir importar. Agora
é um pacote de verdade: `pip install -e .` uma vez e `from core import ...`
funciona de qualquer lugar.

    core.style      styles/*.json, plataformas, biblioteca de música
    core.filters    cadeias de filtro (cor, áudio, música, acabamento, corte)
    core.media      ffmpeg/ffprobe: sondagem de stream e medição de loudness
    core.transcript palavras, remapeamento para o corte, legendas e SRT
"""

from core.filters import (build_audio_chain, build_color_chain, build_filter,
                          build_finish_chain, build_music_chain, music_gain_db,
                          vertical_filter)
from core.media import (FFMPEG, FFPROBE, measure_loudness,
                        measure_music_loudness, parse_loudnorm_json,
                        pick_streams, probe_resolution)
from core.style import (PROJECT_ROOT, STYLES_DIR, load_style, pick_platform,
                        resolve_music_file)

__all__ = [
    "FFMPEG", "FFPROBE", "PROJECT_ROOT", "STYLES_DIR",
    "build_audio_chain", "build_color_chain", "build_filter",
    "build_finish_chain", "build_music_chain", "load_style", "measure_loudness",
    "measure_music_loudness", "music_gain_db", "parse_loudnorm_json",
    "pick_platform", "pick_streams", "probe_resolution", "resolve_music_file",
    "vertical_filter",
]
