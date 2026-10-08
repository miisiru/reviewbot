# 보유 효과 띠 4fps 시트(띠가 0.5초만 뜨는 경우 대비). gp_fast.sh <rev> <vid> <start> <dur>
HERE=$(cd "$(dirname "$0")" && pwd); FF=${FFMPEG:-$(cd "$HERE" && python -c "from paths import FF; print(FF)")}
d=$HERE/../runs/$1; o=$d/gpf$2; mkdir -p $o; rm -f $o/*.jpg
$FF -v error -ss $3 -t $4 -i $d/video$2.mp4 -vf "fps=4,crop=iw*0.3:ih*0.16:iw*0.66:ih*0.55,scale=120:-1,drawtext=text='%{pts\:hms\:$3}':x=1:y=1:fontsize=8:fontcolor=yellow:box=1:boxcolor=black,tile=20x18" -q:v 4 -y $o/%02d.jpg 2>/dev/null
ls $o
