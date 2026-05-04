from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from app.db import init_db_pool, close_db_pool, get_db
from datetime import datetime
from pymysql.err import OperationalError
import time
import os
import re
from app.logger import logger

CACHE_TTL_SECONDS = 60
order_list_cache = {}
dashboard_cache = {}

STATUS_PROGRESS = ("판매접수", "발주요청")
STATUS_COMPLETED = ("출고완료",)
STATUS_CANCELLED = ("발주취소", "취소완료")
PRODUCT_RESERVATION_PATTERN = r"\\[[0-9]{1,2}/[0-9]{1,2}"
PRODUCT_COLUMN_SQL = f"""
    (
        SELECT COALESCE(
            MAX(CASE WHEN ps.PRODUCT REGEXP '{PRODUCT_RESERVATION_PATTERN}' THEN ps.PRODUCT END),
            MAX(ps.PRODUCT)
        )
        FROM scm_sale ps
        WHERE ps.ORD_CODE = o.ord_code
    )
"""

ORDER_COLUMNS = """
    o.idx AS sale_id,
    o.ord_code,
    o.ord_date,
    o.shp_name,
    o.gd_name,
    o.CUSTOMER,
    o.CUSTOMER_MOBILE,
    o.dlv_name,
    o.dlv_tel_1,
    o.dlv_addr_1,
    o.logis_out_no,
    o.ord_dlv_status,
    o.ord_dlv_reqest_date,
    (
        SELECT MAX(sh.REG_DAT)
        FROM scm_shipping sh
        WHERE sh.SALE_ID = o.idx
    ) AS shipping_reg_dat,
""" + PRODUCT_COLUMN_SQL + """ AS PRODUCT,
    r.reservation_date
"""

ORDER_FROM = """
    view_shp_ord_detail o
    LEFT JOIN reservation_info r
        ON o.ord_code COLLATE utf8_unicode_ci = r.ord_code
"""

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: 커넥션 풀 생성
    try:
        await init_db_pool()
    except Exception:
        logger.error("DB 초기 연결에 실패했습니다. 요청 시 다시 연결을 시도합니다.", exc_info=True)
    yield
    # Shutdown: 커넥션 풀 종료
    await close_db_pool()

APP_ROOT_PATH = os.getenv("APP_ROOT_PATH", "/delivery")
app = FastAPI(lifespan=lifespan, root_path=APP_ROOT_PATH)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

@app.exception_handler(OperationalError)
async def db_operational_error_handler(request: Request, exc: OperationalError):
    logger.error("DB 연결 중 에러 발생", exc_info=True)
    return HTMLResponse(
        "<h1>데이터베이스 연결 오류가 발생했습니다.</h1>"
        "<p>DB 서버와 포트 설정을 확인해주세요.</p>",
        status_code=503,
    )

def extract_reservation_date(product):
    if not product:
        return None

    match = re.search(r"\[(\d{1,2})/(\d{1,2})", product)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        return f"2026-{month:02d}-{day:02d}"
    return None

def group_orders(raw_rows):
    """(개선됨) 반복 사용되는 주문 그룹핑(합치기) 로직을 함수로 분리하여 중복 방지"""
    grouped = {}
    for row in raw_rows:
        ord_code = row["ord_code"]
        if ord_code not in grouped:
            reservation_date = extract_reservation_date(row.get("PRODUCT"))
            grouped[ord_code] = {
                "ord_code": row["ord_code"],
                "ord_date": row["ord_date"],
                "reservation_date": reservation_date,
                "ord_dlv_reqest_date": str(row["ord_dlv_reqest_date"]) if row.get("ord_dlv_reqest_date") else None,
                "shp_name": row["shp_name"],
                "CUSTOMER": row["CUSTOMER"],
                "CUSTOMER_MOBILE": row["CUSTOMER_MOBILE"],
                "dlv_name": row["dlv_name"],
                "dlv_tel_1": row["dlv_tel_1"],
                "dlv_addr_1": row["dlv_addr_1"],
                "ord_dlv_status": row["ord_dlv_status"],
                "status_class": get_status_class(row["ord_dlv_status"]),
                "row_class": get_row_class(row["ord_dlv_status"]),
                "item_count": 1,
                "item_names": [row["gd_name"]] if row["gd_name"] else []
            }
        else:
            if not grouped[ord_code].get("reservation_date"):
                grouped[ord_code]["reservation_date"] = extract_reservation_date(row.get("PRODUCT"))
            grouped[ord_code]["item_count"] += 1
            if row["gd_name"]:
                grouped[ord_code]["item_names"].append(row["gd_name"])
    return list(grouped.values())

def classify_dashboard_rows(rows):
    today = datetime.now().date()
    reservation_list = []
    progress_list = []
    complete_list = []

    for row in rows:
        reservation = row.get("reservation_date")
        status = row.get("ord_dlv_status")

        if reservation:
            try:
                reservation_date = datetime.strptime(reservation, "%Y-%m-%d").date()
                if reservation_date >= today:
                    reservation_list.append(row)
                    continue
            except Exception:
                pass

        if status == STATUS_COMPLETED[0]:
            complete_list.append(row)
        else:
            progress_list.append(row)

    reservation_list.sort(key=lambda row: row.get("reservation_date") or "9999-12-31")
    return reservation_list, progress_list, complete_list

def filter_upcoming_reservations(rows):
    today = datetime.now().date()
    upcoming = []

    for row in rows:
        reservation = row.get("reservation_date")
        if not reservation:
            continue

        try:
            reservation_date = datetime.strptime(reservation, "%Y-%m-%d").date()
        except Exception:
            continue

        if reservation_date >= today:
            shipping_reg_dat = row.get("shipping_reg_dat")
            if reservation_date > today and row.get("ord_dlv_status") == STATUS_COMPLETED[0]:
                if not shipping_reg_dat:
                    continue
                if isinstance(shipping_reg_dat, str):
                    shipping_reg_dat = datetime.fromisoformat(shipping_reg_dat)
                if shipping_reg_dat.date() < today:
                    continue
            upcoming.append(row)

    upcoming.sort(key=lambda row: row.get("reservation_date") or "9999-12-31")
    return upcoming

def get_status_class(status):
    status = status or ""
    if status in STATUS_CANCELLED:
        return "status-cancel"
    if status == "출고완료":
        return "status-completed"
    if "반품" in status or "교환" in status:
        return "status-return"
    return "status-progress"

def get_row_class(status):
    return "row-cancel" if (status or "") in STATUS_CANCELLED else ""

def add_status_metadata(rows):
    for row in rows:
        row["reservation_date"] = extract_reservation_date(row.get("PRODUCT"))
        row["status_class"] = get_status_class(row.get("ord_dlv_status"))
        row["row_class"] = get_row_class(row.get("ord_dlv_status"))
        row["item_count"] = 1
        row["item_names"] = [row["gd_name"]] if row.get("gd_name") else []
    return rows

def build_status_where(statuses, recent_months=None, reservation_filter=None):
    placeholders = ", ".join(["%s"] * len(statuses))
    where = f"o.ord_dlv_status IN ({placeholders})"
    if recent_months:
        where += f" AND o.ord_date >= DATE_SUB(CURDATE(), INTERVAL {recent_months} MONTH)"
    if reservation_filter == "reserved":
        where += f"""
        AND EXISTS (
            SELECT 1
            FROM scm_sale rs
            WHERE rs.ORD_CODE = o.ord_code
              AND rs.PRODUCT REGEXP '{PRODUCT_RESERVATION_PATTERN}'
        )
        """
    elif reservation_filter == "walk_in":
        where += f"""
        AND NOT EXISTS (
            SELECT 1
            FROM scm_sale rs
            WHERE rs.ORD_CODE = o.ord_code
              AND rs.PRODUCT REGEXP '{PRODUCT_RESERVATION_PATTERN}'
        )
        """
    return where

async def fetch_order_rows(cursor, statuses, limit, recent_months=None, reservation_filter=None, order_by=None):
    where = build_status_where(statuses, recent_months, reservation_filter)
    order_clause = "o.ord_date DESC"
    if order_by in ("reservation_date_asc", "reservation_date_desc"):
        direction = "ASC" if order_by == "reservation_date_asc" else "DESC"
        reservation_date_sql = """
        STR_TO_DATE(
            CONCAT(
                '2026-',
                LPAD(SUBSTRING_INDEX(SUBSTRING_INDEX(""" + PRODUCT_COLUMN_SQL + """, '[', -1), '/', 1), 2, '0'),
                '-',
                LPAD(SUBSTRING_INDEX(SUBSTRING_INDEX(SUBSTRING_INDEX(""" + PRODUCT_COLUMN_SQL + """, '[', -1), '/', -1), ' ', 1), 2, '0')
            ),
            '%%Y-%%m-%%d'
        )
        """
        order_clause = """
        CASE WHEN """ + reservation_date_sql + """ >= CURDATE() THEN 0 ELSE 1 END,
        """ + reservation_date_sql + " " + direction + """,
        o.ord_date DESC
        """
    query = f"""
    SELECT
        {ORDER_COLUMNS}
    FROM {ORDER_FROM}
    WHERE {where}
    ORDER BY {order_clause}
    LIMIT %s
    """

    await cursor.execute(query, (*statuses, limit))
    return await cursor.fetchall()

async def fetch_upcoming_reservation_rows(cursor, limit=300):
    rows = await fetch_order_rows(
        cursor,
        STATUS_PROGRESS + STATUS_COMPLETED,
        limit,
        recent_months=3,
        reservation_filter="reserved",
        order_by="reservation_date_asc",
    )
    return filter_upcoming_reservations(add_status_metadata(rows))

async def fetch_order_count(cursor, statuses, recent_months=None, distinct_order=False, reservation_filter=None):
    where = build_status_where(statuses, recent_months, reservation_filter)
    count_target = "DISTINCT o.ord_code" if distinct_order else "*"
    query = f"""
    SELECT COUNT({count_target}) AS cnt
    FROM view_shp_ord_detail o
    WHERE {where}
    """

    await cursor.execute(query, statuses)
    row = await cursor.fetchone()
    return row["cnt"] if row else 0

async def fetch_order_detail_rows(cursor, ord_code):
    query = f"""
    SELECT
        {ORDER_COLUMNS}
    FROM {ORDER_FROM}
    WHERE o.ord_code = %s
    ORDER BY o.ord_date DESC
    """

    await cursor.execute(query, (ord_code,))
    return await cursor.fetchall()

async def fetch_order_detail_api_rows(cursor, ord_code):
    query = f"""
    SELECT
        {ORDER_COLUMNS}
    FROM {ORDER_FROM}
    WHERE o.ord_code = %s
    ORDER BY o.ord_date DESC
    """

    await cursor.execute(query, (ord_code,))
    return await cursor.fetchall()

async def complete_order_with_tracking(cursor, ord_code, tracking_number):
    progress_placeholders = ", ".join(["%s"] * len(STATUS_PROGRESS))

    await cursor.execute(
        f"""
        SELECT COUNT(*) AS cnt
        FROM scm_sale
        WHERE ORD_CODE = %s
          AND STATE IN ({progress_placeholders})
        """,
        (ord_code, *STATUS_PROGRESS)
    )
    row = await cursor.fetchone()
    if not row or row["cnt"] == 0:
        return 0

    await cursor.execute(
        f"""
        INSERT INTO scm_shipping (
            STATE, SALE_ID, SALE_MASTER_ID, ORDER_OWNER_ID, SHIP_OWNER_ID,
            REG_DAT, PRODUCT, QTY, ADDRESS, ZIPCODE, MESSAGE, MARKET,
            LOGIS_OUT_NO, CUSTOMER, RECIPIENT, RECIPIENT_TEL,
            RECIPIENT_MOBILE, SHP_CODE, SHP_ORDER_TYPE
        )
        SELECT
            %s, s.IDX, s.MASTER_ID, s.OWNER_ID, s.OWNER_ID,
            NOW(), s.PRODUCT, s.QTY, s.ADDRESS, s.ZIPCODE, s.MESSAGE, s.MARKET,
            %s, s.CUSTOMER, s.RECIPIENT, s.RECIPIENT_TEL,
            s.RECIPIENT_MOBILE, s.SHP_CODE, s.ORD_DLV_TYPE
        FROM scm_sale s
        LEFT JOIN scm_shipping sh ON sh.SALE_ID = s.IDX
        WHERE s.ORD_CODE = %s
          AND s.STATE IN ({progress_placeholders})
          AND sh.SALE_ID IS NULL
        """,
        ("출고완료", tracking_number, ord_code, *STATUS_PROGRESS)
    )

    await cursor.execute(
        f"""
        UPDATE scm_shipping sh
        JOIN scm_sale s ON s.IDX = sh.SALE_ID
        SET sh.LOGIS_OUT_NO = %s,
            sh.STATE = %s
        WHERE s.ORD_CODE = %s
          AND s.STATE IN ({progress_placeholders})
        """,
        (tracking_number, "출고완료", ord_code, *STATUS_PROGRESS)
    )

    await cursor.execute(
        f"""
        UPDATE scm_sale
        SET STATE = %s
        WHERE ORD_CODE = %s
          AND STATE IN ({progress_placeholders})
        """,
        ("출고완료", ord_code, *STATUS_PROGRESS)
    )
    return cursor.rowcount

async def update_completed_order_tracking(cursor, ord_code, tracking_number):
    await cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM scm_sale
        WHERE ORD_CODE = %s
          AND STATE = %s
        """,
        (ord_code, STATUS_COMPLETED[0])
    )
    row = await cursor.fetchone()
    if not row or row["cnt"] == 0:
        return 0
    sale_count = row["cnt"]

    await cursor.execute(
        """
        INSERT INTO scm_shipping (
            STATE, SALE_ID, SALE_MASTER_ID, ORDER_OWNER_ID, SHIP_OWNER_ID,
            REG_DAT, PRODUCT, QTY, ADDRESS, ZIPCODE, MESSAGE, MARKET,
            LOGIS_OUT_NO, CUSTOMER, RECIPIENT, RECIPIENT_TEL,
            RECIPIENT_MOBILE, SHP_CODE, SHP_ORDER_TYPE
        )
        SELECT
            s.STATE, s.IDX, s.MASTER_ID, s.OWNER_ID, s.OWNER_ID,
            NOW(), s.PRODUCT, s.QTY, s.ADDRESS, s.ZIPCODE, s.MESSAGE, s.MARKET,
            %s, s.CUSTOMER, s.RECIPIENT, s.RECIPIENT_TEL,
            s.RECIPIENT_MOBILE, s.SHP_CODE, s.ORD_DLV_TYPE
        FROM scm_sale s
        LEFT JOIN scm_shipping sh ON sh.SALE_ID = s.IDX
        WHERE s.ORD_CODE = %s
          AND s.STATE = %s
          AND sh.SALE_ID IS NULL
        """,
        (tracking_number, ord_code, STATUS_COMPLETED[0])
    )

    await cursor.execute(
        """
        UPDATE scm_shipping sh
        JOIN scm_sale s ON s.IDX = sh.SALE_ID
        SET sh.LOGIS_OUT_NO = %s
        WHERE s.ORD_CODE = %s
          AND s.STATE = %s
        """,
        (tracking_number, ord_code, STATUS_COMPLETED[0])
    )
    return sale_count

async def complete_sale_with_tracking(cursor, ord_code, sale_id, tracking_number):
    progress_placeholders = ", ".join(["%s"] * len(STATUS_PROGRESS))

    await cursor.execute(
        f"""
        SELECT COUNT(*) AS cnt
        FROM scm_sale
        WHERE IDX = %s
          AND ORD_CODE = %s
          AND STATE IN ({progress_placeholders})
        """,
        (sale_id, ord_code, *STATUS_PROGRESS)
    )
    row = await cursor.fetchone()
    if not row or row["cnt"] == 0:
        return 0

    await cursor.execute(
        f"""
        INSERT INTO scm_shipping (
            STATE, SALE_ID, SALE_MASTER_ID, ORDER_OWNER_ID, SHIP_OWNER_ID,
            REG_DAT, PRODUCT, QTY, ADDRESS, ZIPCODE, MESSAGE, MARKET,
            LOGIS_OUT_NO, CUSTOMER, RECIPIENT, RECIPIENT_TEL,
            RECIPIENT_MOBILE, SHP_CODE, SHP_ORDER_TYPE
        )
        SELECT
            %s, s.IDX, s.MASTER_ID, s.OWNER_ID, s.OWNER_ID,
            NOW(), s.PRODUCT, s.QTY, s.ADDRESS, s.ZIPCODE, s.MESSAGE, s.MARKET,
            %s, s.CUSTOMER, s.RECIPIENT, s.RECIPIENT_TEL,
            s.RECIPIENT_MOBILE, s.SHP_CODE, s.ORD_DLV_TYPE
        FROM scm_sale s
        LEFT JOIN scm_shipping sh ON sh.SALE_ID = s.IDX
        WHERE s.IDX = %s
          AND s.ORD_CODE = %s
          AND s.STATE IN ({progress_placeholders})
          AND sh.SALE_ID IS NULL
        """,
        ("출고완료", tracking_number, sale_id, ord_code, *STATUS_PROGRESS)
    )

    await cursor.execute(
        f"""
        UPDATE scm_shipping sh
        JOIN scm_sale s ON s.IDX = sh.SALE_ID
        SET sh.LOGIS_OUT_NO = %s,
            sh.STATE = %s
        WHERE s.IDX = %s
          AND s.ORD_CODE = %s
          AND s.STATE IN ({progress_placeholders})
        """,
        (tracking_number, "출고완료", sale_id, ord_code, *STATUS_PROGRESS)
    )

    await cursor.execute(
        f"""
        UPDATE scm_sale
        SET STATE = %s
        WHERE IDX = %s
          AND ORD_CODE = %s
          AND STATE IN ({progress_placeholders})
        """,
        ("출고완료", sale_id, ord_code, *STATUS_PROGRESS)
    )
    return cursor.rowcount

def get_cached_order_rows(cache_key):
    cached = order_list_cache.get(cache_key)
    if not cached:
        return None

    if time.time() - cached["created_at"] >= CACHE_TTL_SECONDS:
        order_list_cache.pop(cache_key, None)
        return None

    return cached["rows"]

def set_cached_order_rows(cache_key, rows):
    order_list_cache[cache_key] = {
        "created_at": time.time(),
        "rows": rows,
    }

def get_cached_dashboard():
    cached = dashboard_cache.get("home")
    if not cached:
        return None

    if time.time() - cached["created_at"] >= CACHE_TTL_SECONDS:
        dashboard_cache.pop("home", None)
        return None

    return cached["data"]

def set_cached_dashboard(data):
    dashboard_cache["home"] = {
        "created_at": time.time(),
        "data": data,
    }

def clear_cache(cache_key=None):
    if cache_key:
        order_list_cache.pop(cache_key, None)
        if cache_key == "home":
            dashboard_cache.pop("home", None)
        return

    order_list_cache.clear()
    dashboard_cache.clear()

async def render_order_list(
    request,
    conn,
    statuses,
    template_name,
    log_name,
    active_page,
    cache_key,
    recent_months=None,
    reservation_filter=None,
    order_by=None,
    progress_tab=None,
    group_rows=True,
):
    try:
        raw_rows = get_cached_order_rows(cache_key)

        if raw_rows is None:
            async with conn.cursor() as cursor:
                start = time.time()
                raw_rows = await fetch_order_rows(cursor, statuses, 100, recent_months, reservation_filter, order_by)
                set_cached_order_rows(cache_key, raw_rows)
                print(f"{log_name} query time:", time.time() - start)
        else:
            print(f"{log_name} cache hit")

        rows = group_orders(raw_rows) if group_rows else add_status_metadata(raw_rows)

        return templates.TemplateResponse(
            template_name,
            {
                "rows": rows,
                "active_page": active_page,
                "cache_key": cache_key,
                "progress_tab": progress_tab,
                "request": request,
            }
        )

    except Exception as e:
        logger.error("라우터 통신 중 에러 발생", exc_info=True)
        return HTMLResponse("<h1>서버 에러가 발생했습니다. logs 폴더를 확인해주세요.</h1>", status_code=500)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, conn=Depends(get_db)):
    try:
        data = get_cached_dashboard()

        if data is None:
            async with conn.cursor() as cursor:
                progress_count = await fetch_order_count(cursor, STATUS_PROGRESS, distinct_order=True)
                completed_count = await fetch_order_count(cursor, STATUS_COMPLETED, recent_months=3, distinct_order=True)
                cancelled_count = await fetch_order_count(cursor, STATUS_CANCELLED, recent_months=3, distinct_order=True)
                reservation_list = await fetch_upcoming_reservation_rows(cursor)
                dashboard_rows = add_status_metadata(
                    await fetch_order_rows(cursor, STATUS_PROGRESS + STATUS_COMPLETED, 300, recent_months=3)
                )
                _, progress_list, complete_list = classify_dashboard_rows(dashboard_rows)
                all_list = (reservation_list + progress_list + complete_list)[:20]
                data = {
                    "progress_count": progress_count,
                    "completed_count": completed_count,
                    "cancelled_count": cancelled_count,
                    "all_list": all_list,
                    "reservation_list": reservation_list[:20],
                    "progress_list": progress_list[:20],
                    "complete_list": complete_list[:20],
                    "completed_rows": complete_list[:20],
                }
                set_cached_dashboard(data)
        else:
            print("home cache hit")

        return templates.TemplateResponse(
            "index.html",
            {**data, "active_page": "home", "cache_key": "home", "request": request}
        )

    except Exception as e:
        logger.error("라우터 통신 중 에러 발생", exc_info=True)
        return HTMLResponse("<h1>서버 에러가 발생했습니다. logs 폴더를 확인해주세요.</h1>", status_code=500)

@app.get("/refresh-cache/{cache_key}")
async def refresh_cache(cache_key: str):
    allowed_keys = {"home", "progress", "progress_walk_in", "progress_reserved", "completed", "cancelled"}
    if cache_key not in allowed_keys:
        return {"ok": False, "message": "지원하지 않는 캐시 키입니다."}

    clear_cache(cache_key)
    return {"ok": True, "cache_key": cache_key}

@app.get("/progress", response_class=HTMLResponse)
async def progress(request: Request, conn=Depends(get_db)):
    return await render_order_list(
        request,
        conn,
        STATUS_PROGRESS,
        "progress.html",
        "progress",
        "progress",
        "progress",
        recent_months=3,
        progress_tab="all",
    )

@app.get("/progress/walk-in", response_class=HTMLResponse)
async def progress_walk_in(request: Request, conn=Depends(get_db)):
    return await render_order_list(
        request,
        conn,
        STATUS_PROGRESS,
        "progress.html",
        "progress_walk_in",
        "progress",
        "progress_walk_in",
        recent_months=3,
        reservation_filter="walk_in",
        progress_tab="walk_in",
    )

@app.get("/progress/reserved", response_class=HTMLResponse)
async def progress_reserved(request: Request, conn=Depends(get_db)):
    try:
        rows = get_cached_order_rows("progress_reserved")

        if rows is None:
            async with conn.cursor() as cursor:
                start = time.time()
                rows = await fetch_upcoming_reservation_rows(cursor)
                set_cached_order_rows("progress_reserved", rows)
                print("progress_reserved query time:", time.time() - start)
        else:
            print("progress_reserved cache hit")

        return templates.TemplateResponse(
            "progress.html",
            {
                "rows": rows,
                "active_page": "progress",
                "cache_key": "progress_reserved",
                "progress_tab": "reserved",
                "request": request,
            }
        )

    except Exception as e:
        logger.error("라우터 통신 중 에러 발생", exc_info=True)
        return HTMLResponse("<h1>서버 에러가 발생했습니다. logs 폴더를 확인해주세요.</h1>", status_code=500)

@app.get("/completed", response_class=HTMLResponse)
async def completed(request: Request, conn=Depends(get_db)):
    return await render_order_list(
        request,
        conn,
        STATUS_COMPLETED,
        "completed.html",
        "completed",
        "completed",
        "completed",
        recent_months=3
    )

@app.get("/cancelled", response_class=HTMLResponse)
async def cancelled(request: Request, conn=Depends(get_db)):
    return await render_order_list(
        request,
        conn,
        STATUS_CANCELLED,
        "cancelled.html",
        "cancelled",
        "cancelled",
        "cancelled",
        recent_months=3
    )

@app.get("/api/order/{ord_code}")
async def order_detail_api(ord_code: str, conn=Depends(get_db)):
    try:
        async with conn.cursor() as cursor:
            rows = add_status_metadata(await fetch_order_detail_api_rows(cursor, ord_code))
            return {"ord_code": ord_code, "items": rows}

    except Exception as e:
        logger.error("주문 상세 API 통신 중 에러 발생", exc_info=True)
        return {"ord_code": ord_code, "items": [], "error": "주문 상세 정보를 불러오지 못했습니다."}

@app.post("/api/order/{ord_code}/tracking")
async def save_tracking_number(ord_code: str, request: Request, conn=Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="요청 형식이 올바르지 않습니다.")

    tracking_number = str(payload.get("tracking_number") or "").strip()
    if not tracking_number:
        raise HTTPException(status_code=400, detail="운송장번호를 입력해주세요.")
    if len(tracking_number) > 30:
        raise HTTPException(status_code=400, detail="운송장번호는 30자 이하로 입력해주세요.")

    async with conn.cursor() as cursor:
        await conn.begin()
        try:
            await cursor.execute(
                """
                SELECT DISTINCT STATE
                FROM scm_sale
                WHERE ORD_CODE = %s
                """,
                (ord_code,)
            )
            status_rows = await cursor.fetchall()
            statuses = {row["STATE"] for row in status_rows}

            if not statuses:
                await conn.rollback()
                raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")

            if statuses.intersection(STATUS_PROGRESS):
                updated_count = await complete_order_with_tracking(cursor, ord_code, tracking_number)
                action = "completed"
            elif statuses == {STATUS_COMPLETED[0]}:
                updated_count = await update_completed_order_tracking(cursor, ord_code, tracking_number)
                action = "updated"
            else:
                await conn.rollback()
                raise HTTPException(status_code=409, detail="운송장번호를 변경할 수 없는 주문 상태입니다.")

            if updated_count == 0:
                await conn.rollback()
                raise HTTPException(status_code=409, detail="운송장번호를 저장할 주문을 찾을 수 없습니다.")

            await conn.commit()
            rows = add_status_metadata(await fetch_order_detail_api_rows(cursor, ord_code))
        except HTTPException:
            raise
        except Exception:
            await conn.rollback()
            logger.error("운송장번호 저장 중 에러 발생", exc_info=True)
            raise HTTPException(status_code=500, detail="운송장번호 저장에 실패했습니다.")

    clear_cache()
    return {
        "ok": True,
        "action": action,
        "ord_code": ord_code,
        "tracking_number": tracking_number,
        "items": rows,
    }

@app.post("/api/order/{ord_code}/item/{sale_id}/tracking")
async def save_item_tracking_number(ord_code: str, sale_id: int, request: Request, conn=Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="요청 형식이 올바르지 않습니다.")

    tracking_number = str(payload.get("tracking_number") or "").strip()
    if not tracking_number:
        raise HTTPException(status_code=400, detail="운송장번호를 입력해주세요.")
    if len(tracking_number) > 30:
        raise HTTPException(status_code=400, detail="운송장번호는 30자 이하로 입력해주세요.")

    async with conn.cursor() as cursor:
        await conn.begin()
        try:
            updated_count = await complete_sale_with_tracking(cursor, ord_code, sale_id, tracking_number)
            if updated_count == 0:
                await conn.rollback()
                raise HTTPException(status_code=409, detail="운송장번호를 저장할 상품을 찾을 수 없습니다.")

            await conn.commit()
        except HTTPException:
            raise
        except Exception:
            await conn.rollback()
            logger.error("상품별 운송장번호 저장 중 에러 발생", exc_info=True)
            raise HTTPException(status_code=500, detail="운송장번호 저장에 실패했습니다.")

    clear_cache()
    return {
        "ok": True,
        "action": "completed",
        "ord_code": ord_code,
        "sale_id": sale_id,
        "tracking_number": tracking_number,
    }

@app.post("/api/order/{ord_code}/reservation")
async def save_reservation_date(ord_code: str, request: Request, conn=Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="요청 형식이 올바르지 않습니다.")

    reservation_date = str(payload.get("reservation_date") or "").strip()
    if reservation_date:
        try:
            time.strptime(reservation_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="예약일 형식이 올바르지 않습니다.")

    async with conn.cursor() as cursor:
        try:
            if reservation_date:
                await cursor.execute(
                    """
                    INSERT INTO reservation_info (ord_code, reservation_date)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE reservation_date = VALUES(reservation_date)
                    """,
                    (ord_code, reservation_date)
                )
            else:
                await cursor.execute(
                    """
                    DELETE FROM reservation_info
                    WHERE ord_code = %s
                    """,
                    (ord_code,)
                )
        except Exception:
            logger.error("예약일 저장 중 에러 발생", exc_info=True)
            raise HTTPException(status_code=500, detail="예약일 저장에 실패했습니다.")

    clear_cache()
    return {"ok": True, "ord_code": ord_code, "reservation_date": reservation_date or None}

@app.get("/order/{ord_code}", response_class=HTMLResponse)
async def order_detail(ord_code: str, request: Request, conn=Depends(get_db)):
    try:
        async with conn.cursor() as cursor:
            rows = add_status_metadata(await fetch_order_detail_rows(cursor, ord_code))

            return templates.TemplateResponse(
                "order_detail.html",
                {
                    "ord_code": ord_code,
                    "rows": rows,
                    "active_page": "",
                    "request": request,
                }
            )

    except Exception as e:
        logger.error("라우터 통신 중 에러 발생", exc_info=True)
        return HTMLResponse("<h1>서버 에러가 발생했습니다. logs 폴더를 확인해주세요.</h1>", status_code=500)
