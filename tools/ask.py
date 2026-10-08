"""사용자에게 질문 보내기(질문 전용 웹후크, config.json 의 question_webhook). 검토 보고 웹후크(discord_webhook)는 쓰지 않는다.
python ask.py "질문" [첨부 이미지 ...]"""
import sys
from webhook import post, text
print(post('question_webhook', text(sys.argv[1]), sys.argv[2:]))
