# 쇼케이스 전체 화면 시트(성혼·광추 탭 찾기용). GP 시트와 같은 방식(구간 시작만 키프레임 탐색 + 연속 디코드)이라 안전하고 빠르다.
# scan_sheet.sh <rev> <vid> <start> <dur> [fps(기본 1)] [cols(기본 10)]
HERE=$(cd "$(dirname "$0")" && pwd); FF=${FFMPEG:-$(cd "$HERE" && python -c "from paths import FF; print(FF)")}
d=$HERE/../runs/$1; o=$d/scan$2; mkdir -p $o; rm -f $o/*.jpg
fps=${5:-1}; cols=${6:-10}
n=$(python -c "import math;print(math.ceil($4*$fps))")
rows=$(python -c "import math;print(math.ceil($n/$cols))")
$FF -v error -ss $3 -t $4 -i $d/video$2.mp4 -vf "fps=$fps,scale=240:-1,drawtext=text='%{pts\:hms\:$3}':x=1:y=1:fontsize=10:fontcolor=yellow:box=1:boxcolor=black,tile=${cols}x${rows}" -q:v 3 -y $o/%02d.jpg 2>/dev/null
ls $o
