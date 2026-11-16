#!/bin/zsh
# 연구실 화면에 쓰는 Clawd 캐릭터 SVG를 설치된 Clawd on Desk 앱에서 agent-lab/clawd/ 로 복사한다.
# 그림은 Clawd on Desk(AGPL-3.0)의 것이라 이 저장소에는 넣지 않는다.
#   scripts/fetch-clawd.sh [Clawd on Desk의 assets/svg 폴더]
HERE="${0:A:h}/.."
SRC="${1:-/Applications/Clawd on Desk.app/Contents/Resources/app.asar.unpacked/assets/svg}"
DST="$HERE/agent-lab/clawd"
NAMES=(error happy idle-living idle-reading mini-crabwalk sleeping working-building
       working-carrying working-thinking working-typing-boss working-typing)
if [[ ! -d "$SRC" ]]; then
  echo "그림 폴더가 없다: $SRC"
  echo "Clawd on Desk를 설치하거나(brew install --cask clawd-on-desk), 그림 폴더 경로를 인자로 준다."
  exit 1
fi
mkdir -p "$DST"
n=0
for name in $NAMES; do
  f="$SRC/clawd-$name.svg"
  [[ -f "$f" ]] && cp "$f" "$DST/" && n=$((n+1)) || echo "없음: clawd-$name.svg"
done
echo "${n}개 복사했다 → $DST"
