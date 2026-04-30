import aiomysql
from aiomysql.cursors import DictCursor
from app.logger import logger
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

async def ensure_reservation_info_schema():
    if db_pool is None:
        return

    async with db_pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS reservation_info (
                    ord_code VARCHAR(100) NOT NULL PRIMARY KEY,
                    reservation_date DATE NULL,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP
                ) CHARACTER SET utf8 COLLATE utf8_unicode_ci
                """
            )

            await cursor.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'reservation_info'
                  AND COLUMN_NAME = 'reservation_date'
                """
            )
            row = await cursor.fetchone()
            if not row or row["cnt"] == 0:
                await cursor.execute(
                    """
                    ALTER TABLE reservation_info
                    ADD COLUMN reservation_date DATE NULL
                    """
                )

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
        try:
            await ensure_reservation_info_schema()
        except Exception:
            logger.error("reservation_info 스키마 확인 중 에러 발생", exc_info=True)

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
