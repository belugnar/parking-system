# app.py
from flask import Flask, render_template, request, jsonify
import sqlite3, os, time, logging

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (NoSuchElementException, TimeoutException,
                                        WebDriverException)
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import chromedriver_autoinstaller

# ----- 설정 -----
DB_NAME = "database.db"
CHROMEDRIVER_PATH = "./chromedriver.exe"   # app.py와 같은 폴더에 chromedriver.exe 위치
# HEADLESS True로 두면 브라우저 창 안 뜸. 디버그 시 False로 바꿔서 눈으로 확인.
HEADLESS = True

# ----------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)


# ---------------- DB 초기화 및 마이그레이션(있는 경우 안전하게 처리)
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS cars (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plate TEXT,
        machine INTEGER DEFAULT 1,
        small INTEGER DEFAULT 0,
        low_emission INTEGER DEFAULT 0,
        exit_order INTEGER DEFAULT 0
    )
    """)
    conn.commit()

    # 안전하게 컬럼 추가 시도 (exist 체크가 없으므로 실패해도 무시)
    try:
        cur.execute("ALTER TABLE cars ADD COLUMN low_emission INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE cars ADD COLUMN exit_order INTEGER DEFAULT 0")
    except Exception:
        pass
    conn.commit()
    conn.close()


init_db()


# ---------------- 저공해 조회 (환경부) - 안정적 구현


def check_low_emission(plate: str) -> bool:
    """
    True  -> 저공해 차량 (환경부에 정보 있음)
    False -> 일반 차량 (조회 차량정보가 없습니다)
    """
    url = "https://ev.or.kr/nportal/buySupprt/initMycarNonpolluCheckAction.do"

    # ✅ 크롬드라이버 자동 설치
    chromedriver_autoinstaller.install()

    # 기본 옵션 준비
    base_options = Options()
    base_options.add_argument("--no-sandbox")
    base_options.add_argument("--disable-dev-shm-usage")
    base_options.add_argument("--window-size=1920,1080")

    if HEADLESS:
        try:
            base_options.add_argument("--headless=new")
        except Exception:
            base_options.add_argument("--headless")

    # ✅ 두 번 시도: headless -> headful (일부 사이트가 headless 차단)
    for attempt_headless in (HEADLESS, False):
        if not attempt_headless:
            # headful 재시도 시 새 옵션으로 초기화
            options = Options()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1920,1080")
        else:
            options = base_options

        driver = None
        try:
            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(20)
            driver.get(url)

            wait = WebDriverWait(driver, 10)
            wait.until(EC.presence_of_element_located((By.ID, "searchWord")))

            search_box = driver.find_element(By.ID, "searchWord")
            search_box.click()
            search_box.clear()
            search_box.send_keys(plate)
            search_box.send_keys("\n")

            time.sleep(0.5)

            # ✅ alert 확인
            try:
                WebDriverWait(driver, 3).until(EC.alert_is_present())
                alert = driver.switch_to.alert
                alert_text = alert.text
                alert.accept()
                logging.info("alert text: %s", alert_text)
                if "조회 차량정보가 없습니다" in alert_text:
                    return False
                else:
                    return True
            except TimeoutException:
                # alert 없음 → 저공해 차량으로 간주
                logging.info("no alert present — treating as 저공해(True)")
                return True

        except (WebDriverException, NoSuchElementException, TimeoutException) as e:
            logging.warning("저공해 조회 오류 (attempt_headless=%s): %s", attempt_headless, e)
            continue

        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    logging.error("저공해 조회 모든 시도 실패 — 일반 차량(False)로 처리")
    return False



# ------------------- Flask 라우트 -------------------
@app.route('/')
def index():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM cars ORDER BY machine, exit_order, id")
    cars = cur.fetchall()
    conn.close()

    # 정리해서 전달 (machine 1~3)
    lots = {1: [], 2: [], 3: []}
    for c in cars:
        lots[int(c["machine"])].append(dict(c))
    return render_template('index.html', lots=lots)


@app.route('/add', methods=['POST'])
def add_car():
    data = request.get_json() or request.form
    plate = data.get('plate', '').strip()
    if not plate:
        return jsonify(success=False, msg="차량번호 입력 필요"), 400
    machine = int(data.get('machine', 1))
    small = 1 if (data.get('small') in (True, 'on', 'true', '1')) else 0

    # 저공해 조회 (시간 걸릴 수 있음)
    try:
        low = 1 if check_low_emission(plate) else 0
    except Exception as e:
        logging.exception("check_low_emission 예외 발생, 기본값 사용")
        low = 0

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO cars (plate, machine, small, low_emission) VALUES (?, ?, ?, ?)",
        (plate, machine, small, low)
    )
    conn.commit()
    conn.close()
    return jsonify(success=True)


@app.route('/list')
def list_cars():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, plate, low_emission, small, machine, exit_order FROM cars ORDER BY machine, exit_order, id")
    rows = cur.fetchall()
    conn.close()
    return jsonify(rows)


@app.route('/queue_exit/<int:car_id>', methods=['POST'])
def queue_exit(car_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT machine, exit_order FROM cars WHERE id=?", (car_id,))
    res = cur.fetchone()
    if not res:
        conn.close()
        return jsonify(success=False), 404
    machine, current_order = res
    if current_order == 0:
        cur.execute("SELECT MAX(exit_order) FROM cars WHERE machine=?", (machine,))
        max_order = cur.fetchone()[0] or 0
        new_order = max_order + 1
        cur.execute("UPDATE cars SET exit_order=? WHERE id=?", (new_order, car_id))
        conn.commit()
    conn.close()
    return jsonify(success=True)


@app.route('/exit/<int:car_id>', methods=['POST'])
def exit_car(car_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT machine, exit_order FROM cars WHERE id=?", (car_id,))
    res = cur.fetchone()
    if not res:
        conn.close()
        return jsonify(success=False), 404
    machine, order = res
    if order == 1:
        cur.execute("DELETE FROM cars WHERE id=?", (car_id,))
        cur.execute("UPDATE cars SET exit_order = exit_order - 1 WHERE machine=? AND exit_order > 1", (machine,))
        conn.commit()
    conn.close()
    return jsonify(success=True)


@app.route('/remove', methods=['POST'])
def remove_car():
    data = request.get_json() or request.form
    car_id = data.get('id')
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM cars WHERE id=?", (car_id,))
    conn.commit()
    conn.close()
    return jsonify(success=True)


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

