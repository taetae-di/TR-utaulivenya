import discord
from discord.ext import commands
from discord import app_commands
from apscheduler.schedulers.asyncio import AsyncioScheduler
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
intents.reactions = True  

bot = commands.Bot(command_prefix="!", intents=intents)

TOKEN = os.environ.get('DISCORD_TOKEN')

# 데이터 파일 정의
DATA_FILE = "alarm_users.json"
EXEMPT_FILE = "exempt_users.json"
CHANNELS_FILE = "server_channels.json" # 서버별 채널 설정을 저장할 파일

alarm_users = set()
exempt_users = {}  
user_reaction_counts = {}  
server_channels = {} # { "서버ID": {"recruit": "채널ID", "alarm": "채널ID"} }

scheduler = AsyncioScheduler(timezone="Asia/Seoul")

def load_data():
    global alarm_users, exempt_users, server_channels
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                alarm_users = set(json.load(f))
        except Exception as e: print(f"Load Error (Alarm): {e}")
            
    if os.path.exists(EXEMPT_FILE):
        try:
            with open(EXEMPT_FILE, "r", encoding="utf-8") as f:
                exempt_users = json.load(f)
        except Exception as e: print(f"Load Error (Exempt): {e}")

    if os.path.exists(CHANNELS_FILE):
        try:
            with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
                server_channels = json.load(f)
                print(f"[Data Loaded] {len(server_channels)} servers configured.")
        except Exception as e: print(f"Load Error (Channels): {e}")

def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(list(alarm_users), f, ensure_ascii=False, indent=4)
    except Exception as e: print(f"Save Error (Alarm): {e}")

def save_exempt_data():
    try:
        with open(EXEMPT_FILE, "w", encoding="utf-8") as f:
            json.dump(exempt_users, f, ensure_ascii=False, indent=4)
    except Exception as e: print(f"Save Error (Exempt): {e}")

def save_channels_data():
    try:
        with open(CHANNELS_FILE, "w", encoding="utf-8") as f:
            json.dump(server_channels, f, ensure_ascii=False, indent=4)
    except Exception as e: print(f"Save Error (Channels): {e}")


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
    bot.add_view(AlarmExemptView())
    
    try:
        # 1. 여기에 동기화하고 싶은 서버 ID들을 쉼표(,)로 구분해서 모두 적어줍니다.
        guild_ids = [
            "1487482092983025744",  # 기존 첫 번째 서버 ID
            "1409900572168949772"   # 새로 추가할 두 번째 서버 ID
        ]
        
        # 2. 적어준 서버 목록을 돌면서 명령어를 하나씩 주입합니다.
        for guild_id in guild_ids:
            guild_obj = discord.Object(id=guild_id)
            bot.tree.copy_global_to(guild=guild_obj)
            synced = await bot.tree.sync(guild=guild_obj)
            print(f"[서버 {guild_id}]에 즉시 동기화 완료: {len(synced)}개 명령어")
            
    except Exception as e:
        print(f"Command sync error: {e}")

    if not scheduler.running:
        scheduler.add_job(send_alarm, "cron", minute=0, second=0)
        scheduler.start()

# ⚙️ [슬래시 명령어 1: 언급용 채널 설정 (알람 멘션이 갈 곳)]
@bot.tree.command(name="언채설정", description="실제 알람 멘션(언급)이 발송될 시간표 채널을 지정합니다.")
@app_commands.checks.has_permissions(manage_channels=True)
async def setup_alarm_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    guild_id = str(interaction.guild_id)
    if guild_id not in server_channels:
        server_channels[guild_id] = {"recruit": None, "alarm": None}
        
    server_channels[guild_id]["alarm"] = str(channel.id)
    save_channels_data()
    await interaction.response.send_message(f"📢 알람 언급 채널이 {channel.mention}으로 설정되었습니다.", ephemeral=True)

# ⚙️ [슬래시 명령어 2: 알람 신청/취소용 채널 설정 (모집 버튼 올라갈 곳)]
@bot.tree.command(name="알채설정", description="알람 신청 및 취소 버튼 메시지를 띄울 일반 채널을 지정합니다.")
@app_commands.checks.has_permissions(manage_channels=True)
async def setup_recruit_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    guild_id = str(interaction.guild_id)
    if guild_id not in server_channels:
        server_channels[guild_id] = {"recruit": None, "alarm": None}
        
    server_channels[guild_id]["recruit"] = str(channel.id)
    save_channels_data()
    
    await interaction.response.send_message(f"⚙️ 알람 모집 채널이 {channel.mention}으로 설정되었습니다. 버튼을 생성합니다.", ephemeral=True)
    
    # 지정된 채널에 버튼 메시지 즉시 발송
    await channel.send(
        "🔔 **[세라 라이브 알람 신청]**\n아래 버튼을 눌러 알람 명단에 등록하거나 취소할 수 있습니다!",
        view=AlarmView()
    )

# --------------------------------------------------------
# 🔘 [변경] 알람 제외 버튼 클래스 (완벽한 시크릿 메시지)
# --------------------------------------------------------
class AlarmExemptView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # 24시간 버튼 구조 유지

    @discord.ui.button(label="오늘 알람 제외하기 ❌", style=discord.ButtonStyle.danger, custom_id="exempt_today_btn")
    async def exempt_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        
        # 🎯 당일 오후 11시 59분 59초 기준 시간 계산
        now = datetime.now()
        exempt_until = datetime(now.year, now.month, now.day, 23, 59, 59)
        
        # 이미 당일 밤 11시 59분이 지난 새벽 시간대 예외 처리
        if now > exempt_until:
            exempt_until += timedelta(days=1)
            
        # 면제자 명단에 등록 후 물리 파일 저장
        exempt_users[user_id] = exempt_until.strftime("%Y-%m-%d %H:%M:%S")
        save_exempt_data()
        
        # 🤫 ephemeral=True 옵션으로 '누른 사람에게만 보이는' 완벽한 시크릿 메시지 발송
        await interaction.response.send_message(
            f"🎉 알람 제외 처리가 완료되었습니다!\n"
            f"**오늘 오후 11시 59분**까지 라이브 알람 멘션에서 제외되며, 자정 이후 다음 날 아침부터 다시 정상 작동합니다.",
            ephemeral=True
        )

# --------------------------------------------------------
# ⏰ 알람 발송 함수 (지정된 홀수 시간대 발송 + 서버에 존재하는 멤버만 필터링 + 버튼 장착)
# --------------------------------------------------------
async def send_alarm():
    current_hour = datetime.now().hour

    # 🎯 [화이트리스트 시간 설정] 딱 이 홀수 시간대에만 발송 허용
    allowed_hours = [7, 9, 11, 13, 15, 17, 19, 21, 23, 1, 3]
    if current_hour not in allowed_hours:
        return

    # 알람 신청 유저가 없으면 패스
    if not alarm_users: 
        return

    now = datetime.now()
    active_mentions = []

    # 1. 면제자 유저 필터링 로직 (시간 기준)
    for user_id in alarm_users:
        is_exempt = False
        if user_id in exempt_users:
            exempt_time = datetime.strptime(exempt_users[user_id], "%Y-%m-%d %H:%M:%S")
            if now < exempt_time:
                is_exempt = True

        if not is_exempt:
            active_mentions.append(user_id)

    # 면제 시간이 지난 유저들 명단 사후 정리 (오후 11시 59분이 지나 자정이 되면 자동 삭제)
    for uid in list(exempt_users.keys()):
        if now >= datetime.strptime(exempt_users[uid], "%Y-%m-%d %H:%M:%S"):
            del exempt_users[uid]
    save_exempt_data()

    if not active_mentions: 
        return

    # 2. 설정된 모든 서버의 알람 채널을 돌며 멘션 발송
    for guild_id, channels in server_channels.items():
        alarm_channel_id = channels.get("alarm")
        if not alarm_channel_id:
            continue

        # 디스코드에서 해당 서버(Guild) 객체 가져오기
        guild = bot.get_guild(int(guild_id))
        if not guild:
            continue

        alarm_channel = bot.get_channel(int(alarm_channel_id))
        if not alarm_channel:
            continue

        # 현재 서버의 멤버 목록을 확인하여, 실제로 존재하는 멤버만 골라내기
        real_server_members = []
        for uid in active_mentions:
            member = guild.get_member(int(uid))
            if member: # 서버에 실제로 존재하는 유저라면 목록에 추가
                real_server_members.append(uid)

        # 해당 서버에 멘션할 유저가 한 명도 없다면 이 서버는 발송을 건너뜁니다.
        if not real_server_members:
            continue

        # 실제 존재하는 유저들만 멘션 문자열로 조합
        mentions = " ".join([f"<@{uid}>" for uid in real_server_members])
        
        # 🌟 알람 메시지를 보낼 때 하단에 [오늘 알람 제외하기 ❌] 버튼을 장착해서 보냅니다.
        view = AlarmExemptView()
        await alarm_channel.send(
            f"{mentions} 세라 라이브 들어갈 시간입니다!",
            view=view
        )
        print(f"[{datetime.now()}] 서버({guild_id})의 {current_hour}시 버튼식 알람 발송 완료 (실제 멘션: {len(real_server_members)}명)")

keep_alive()
bot.run(TOKEN)
