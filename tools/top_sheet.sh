# 위 안내 줄(보유 효과 「…hacked into the game」 「Castorice protected you」 류) 2fps 시트. top_sheet.sh <rev> <vid> <start> <dur>
HERE=$(cd "$(dirname "$0")" && pwd); FF=${FFMPEG:-$(cd "$HERE" && python -c "from paths import FF; print(FF)")}
d=$HERE/../runs/$1; o=$d/top$2; mkdir -p $o; rm -f $o/*.jpg
$FF -v error -ss $3 -t $4 -i $d/video$2.mp4 -vf "fps=2,crop=iw*0.5:ih*0.06:iw*0.3:ih*0.085,scale=320:-1,drawtext=text='%{pts\:hms\:$3}':x=2:y=2:fontsize=10:fontcolor=yellow:box=1:boxcolor=black,tile=6x30" -q:v 4 -y $o/%02d.jpg 2>/dev/null
ls $o
