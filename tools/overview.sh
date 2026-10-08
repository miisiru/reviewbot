# 영상 전체 한 장 훑기. overview.sh <rev> [video idx=0] [간격초=auto]
HERE=$(cd "$(dirname "$0")" && pwd); FF=${FFMPEG:-$(cd "$HERE" && python -c "from paths import FF; print(FF)")}
d=$HERE/../runs/$1; i=${2:-0}; v=$d/video$i.mp4
dur=$($FF -i $v 2>&1 | grep -o "Duration: [0-9:.]*" | awk -F'[: ]' '{print $3*3600+$4*60+$5}')
step=${3:-$(awk -v d=$dur 'BEGIN{s=int(d/200)+1; if(s<2)s=2; print s}')}
n=$(awk -v d=$dur -v s=$step 'BEGIN{print int(d/s)+1}'); rows=$(( (n+9)/10 ))
$FF -v error -i $v -vf "fps=1/$step,scale=320:-1,drawtext=text='%{pts\:hms}':x=4:y=4:fontsize=16:fontcolor=yellow:box=1:boxcolor=black,tile=10x$rows" -frames:v 1 -q:v 3 -y $d/all$i.jpg 2>/dev/null
echo "dur=$dur step=$step -> $d/all$i.jpg"
