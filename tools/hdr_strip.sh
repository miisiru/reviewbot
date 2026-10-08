# 왼쪽 위 머리글(탭 / 길 / 이름) 띠. hdr_strip.sh <rev> <vid idx> <start> <dur> [fps=2]
HERE=$(cd "$(dirname "$0")" && pwd); FF=${FFMPEG:-$(cd "$HERE" && python -c "from paths import FF; print(FF)")}
d=$HERE/../runs/$1; fps=${5:-2}
n=$(awk -v d=$4 -v f=$fps 'BEGIN{print int(d*f)}'); rows=$(( (n+7)/8 ))
$FF -v error -ss $3 -t $4 -i $d/video$2.mp4 -vf "fps=$fps,crop=iw*0.3:ih*0.075:0:0,scale=360:-1,drawtext=text='%{pts\:hms\:$3}':x=250:y=2:fontsize=10:fontcolor=yellow:box=1:boxcolor=black,tile=8x$rows" -frames:v 1 -y $d/hdr$2_$3.png 2>/dev/null
echo $d/hdr$2_$3.png
