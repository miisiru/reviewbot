"""디스코드 웹후크로 알림. python notify.py "메시지" [첨부 이미지 ...]"""
import sys
from webhook import post, text
print(post('discord_webhook', text(sys.argv[1]), sys.argv[2:]))
