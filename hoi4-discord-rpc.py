import time
import threading
import sys
import os
import re
from PIL import Image
from pypresence import Presence
import pystray

# ==============================================================================
# [重要] 設定項目
# ==============================================================================
# Discord Developer Portalで取得した19桁のクライアントIDをここに貼り付けてください
CLIENT_ID = "1508508003308011671"

# Linux環境における game.log へのパス（環境に合わせて自動でホームディレクトリを展開します）
LOG_PATH = os.path.expanduser("~/.local/share/Paradox Interactive/Hearts of Iron IV/logs/game.log")

# ==============================================================================
# グローバル状態管理
# ==============================================================================
RPC = None
is_connected = False
tray_icon = None

# ==============================================================================
# Discord 自動接続ロジック（バックグラウンドで常時待機）
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
                
                # 初期状態を設定
                RPC.update(
                    details="Waiting for HoI4 to start...", 
                    state="Main Menu / Lobby", 
                    large_image="hoi4_main_logo"
                )
            except Exception as e:
                print(f"Discord client not found. Retrying in 5 seconds... ({e})")
                RPC = None
                is_connected = False
                time.sleep(5)
        else:
            time.sleep(10)

# ==============================================================================
# HoI4 ログ監視ロジック（Tail -f モード）
# ==============================================================================
def log_watcher_loop():
    global is_connected, RPC
    
    print(f"Watching log file: {LOG_PATH}")
    
    # game.log が生成されるまで待機
    while not os.path.exists(LOG_PATH):
        print("game.log not found. Waiting for HoI4 to launch...")
        time.sleep(5)
        
    with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
        # ファイルの末尾にシークして起動前の古いログをスキップ
        f.seek(0, os.SEEK_END)
        
        while True:
            line = f.readline()
            if not line:
                time.sleep(1) # 新しい行が書き込まれるまで1秒待機
                continue
                
            # プレイヤー国の判定行をキャッチ
            if "is player country" in line:
                # ログ例: "1936.1.1.12: Country 'JAP' (Japan) is player country." からデータを抽出
                match = re.search(r"(\d{4})\.\d+\.\d+\.\d+: Country '([A-Z]{3})' \((.*?)\)", line)
                if match:
                    year = match.group(1)
                    country_tag = match.group(2)
                    country_name = match.group(3)
                    
                    print(f"[Detected] Country: {country_name} ({country_tag}) | Year: {year}")
                    
                    # Discord Rich Presence の表示を更新
                    if is_connected and RPC:
                        try:
                            RPC.update(
                                details=f"Playing as: {country_name} ({country_tag})",
                                state=f"In-game Year: {year}",
                                large_image="hoi4_main_logo",
                                large_text="Hearts of Iron IV",
                                small_image=country_tag.lower(), # 国旗画像アセット（あれば）
                                small_text=country_name
                            )
                        except Exception as e:
                            print(f"Failed to update Discord Presence: {e}")
                            is_connected = False

# ==============================================================================
# タスクトレイ（システムトレイ）管理 ※Linux互換（英語統一）
# ==============================================================================
def create_tray_icon():
    global tray_icon
    # トレイ表示用の簡易アイコン画像を作成 (青色のスクエア)
    icon_image = Image.new('RGB', (64, 64), color=(30, 144, 255))
    
    def on_quit(icon, item):
        print("Shutting down application...")
        icon.stop()
        sys.exit(0)

    # Linuxでの文字コードエラーを避けるため、メニュー項目はすべて英語
    menu = pystray.Menu(
        pystray.MenuItem("Quit App", on_quit)
    )
    
    # アプリ名（ホバーテキスト）も英語表記
    tray_icon = pystray.Icon("HoI4-RPC", icon_image, "HoI4 Log Watcher RPC", menu)
    tray_icon.run()

# ==============================================================================
# メイン処理
# ==============================================================================
if __name__ == "__main__":
    print("=== HoI4 Discord RPC Log Watcher (Linux/Unix Compatible) ===")
    
    # 1. Discord自動接続スレッドを起動
    threading.Thread(target=discord_connection_loop, daemon=True).start()
    
    # 2. ログファイルの常時監視スレッドを起動
    threading.Thread(target=log_watcher_loop, daemon=True).start()
    
    # 3. メインスレッドでタスクトレイを起動（アプリを常駐・待機させる）
    print("Running in system tray. Use the tray icon 'Quit App' to exit.")
    create_tray_icon()