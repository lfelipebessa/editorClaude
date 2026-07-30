#!/bin/zsh
# Gera tests/fixture_gaps.mp4 a partir de qualquer vídeo com fala:
# 8s de fala + ~3s de silêncio (vídeo congelado) + 11s de fala.
# Uso: tests/make_fixture.sh /caminho/video_com_fala.mp4
set -e
SRC="$1"
[ -f "$SRC" ] || { echo "uso: $0 <video_com_fala>"; exit 1; }
cd "$(dirname "$0")/.."
/opt/homebrew/bin/ffmpeg -y -v error -i "$SRC" -filter_complex "
[0:v]trim=start=0:end=8,setpts=PTS-STARTPTS,scale=640:-2[v0];
[0:a]atrim=start=0:end=8,asetpts=PTS-STARTPTS[a0];
[0:v]trim=start=8:end=9,setpts=PTS-STARTPTS,scale=640:-2,tpad=stop_mode=clone:stop_duration=3[vgap];
[0:a]atrim=start=8:end=9,asetpts=PTS-STARTPTS,apad=pad_dur=3,volume=enable='gte(t,1)':volume=0[agap];
[0:v]trim=start=9:end=20,setpts=PTS-STARTPTS,scale=640:-2[v1];
[0:a]atrim=start=9:end=20,asetpts=PTS-STARTPTS[a1];
[v0][a0][vgap][agap][v1][a1]concat=n=3:v=1:a=1[v][a]" \
  -map "[v]" -map "[a]" -c:v libx264 -preset fast -crf 23 -c:a aac tests/fixture_gaps.mp4
echo "fixture gerada em tests/fixture_gaps.mp4"
