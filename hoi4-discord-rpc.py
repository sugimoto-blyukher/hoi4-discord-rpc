import time
import threading
import sys
import os
import re
from PIL import Image
from pypresence import Presence
import pystray

# ==============================================================================
# 設定項目
# ==============================================================================
CLIENT_ID = "YOUR_DISCORD_APPLICATION_ID_HERE"

# あなたのPCのgame.logへのパスを指定してください（Windowsの例）
LOG_PATH = os.path.expanduser(r"/.local/share/Paradox Interactive/Hearts of Iron IV/logs/game.log")

# ==============================================================================
# グローバル変数
# ==============================================================================
RPC = None
is_connected = False
tray_icon = None

# ==============================================================================
# Discord 自動接続ロジック
# ==============================================================================
def discord_connection_loop():
    global RPC, is_connected
    while True:
        if not is_connected:
            try:
                print("Discordへの自動接続を試みています...")
                RPC = Presence(CLIENT_ID)
                RPC.connect()
                is_connected = True
                print("Discordへの接続に成功しました。")
                RPC.update(details="HoI4 起動待機中...", state="ログの出力を待っています...", large_image="hoi4_main_logo")
            except Exception as e:
                print(f"Discordが見つかりません。5秒後に再試行します... ({e})")
                RPC = None
                is_connected = False
                time.sleep(5)
        else:
            time.sleep(10)

# ==============================================================================
# ログファイル監視ロジック（Tail -f の再現）
# ==============================================================================
def log_watcher_loop():
    global is_connected, RPC
    
    print(f"ログファイルの監視を開始しました: {LOG_PATH}")
    
    # ファイルが生成されるまで待機
    while not os.path.exists(LOG_PATH):
        print("game.log が見つかりません。HoI4の起動を待っています...")
        time.sleep(5)
        
    # ログファイルを読み込みモードで開く
    with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
        # まずファイルの末尾までシーク（過去の古いログをスキップ）
        f.seek(0, os.SEEK_END)
        
        while True:
            line = f.readline()
            if not line:
                # 新しい行がなければ少し待って再読込 (ポーリング)
                time.sleep(1)
                continue
                
            # ログの行を解析する正規表現 (例: "1936.1.1.12: Country 'JAP' (Japan) is player country.")
            # ※実際のgame.logの中身に合わせてここのパターンは調整してください
            if "is player country" in line:
                # 正規表現で 年、TAG、国名 を抽出
                match = re.search(r"(\d{4})\.\d+\.\d+\.\d+: Country '([A-Z]{3})' \((.*?)\)", line)
                if match:
                    year = match.group(1)
                    country_tag = match.group(2)
                    country_name = match.group(3)
                    
                    print(f"[検知] 国: {country_name} ({country_tag}) | 年度: {year}年")
                    
                    # Discordのステータスを更新
                    if is_connected and RPC:
                        try:
                            RPC.update(
                                details=f"プレイ国家: {country_name} ({country_tag})",
                                state=f"ゲーム内年度: {year}年",
                                large_image="hoi4_main_logo",
                                large_text="Hearts of Iron IV",
                                small_image=country_tag.lower(),
                                small_text=country_name
                            )
                        except Exception as e:
                            print(f"Discord更新エラー: {e}")
                            is_connected = False

# ==============================================================================
# タスクトレイ（システムトレイ）常駐管理
# ==============================================================================
def create_tray_icon():
    global tray_icon
    icon_image = Image.new('RGB', (64, 64), color=(30, 144, 255)) # 青色のアイコン
    
    def on_quit(icon, item):
        print("アプリケーションを終了します...")
        icon.stop()
        sys.exit(0)

    menu = pystray.Menu(pystray.MenuItem("終了", on_quit))
    tray_icon = pystray.Icon("HoI4-RPC", icon_image, "HoI4 ログ監視 RPC", menu)
    tray_icon.run()

# ==============================================================================
# メイン
# ==============================================================================
if __name__ == "__main__":
    print("--- HoI4 Discord RPC ログ監視版 ---")
    
    # 1. Discord自動接続スレッド開始
    threading.Thread(target=discord_connection_loop, daemon=True).start()
    
    # 2. ログ監視スレッド開始
    threading.Thread(target=log_watcher_loop, daemon=True).start()
    
    # 3. メインスレッドでタスクトレイ常駐
    create_tray_icon()