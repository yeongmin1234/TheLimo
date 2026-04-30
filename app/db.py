import aiomysql
from aiomysql.cursors import DictCursor
from app.config import (
    DB_CHARSET,
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_POOL_MAX_SIZE,
    DB_POOL_MIN_SIZE,
    DB_POOL_RECYCLE,
    DB_PORT,
    DB_USER,
)

db_pool = None

async def init_db_pool():
    global db_pool
    if db_pool is None:
        db_pool = await aiomysql.create_pool(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            db=DB_NAME,
            charset=DB_CHARSET,
            cursorclass=DictCursor,  # IDE 에러 방지를 위해 명시적 경로로 import 함
            autocommit=True,         # 모든 쿼리가 SELECT 위주이므로, 리소스 락을 줄이고 성능을 올리기 위해 True 권장
            minsize=DB_POOL_MIN_SIZE,
            maxsize=DB_POOL_MAX_SIZE,
            pool_recycle=DB_POOL_RECYCLE        # [주의] aiomysql 구버전(0.0.21 이하)을 사용중이시면 이 옵션 때문에 에러가 날 수 있습니다. 에러가 나면 이 줄을 지워주세요.
        )

async def close_db_pool():
    global db_pool
    if db_pool is not None:
        db_pool.close()
        await db_pool.wait_closed()
        db_pool = None

async def get_db():
    """FastAPI의 Depends로 주입하기 위한 제너레이터 함수"""
    global db_pool
    if db_pool is None:
        await init_db_pool()
        
    # async with 구문이 커넥션 대여/자동 반납(finally 효과)을 보장합니다.
    async with db_pool.acquire() as conn:
        yield conn
