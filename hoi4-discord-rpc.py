import time
import threading
import sys
import os
import re
import zipfile
from PIL import Image
from pypresence import Presence
import pystray

# ==============================================================================
# 設定項目
# ==============================================================================
<<<<<<< HEAD
CLIENT_ID = "YOUR_DISCORD_APPLICATION_ID_HERE"
=======
# Discord Developer Portalで取得した19桁のクライアントIDをここに貼り付けてください
CLIENT_ID = ""
>>>>>>> 926f9bbb32724c8783b8d056ec67971ac5520805

# 各種パス（Linux環境用）
BASE_DIR = os.path.expanduser("~/.local/share/Paradox Interactive/Hearts of Iron IV")
LOG_PATH = os.path.join(BASE_DIR, "logs/game.log")
SAVE_DIR = os.path.join(BASE_DIR, "save games")

# 主要国のTAGを国名に変換する辞書（必要に応じて追記してください）
COUNTRY_MAP = {
    "JAP": "Japan", "GER": "Germany", "SOV": "Soviet Union", "USA": "USA",
    "ENG": "United Kingdom", "FRA": "France", "ITA": "Italy", "CHI": "China",
    "PRC": "Communist China", "RAJ": "British Raj", "MAN": "Manchukuo"
}

# ==============================================================================
# グローバル状態管理
# ==============================================================================
RPC = None
is_connected = False
tray_icon = None
last_updated_date = ""
current_country = "Unknown Country"
current_tag = "TXT"

# ==============================================================================
# 💡 セーブデータからプレイヤー国家のTAGを抜き出す関数
# ==============================================================================
def get_player_country_from_save():
    global current_country, current_tag
    
    if not os.path.exists(SAVE_DIR):
        return
        
    try:
        # 1. セーブファイル（.hoi4）の一覧を取得し、最新のファイルを探す
        files = [os.path.join(SAVE_DIR, f) for f in os.listdir(SAVE_DIR) if f.endswith('.hoi4')]
        if not files:
            return
        latest_save = max(files, key=os.path.getmtime)
        
        # 2. .hoi4ファイルをZIPとして開き、中の「meta」ファイルを読み込む
        if zipfile.is_zipfile(latest_save):
            with zipfile.ZipFile(latest_save, 'r') as z:
                if 'meta' in z.namelist():
                    with z.open('meta') as m:
                        # 先頭の数KBだけ読めば十分
                        content = m.read(4096).decode('utf-8', errors='ignore')
                        
                        # player="JAP" のような記述を正規表現で探す
                        match = re.search(r'player\s*=\s*"([A-Z]{3})"', content)
                        if match:
                            tag = match.group(1)
                            current_tag = tag
                            current_country = COUNTRY_MAP.get(tag, f"Country ({tag})")
                            print(f"[Save Analyzer] Detected Player Country: {current_country}")
    except Exception as e:
        print(f"[Save Analyzer] Error reading save game: {e}")

# ==============================================================================
# Discord 自動接続ロジック
# ==============================================================================
def discord_connection_loop():
    global RPC, is_connected
    while True:
        if not is_connected:
            try:
                print("Connecting to Discord...")
                RPC = Presence(CLIENT_ID)
                RPC.connect()
                is_connected = True
                print("Successfully connected to Discord!")
                RPC.update(details="Waiting for HoI4...", state="Main Menu / Lobby", large_image="hoi4_main_logo")
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
    global is_connected, RPC, last_updated_date, current_country, current_tag
    
    print(f"Watching log file: {LOG_PATH}")
    
    while not os.path.exists(LOG_PATH):
        print("game.log not found. Waiting for HoI4 to launch...")
        time.sleep(5)
        
    # アプリ起動時に、まず一度最新のセーブデータから国名を取っておく
    get_player_country_from_save()
        
    with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
        f.seek(0, os.SEEK_END)
        
        while True:
            line = f.readline()
            if not line:
                time.sleep(1)
                continue
                
            # オートセーブや手動セーブが走った形跡ログがあれば、国名を再スキャンする
            if "Saving game" in line or "Autosaving" in line:
                # セーブが完了するまで少し待ってから読み込む
                time.sleep(3)
                get_player_country_from_save()
            
            # 日付の抽出
            match = re.search(r"^\[\d{2}:\d{2}:\d{2}\]\[(\d{4})\.(\d{2})\.(\d{2})\.\d{2}\]", line)
            if match:
                year, month, day = match.group(1), match.group(2), match.group(3)
                current_date_str = f"{year}/{month}/{day}"
                
                if current_date_str != last_updated_date:
                    last_updated_date = current_date_str
                    print(f"[Date Detected] {current_date_str} | Playing as: {current_country}")
                    
                    if is_connected and RPC:
                        try:
                            RPC.update(
                                details=f"Playing as: {current_country}",
                                state=f"In-game Date: {year}/{month}/{day}",
                                large_image="hoi4_main_logo",
                                large_text="Hearts of Iron IV",
                                small_image=current_tag.lower(),  # 国旗アセット用
                                small_text=current_country
                            )
                        except Exception as e:
                            print(f"Failed to update Discord Presence: {e}")
                            is_connected = False

# ==============================================================================
# タスクトレイ管理
# ==============================================================================
def create_tray_icon():
    global tray_icon
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
    
<<<<<<< HEAD
    create_tray_icon()
=======
    # 3. メインスレッドでタスクトレイを起動（アプリを常駐・待機させる）
    print("Running in system tray. Use the tray icon 'Quit App' to exit.")
    create_tray_icon()
>>>>>>> 926f9bbb32724c8783b8d056ec67971ac5520805
