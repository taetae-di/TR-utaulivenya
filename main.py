import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
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
intents.reactions = True  # 이모지 체크를 위해 reaction 인텐트 활성화

bot = commands.Bot(command_prefix="!", intents=intents)

TOKEN = os.environ.get('DISCORD_TOKEN')

# 🛠️ [복수 채널 ID 설정] 본인 서버의 채널 ID들로 수정해 주세요!
RECRUIT_CHANNEL_ID = 1487560087890297002, 1409900573331030058  # "링크공유" 채널 ID (모집 버튼이 올라갈 곳)
ALARM_CHANNEL_ID = 1519281328766455959, 1489102073185308752    # "알림" 채널 ID (실제 알람 멘션이 갈 곳)

DATA_FILE = "alarm_users.json"
EXEMPT_FILE = "exempt_users.json" # 면제자 명단 저장 파일

alarm_users = set()
exempt_users = {}  # { "유저ID": "면제만료시간(YYYY-MM-DD THH:MM:SS)" }
user_reaction_counts = {}  # 임시 당일 이모지 카운트 { "유저ID": 카운트숫자 }

scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

def load_data():
    global alarm_users, exempt_users
    # 1. 알람 신청 유저 로드
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                alarm_users = set(json.load(f))
                print(f"[Data Loaded] {len(alarm_users)} alarm users.")
        except Exception as e:
            print(f"Load Error (Alarm): {e}")
            
    # 2. 면제 유저 로드
    if os.path.exists(EXEMPT_FILE):
        try:
            with open(EXEMPT_FILE, "r", encoding="utf-8") as f:
                exempt_users = json.load(f)
                print(f"[Data Loaded] {len(exempt_users)} exempt users.")
        except Exception as e:
            print(f"Load Error (Exempt): {e}")

def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(list(alarm_users), f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Save Error (Alarm): {e}")

def save_exempt_data():
    try:
        with open(EXEMPT_FILE, "w", encoding="utf-8") as f:
            json.dump(exempt_users, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Save Error (Exempt): {e}")

# 🔘 [버튼 UI 정의]
class AlarmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="알람 신청하기 ⭕", style=discord.ButtonStyle.green, custom_id="btn_register")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        if user_id not in alarm_users:
            alarm_users.add(user_id)
            save_data()
            await interaction.response.send_message("🔔 세라 라이브 알람 신청이 완료되었습니다! (홀수 시각 정각 멘션)", ephemeral=True)
        else:
            await interaction.response.send_message("ℹ️ 이미 알람 신청이 되어 있습니다.", ephemeral=True)

    @discord.ui.button(label="알람 취소하기 ❌", style=discord.ButtonStyle.red, custom_id="btn_cancel")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
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
    
    for channel_id in RECRUIT_CHANNEL_IDS:
        recruit_channel = bot.get_channel(channel_id)
        if recruit_channel:
            await recruit_channel.send(
                "🔔 **[세라 라이브 알람 신청]**\n아래 버튼을 눌러 알람 명단에 등록하거나 취소할 수 있습니다!",
                view=AlarmView()
            )

    if not scheduler.running:
        scheduler.add_job(send_alarm, "cron", minute=0, second=0)
        scheduler.start()

# 📥 [이모지 반응 감지 이벤트]
@bot.event
async def on_reaction_add(reaction: discord.Reaction, user: discord.User):
    if user.bot:
        return

    user_id = str(user.id)
    
    # 이모지 카운트 증가
    user_reaction_counts[user_id] = user_reaction_counts.get(user_id, 0) + 1
    
    # 2번 참여(이모지 누르기)했을 때 조건 발동
    if user_reaction_counts[user_id] == 2:
        now = datetime.now()
        # 익일(내일) 날짜 구하기
        tomorrow = now + timedelta(days=1)
        # 익일 오전 6시 59분 59초 설정
        exempt_until = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 6, 59, 59)
        
        # 면제 명단에 등록 (시간 포맷 저장)
        exempt_users[user_id] = exempt_until.strftime("%Y-%m-%d %H:%M:%S")
        save_exempt_data()
        
        # 유저에게 알림 (DM 혹은 해당 채널에 안내 메시지 - 선택 가능)
        try:
            await user.send(f"🎉 이모지에 2번 참여하셨습니다! 내일 오전 6시 59분까지 라이브 알람 멘션에서 제외됩니다.")
        except discord.Forbidden:
            pass # 유저가 DM을 막아둔 경우 패스

# ⏰ 알람 발송 함수
async def send_alarm():
    current_hour = datetime.now().hour
    
    if current_hour % 2 == 0 or current_hour == 5:
        return
    if not alarm_users:
        return

    now = datetime.now()
    active_mentions = []

    # 현재 알람 대상자 중 면제 대상을 필터링합니다.
    for user_id in alarm_users:
        is_exempt = False
        if user_id in exempt_users:
            # 면제 만료 시간 파싱
            exempt_time = datetime.strptime(exempt_users[user_id], "%Y-%m-%d %H:%M:%S")
            if now < exempt_time:
                is_exempt = True # 아직 면제 시간이 지나지 않음
            else:
                # 시간이 지났으면 면제 명단에서 삭제
                del exempt_users[user_id]
                save_exempt_data()
        
        if not is_exempt:
            active_mentions.append(user_id)

    if not active_mentions:
        return

    # 등록된 모든 알람 채널에 멘션 발송
    for channel_id in ALARM_CHANNEL_IDS:
        alarm_channel = bot.get_channel(channel_id)
        if alarm_channel:
            mentions = " ".join([f"<@{uid}>" for uid in active_mentions])
            await alarm_channel.send(f"{mentions} 세라 라이브 들어갈 시간입니다!")
            print(f"[{datetime.now()}] {current_hour}시 알람 발송 완료")

keep_alive()
bot.run(TOKEN)
