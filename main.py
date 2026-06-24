import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncioScheduler
from datetime import datetime
import json
import os
from flask import Flask
from threading import Thread

# --- [웹 서버 설정: 업타임 로봇용] ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- [디스코드 봇 설정] ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True         

bot = commands.Bot(command_prefix="!", intents=intents)

TOKEN = os.environ.get('DISCORD_TOKEN') # 래플릿 Secrets 환경변수 사용

# 🛠️ [채널 ID 설정] 본인 서버의 채널 ID로 각각 수정해 주세요!
RECRUIT_CHANNEL_ID = 1487560087890297002  # "링크공유" 채널 ID (모집 버튼이 올라갈 곳)
ALARM_CHANNEL_ID = 1519281328766455959    # "알림" 채널 ID (실제 알람 멘션이 갈 곳)

DATA_FILE = "alarm_users.json"
alarm_users = set()
scheduler = AsyncioScheduler(timezone="Asia/Seoul")

def load_data():
    global alarm_users
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                alarm_users = set(json.load(f))
                print(f"[Data Loaded] {len(alarm_users)} users.")
        except Exception as e:
            print(f"Load Error: {e}")

def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(list(alarm_users), f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Save Error: {e}")

# 🔘 [버튼 UI 정의]
class AlarmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="알람 신청하기 ⭕", style=discord.ButtonStyle.green, custom_id="btn_register")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        if user_id not in alarm_users:
            alarm_users.add(user_id)
            save_data()
            await interaction.response.send_message("🔔 세라 라이브 알람 신청이 완료되었습니다! (홀수 시각 정각 멘션)", ephemeral=True)
        else:
            await interaction.response.send_message("ℹ️ 이미 알람 신청이 되어 있습니다.", ephemeral=True)

    @discord.ui.button(label="알람 취소하기 ❌", style=discord.ButtonStyle.red, custom_id="btn_cancel")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        if user_id in alarm_users:
            alarm_users.remove(user_id)
            save_data()
            await interaction.response.send_message("🔕 세라 라이브 알람 신청이 취소되었습니다.", ephemeral=True)
        else:
            await interaction.response.send_message("ℹ️ 현재 신청되어 있지 않습니다.", ephemeral=True)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    load_data()
    bot.add_view(AlarmView())
    
    # 1. "일반" 채널에 알람 모집 버튼 메시지 발송
    recruit_channel = bot.get_channel(RECRUIT_CHANNEL_ID)
    if recruit_channel:
        await recruit_channel.send(
            "🔔 **[세라 라이브 알람 신청]**\n아래 버튼을 눌러 알람 명단에 등록하거나 취소할 수 있습니다!",
            view=AlarmView()
        )

    if not scheduler.running:
        scheduler.add_job(send_alarm, "cron", minute=0, second=0)
        scheduler.start()

# ⏰ 알람 발송 함수
async def send_alarm():
    current_hour = datetime.now().hour
    
    # 짝수 시간이거나 새벽 5시라면 패스
    if current_hour % 2 == 0 or current_hour == 5:
        return

    # 신청 유저가 없다면 패스
    if not alarm_users:
        return
        
    # 2. "시간표" 채널에 실제 알람 멘션 발송
    alarm_channel = bot.get_channel(ALARM_CHANNEL_ID)
    if alarm_channel:
        mentions = " ".join([f"<@{user_id}>" for user_id in alarm_users])
        await alarm_channel.send(f"{mentions} 세라 라이브 들어갈 시간입니다!")
        print(f"[{datetime.now()}] {current_hour}시 알람 발송 완료 (대상: {len(alarm_users)}명)")

keep_alive()
bot.run(TOKEN)
