# 보유 효과 띠 시트, 영상 번호 지정. gp_sheet_v.sh <rev> <vid> <start> <dur>
HERE=$(cd "$(dirname "$0")" && pwd); FF=${FFMPEG:-$(cd "$HERE" && python -c "from paths import FF; print(FF)")}
d=$HERE/../runs/$1; o=$d/gp$2; mkdir -p $o; rm -f $o/*.jpg
$FF -v error -ss $3 -t $4 -i $d/video$2.mp4 -vf "fps=1,crop=iw*0.36:ih*0.42:iw*0.60:ih*0.30,scale=200:-1,drawtext=text='%{pts\:hms\:$3}':x=2:y=2:fontsize=14:fontcolor=yellow:box=1:boxcolor=black,tile=12x10" -q:v 4 -y $o/%02d.jpg 2>/dev/null
ls $o
