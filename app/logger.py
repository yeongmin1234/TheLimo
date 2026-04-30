import logging
from logging.handlers import TimedRotatingFileHandler
import os

# 프로젝트 최상위 폴더 안에 'logs' 라는 디렉토리를 생성합니다.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# 로거 생성
logger = logging.getLogger("delivery_app")
logger.setLevel(logging.INFO)  # ERROR나 INFO 이상의 로그를 기록함

# 로그 출력 형식 (날짜시간 - 로거이름 - 수준 - 내용)
formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# 1. 파일 핸들러: 매일 자정(UTC/서버시간 기준)마다 로그 파일을 새로 분리하고 최대 30일치 보관
log_file = os.path.join(LOG_DIR, "app.log")
file_handler = TimedRotatingFileHandler(
    log_file, when="midnight", interval=1, backupCount=30, encoding="utf-8"
)
file_handler.setFormatter(formatter)

# 2. 콘솔 핸들러: 파일에 쓰면서도 터미널(까만 창) 화면에 동시에 출력해주기 위함
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

# 핸들러를 로거에 장착
if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
