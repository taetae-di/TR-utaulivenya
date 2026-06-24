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

# 📥 [이모지 반응 감지 이벤트]
@bot.event
async def on_reaction_add(reaction: discord.Reaction, user: discord.User):
    if user.bot: 
        return
        
    # 🌟 [핵심 수정] 이모지가 달린 메시지의 작성자가 '이 봇(자신)'일 때만 카운트합니다.
    if reaction.message.author.id != bot.user.id:
        return

    user_id = str(user.id)
    
    # 이모지 누적 카운트 증가
    user_reaction_counts[user_id] = user_reaction_counts.get(user_id, 0) + 1
    
    # 2번 참여 시 면제 처리
    if user_reaction_counts[user_id] == 2:
        now = datetime.now()
        tomorrow = now + timedelta(days=1)
        exempt_until = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 6, 59, 59)
        exempt_users[user_id] = exempt_until.strftime("%Y-%m-%d %H:%M:%S")
        save_exempt_data()
        
        try:
            await user.send(f"🎉 봇 알람 메시지에 이모지로 2번 참여하셨습니다! 내일 오전 6시 59분까지 라이브 알람 멘션에서 제외됩니다.")
        except discord.Forbidden: 
            pass

# ⏰ 알람 발송 함수 (오전 7시 ~ 익일 오전 3시 사이의 홀수 시간대만 발송 / 오전 5시 제외)
async def send_alarm():
    current_hour = datetime.now().hour
    
    # 1. [짝수 필터] 짝수 시간대는 아예 들어오지 못하도록 완전히 차단
    if current_hour % 2 == 0:
        return
        
    # 2. [시간대 및 예외 필터] 아침 4시, 5시, 6시는 알람을 보내지 않고 건너뜁니다.
    # (오전 7시부터 시작해서 익일 오전 3시까지 유효하며, 오전 5시는 강제 제외되므로)
    if current_hour in [4, 5, 6]:
        return
        
    # 3. 알람 신청 유저가 없으면 패스
    if not alarm_users: 
        return

    now = datetime.now()
    active_mentions = []

    # 4. 면제자 유저 필터링 로직
    for user_id in alarm_users:
        is_exempt = False
        if user_id in exempt_users:
            exempt_time = datetime.strptime(exempt_users[user_id], "%Y-%m-%d %H:%M:%S")
            if now < exempt_time:
                is_exempt = True
                
        if not is_exempt:
            active_mentions.append(user_id)

    # 5. 면제 시간이 지난 유저들 명단 사후 정리
    for uid in list(exempt_users.keys()):
        if now >= datetime.strptime(exempt_users[uid], "%Y-%m-%d %H:%M:%S"):
            del exempt_users[uid]
    save_exempt_data()

    if not active_mentions: 
        return

    # 6. 설정된 모든 서버의 알람 채널을 돌며 멘션 발송
    for guild_id, channels in server_channels.items():
        alarm_channel_id = channels.get("alarm")
        if alarm_channel_id:
            alarm_channel = bot.get_channel(int(alarm_channel_id))
            if alarm_channel:
                mentions = " ".join([f"<@{uid}>" for uid in active_mentions])
                await alarm_channel.send(f"{mentions} 세라 라이브 들어갈 시간입니다!")
                print(f"[{datetime.now()}] 서버({guild_id})의 {current_hour}시 알람 발송 완료")

keep_alive()
bot.run(TOKEN)
