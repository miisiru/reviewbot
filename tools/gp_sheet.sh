# 보유 효과 띠 자리 1초 간격 시트. gp_sheet.sh <rev> <start> <dur>
HERE=$(cd "$(dirname "$0")" && pwd); FF=${FFMPEG:-$(cd "$HERE" && python -c "from paths import FF; print(FF)")}
d=$HERE/../runs/$1; mkdir -p $d/gp; rm -f $d/gp/*.jpg
$FF -v error -ss $2 -t $3 -i $d/video0.mp4 -vf "fps=1,crop=iw*0.36:ih*0.42:iw*0.60:ih*0.30,scale=200:-1,drawtext=text='%{pts\:hms\:$2}':x=2:y=2:fontsize=14:fontcolor=yellow:box=1:boxcolor=black,tile=12x10" -q:v 4 -y $d/gp/%02d.jpg 2>/dev/null
ls $d/gp
