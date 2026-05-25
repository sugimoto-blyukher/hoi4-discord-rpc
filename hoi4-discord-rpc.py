import time
import threading
import sys
import os
import re
import zipfile
from datetime import date, timedelta
from PIL import Image
from pypresence import Presence
from country_tags import COUNTRY_MAP

# ==============================================================================
# 設定項目
# ==============================================================================
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def load_env_file(path):
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


load_env_file(ENV_PATH)
CLIENT_ID = os.getenv("CLIENT_ID", "")


# 各種パス（Linux環境用）
BASE_DIR = os.path.expanduser("~/.local/share/Paradox Interactive/Hearts of Iron IV")
LOG_PATH = os.path.join(BASE_DIR, "logs/game.log")
SAVE_DIR = os.path.join(BASE_DIR, "save games")
SAVE_SCAN_INTERVAL_SECONDS = 10
PRESENCE_UPDATE_INTERVAL_SECONDS = 15
MIN_CLOCK_SAMPLE_SECONDS = 5
MAX_GAME_DAYS_PER_REAL_SECOND = 30

# ==============================================================================
# グローバル状態管理
# ==============================================================================
RPC = None
is_connected = False
tray_icon = None
last_updated_date = ""
current_country = "Unknown Country"
current_tag = "TXT"
last_save_scan_time = 0
last_presence_payload = None
last_presence_update_time = 0
observed_game_date = None
clock_anchor_time = 0
measured_game_days_per_second = 0
last_clock_sample_date = None
last_clock_sample_time = 0

# ==============================================================================
# セーブデータからプレイヤー国家のTAGとゲーム内日付を抜き出す関数
# ==============================================================================
def get_latest_save_path():
    if not os.path.exists(SAVE_DIR):
        return None

    files = [os.path.join(SAVE_DIR, f) for f in os.listdir(SAVE_DIR) if f.endswith('.hoi4')]
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def read_save_content(save_path):
    if zipfile.is_zipfile(save_path):
        with zipfile.ZipFile(save_path, 'r') as z:
            names = z.namelist()
            if 'meta' in names:
                with z.open('meta') as m:
                    return m.read(65536).decode('utf-8', errors='ignore')
            if 'gamestate' in names:
                with z.open('gamestate') as g:
                    return g.read(262144).decode('utf-8', errors='ignore')

    with open(save_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read(262144)


def parse_save_state(content):
    tag = None
    date = None

    player_match = re.search(r'player\s*=\s*"([A-Z]{3})"', content)
    if player_match:
        tag = player_match.group(1)

    date_match = re.search(r'date\s*=\s*"?(\d{4})\.(\d{1,2})\.(\d{1,2})(?:\.\d{1,2})?"?', content)
    if date_match:
        year, month, day = date_match.group(1), int(date_match.group(2)), int(date_match.group(3))
        date = f"{year}/{month:02d}/{day:02d}"

    return tag, date


def parse_game_date(date_str):
    match = re.fullmatch(r"(\d{4})/(\d{2})/(\d{2})", date_str)
    if not match:
        return None
    return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))


def format_game_date(game_date):
    return game_date.strftime("%Y/%m/%d")


def update_game_clock(date_str):
    global last_updated_date, observed_game_date, clock_anchor_time
    global measured_game_days_per_second, last_clock_sample_date, last_clock_sample_time

    new_date = parse_game_date(date_str)
    if not new_date:
        return

    now = time.monotonic()
    if observed_game_date and new_date < observed_game_date:
        return

    if last_clock_sample_date and new_date > last_clock_sample_date:
        elapsed_seconds = now - last_clock_sample_time
        elapsed_days = (new_date - last_clock_sample_date).days
        if elapsed_seconds >= MIN_CLOCK_SAMPLE_SECONDS:
            sampled_rate = elapsed_days / elapsed_seconds
            if 0 < sampled_rate <= MAX_GAME_DAYS_PER_REAL_SECOND:
                if measured_game_days_per_second:
                    measured_game_days_per_second = (measured_game_days_per_second * 0.65) + (sampled_rate * 0.35)
                else:
                    measured_game_days_per_second = sampled_rate
                print(f"[Clock] Measured speed: {measured_game_days_per_second:.2f} game days/sec")

    if observed_game_date != new_date:
        observed_game_date = new_date
        clock_anchor_time = now
        last_updated_date = format_game_date(new_date)

    if not last_clock_sample_date or new_date > last_clock_sample_date:
        last_clock_sample_date = new_date
        last_clock_sample_time = now


def get_estimated_game_date():
    if not observed_game_date:
        return last_updated_date or "Unknown Date"
    if measured_game_days_per_second <= 0:
        return format_game_date(observed_game_date)

    elapsed_seconds = max(0, time.monotonic() - clock_anchor_time)
    estimated_days = int(elapsed_seconds * measured_game_days_per_second)
    return format_game_date(observed_game_date + timedelta(days=estimated_days))


def get_clock_state_text():
    estimated_date = get_estimated_game_date()
    if measured_game_days_per_second > 0:
        return f"In-game Date: {estimated_date} ({measured_game_days_per_second:.1f} d/s)"
    return f"In-game Date: {estimated_date}"


def get_player_country_from_save():
    global current_country, current_tag
        
    try:
        latest_save = get_latest_save_path()
        if not latest_save:
            return

        content = read_save_content(latest_save)
        tag, date = parse_save_state(content)

        if tag:
            current_tag = tag
            current_country = COUNTRY_MAP.get(tag, f"Country ({tag})")

        if date:
            update_game_clock(date)

        if tag or date:
            print(f"[Save Analyzer] {os.path.basename(latest_save)} | {current_country} | {get_estimated_game_date()}")
    except Exception as e:
        print(f"[Save Analyzer] Error reading save game: {e}")


def update_presence(force=False):
    global RPC, is_connected, last_presence_payload, last_presence_update_time

    if not is_connected or not RPC:
        return

    state_text = get_clock_state_text()
    payload = (
        current_country,
        current_tag,
        state_text,
    )
    if payload == last_presence_payload:
        return

    now = time.monotonic()
    country_or_tag_changed = (
        not last_presence_payload
        or payload[0] != last_presence_payload[0]
        or payload[1] != last_presence_payload[1]
    )
    if not force and not country_or_tag_changed and now - last_presence_update_time < PRESENCE_UPDATE_INTERVAL_SECONDS:
        return

    try:
        RPC.update(
            details=f"Playing as: {current_country}",
            state=state_text,
            large_image="hoi4_main_logo",
            large_text="Hearts of Iron IV",
            small_image=current_tag.lower(),
            small_text=current_country
        )
        last_presence_payload = payload
        last_presence_update_time = now
    except Exception as e:
        print(f"Failed to update Discord Presence: {e}")
        is_connected = False

# ==============================================================================
# Discord 自動接続ロジック
# ==============================================================================
def discord_connection_loop():
    global RPC, is_connected, last_presence_payload
    if not CLIENT_ID:
        print("CLIENT_ID is not set. Create .env from .env.example and set your Discord Application ID.")
        return

    while True:
        if not is_connected:
            try:
                print("Connecting to Discord...")
                RPC = Presence(CLIENT_ID)
                RPC.connect()
                is_connected = True
                last_presence_payload = None
                print("Successfully connected to Discord!")
                update_presence()
            except Exception as e:
                print(f"Discord client not found. Retrying in 5 seconds... ({e})")
                RPC = None
                is_connected = False
                time.sleep(5)
        else:
            time.sleep(10)

# ==============================================================================
# HoI4 ログ監視ロジック（日付抽出 ＋ セーブ連動ハイブリッド版）
# ==============================================================================
def log_watcher_loop():
    global is_connected, RPC, last_updated_date, current_country, current_tag, last_save_scan_time
    
    print(f"Watching log file: {LOG_PATH}")
    
    while not os.path.exists(LOG_PATH):
        print("game.log not found. Waiting for HoI4 to launch...")
        time.sleep(5)
        
    # アプリ起動時に、まず一度最新のセーブデータから国名を取っておく
    get_player_country_from_save()
    update_presence()
        
    with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
        f.seek(0, os.SEEK_END)
        
        while True:
            line = f.readline()
            if not line:
                if time.time() - last_save_scan_time >= SAVE_SCAN_INTERVAL_SECONDS:
                    last_save_scan_time = time.time()
                    get_player_country_from_save()
                    update_presence()
                time.sleep(1)
                continue
                
            # オートセーブや手動セーブが走った形跡ログがあれば、国名を再スキャンする
            if "Saving game" in line or "Autosaving" in line:
                # セーブが完了するまで少し待ってから読み込む
                time.sleep(3)
                get_player_country_from_save()
                update_presence()
            
            # 日付の抽出
            match = re.search(r"^\[\d{2}:\d{2}:\d{2}\]\[(\d{4})\.(\d{2})\.(\d{2})\.\d{2}\]", line)
            if match:
                year, month, day = match.group(1), match.group(2), match.group(3)
                current_date_str = f"{year}/{month}/{day}"
                
                if current_date_str != last_updated_date:
                    update_game_clock(current_date_str)
                    print(f"[Date Detected] {current_date_str} | Playing as: {current_country}")
                    update_presence()


def presence_updater_loop():
    while True:
        update_presence()
        time.sleep(1)

# ==============================================================================
# タスクトレイ管理
# ==============================================================================
def create_tray_icon():
    global tray_icon
    import pystray

    icon_image = Image.new('RGB', (64, 64), color=(30, 144, 255))
    
    def on_quit(icon, item):
        icon.stop()
        sys.exit(0)

    menu = pystray.Menu(pystray.MenuItem("Quit App", on_quit))
    tray_icon = pystray.Icon("HoI4-RPC", icon_image, "HoI4 Log Watcher RPC", menu)
    tray_icon.run()

# ==============================================================================
# メイン処理
# ==============================================================================
if __name__ == "__main__":
    print("=== HoI4 Discord RPC (Hybrid Save-Log Tracker) ===")
    
    threading.Thread(target=discord_connection_loop, daemon=True).start()
    threading.Thread(target=log_watcher_loop, daemon=True).start()
    threading.Thread(target=presence_updater_loop, daemon=True).start()
    
    create_tray_icon()
