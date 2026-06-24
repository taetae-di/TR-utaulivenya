import discord
from discord.ext import commands
from discord import app_commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
import os
from flask import Flask
from threading import Thread
from supabase import create_client, Client

# --- [웹 서버 설정: 업타임 및 Koyeb 헬스체크용] ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- [디스코드 봇 및 Supabase 설정] ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True         
intents.reactions = True  

bot = commands.Bot(command_prefix="!", intents=intents)

TOKEN = os.environ.get('DISCORD_TOKEN')
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

# Supabase 클라이언트 초기화
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

# --- [Supabase 전용 데이터 조작 함수 정의] ---

def db_get_alarm_users() -> set:
    try:
        res = supabase.table("alarm_users").select("user_id").execute()
        return {row["user_id"] for row in res.data}
    except Exception as e:
        print(f"DB Error (get_alarm_users): {e}")
        return set()

def db_add_alarm_user(user_id: str):
    try:
        supabase.table("alarm_users").upsert({"user_id": user_id}).execute()
    except Exception as e: print(f"DB Error (add_alarm_user): {e}")

def db_remove_alarm_user(user_id: str):
    try:
        supabase.table("alarm_users").delete().eq("user_id", user_id).execute()
    except Exception as e: print(f"DB Error (remove_alarm_user): {e}")

def db_get_exempt_users() -> dict:
    try:
        res = supabase.table("exempt_users").select("user_id", "exempt_until").execute()
        return {row["user_id"]: row["exempt_until"] for row in res.data}
    except Exception as e:
        print(f"DB Error (get_exempt_users): {e}")
        return {}

def db_set_exempt_user(user_id: str, exempt_until: str):
    try:
        supabase.table("exempt_users").upsert({"user_id": user_id, "exempt_until": exempt_until}).execute()
    except Exception as e: print(f"DB Error (set_exempt_user): {e}")

def db_remove_exempt_user(user_id: str):
    try:
        supabase.table("exempt_users").delete().eq("user_id", user_id).execute()
    except Exception as e: print(f"DB Error (remove_exempt_user): {e}")

def db_get_server_channels() -> dict:
    try:
        res = supabase.table("server_channels").select("*").execute()
        result = {}
        for row in res.data:
            result[row["guild_id"]] = {
                "recruit": row["recruit_channel_id"],
                "alarm": row["alarm_channel_id"]
            }
        return result
    except Exception as e:
        print(f"DB Error (get_server_channels): {e}")
        return {}

def db_set_server_channel(guild_id: str, channel_type: str, channel_id: str):
    try:
        current = db_get_server_channels().get(guild_id, {"recruit": None, "alarm": None})
        if channel_type == "recruit":
            recruit_id, alarm_id = channel_id, current["alarm"]
        else:
            recruit_id, alarm_id = current["recruit"], channel_id
            
        supabase.table("server_channels").upsert({
            "guild_id": guild_id,
            "recruit_channel_id": recruit_id,
            "alarm_channel_id": alarm_id
        }).execute()
    except Exception as e: print(f"DB Error (set_server_channel): {e}")


# 🔘 [버튼 UI: 알람 신청/취소]
class AlarmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="알람 신청하기 ⭕", style=discord.ButtonStyle.green, custom_id="btn_register")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        current_users = db_get_alarm_users()
        
        if user_id not in current_users:
            db_add_alarm_user(user_id)
            await interaction.response.send_message("🔔 세라 라이브 알람 신청이 완료되었습니다! (지정된 시간 정각 멘션)", ephemeral=True)
        else:
            await interaction.response.send_message("ℹ️ 이미 알람 신청이 되어 있습니다.", ephemeral=True)

    @discord.ui.button(label="알람 취소하기 ❌", style=discord.ButtonStyle.red, custom_id="btn_cancel")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        current_users = db_get_alarm_users()
        
        if user_id in current_users:
            db_remove_alarm_user(user_id)
            await interaction.response.send_message("🔕 세라 라이브 알람 신청이 취소되었습니다.", ephemeral=True)
        else:
            await interaction.response.send_message("ℹ️ 현재 신청되어 있지 않습니다.", ephemeral=True)


# 🔘 [버튼 UI: 오늘 알람 제외]
class AlarmExemptView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="오늘 알람 제외하기 ❌", style=discord.ButtonStyle.danger, custom_id="exempt_today_btn")
    async def exempt_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        
        now = datetime.now()
        exempt_until = datetime(now.year, now.month, now.day, 23, 59, 59)
        
        if now > exempt_until:
            exempt_until += timedelta(days=1)
            
        db_set_exempt_user(user_id, exempt_until.strftime("%Y-%m-%d %H:%M:%S"))
        
        await interaction.response.send_message(
            f"🎉 알람 제외 처리가 완료되었습니다!\n"
            f"**오늘 오후 11시 59분**까지 라이브 알람 멘션에서 제외되며, 자정 이후 다음 날 아침부터 다시 정상 작동합니다.",
            ephemeral=True
        )


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    bot.add_view(AlarmView())
    bot.add_view(AlarmExemptView())
    
    try:
        guild_ids = [
            "1487482092983025744",  
            "1409900572168949772"   
        ]
        
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


# ⚙️ [슬래시 명령어 1: 언급용 시간표 채널 설정]
@bot.tree.command(name="언채설정", description="실제 알람 멘션(언급)이 발송될 시간표 채널을 지정합니다.")
@app_commands.checks.has_permissions(manage_channels=True)
async def setup_alarm_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    guild_id = str(interaction.guild_id)
    db_set_server_channel(guild_id, "alarm", str(channel.id))
    await interaction.response.send_message(f"📢 알람 언급 채널이 {channel.mention}으로 설정되었습니다.", ephemeral=True)


# ⚙️ [슬래시 명령어 2: 모집 버튼 채널 설정]
@bot.tree.command(name="알채설정", description="알람 신청 및 취소 버튼 메시지를 띄울 일반 채널을 지정합니다.")
@app_commands.checks.has_permissions(manage_channels=True)
async def setup_recruit_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    guild_id = str(interaction.guild_id)
    db_set_server_channel(guild_id, "recruit", str(channel.id))
    
    await interaction.response.send_message(f"⚙️ 알람 모집 채널이 {channel.mention}으로 설정되었습니다. 버튼을 생성합니다.", ephemeral=True)
    await channel.send(
        "🔔 **[세라 라이브 알람 신청]**\n아래 버튼을 눌러 알람 명단에 등록하거나 취소할 수 있습니다!",
        view=AlarmView()
    )


# ⏰ [알람 발송 함수]
async def send_alarm():
    current_hour = datetime.now().hour

    # 새벽 1시(1), 새벽 3시(3), 오전 7시, 9시, 11시, 오후 1시(13), 3시(15), 5시(17), 7시(19), 9시(21), 11시(23)
    # ❌ 새벽 2시, 새벽 5시 등은 여기에 없으므로 절대 발송되지 않습니다.
    allowed_hours = [1, 3, 7, 9, 11, 13, 15, 17, 19, 21, 23]
    
    if current_hour not in allowed_hours:
        return

    alarm_users = db_get_alarm_users()
    if not alarm_users: 
        return

    now = datetime.now()
    exempt_users = db_get_exempt_users()
    active_mentions = []

    # 1. 면제 시간 체크 후 유효한 유저만 알람 명단에 추가
    for user_id in alarm_users:
        is_exempt = False
        if user_id in exempt_users:
            exempt_time = datetime.strptime(exempt_users[user_id], "%Y-%m-%d %H:%M:%S")
            if now < exempt_time:
                is_exempt = True

        if not is_exempt:
            active_mentions.append(user_id)

    # 2. 밤 11시 59분이 지나 유효시간이 끝난 면제 유저는 DB에서 삭제 처리 (자동 초기화)
    for uid, x_time_str in exempt_users.items():
        if now >= datetime.strptime(x_time_str, "%Y-%m-%d %H:%M:%S"):
            db_remove_exempt_user(uid)

    if not active_mentions: 
        return

    server_channels = db_get_server_channels()

    # 3. 각 서버별 순회하며 멘션 발송
    for guild_id, channels in server_channels.items():
        alarm_channel_id = channels.get("alarm")
        if not alarm_channel_id:
            continue

        guild = bot.get_guild(int(guild_id))
        if not guild:
            continue

        alarm_channel = bot.get_channel(int(alarm_channel_id))
        if not alarm_channel:
            continue

        # 해당 서버에 실존하는 멤버인지 한 번 더 교차 검증
        real_server_members = []
        for uid in active_mentions:
            member = guild.get_member(int(uid))
            if member: 
                real_server_members.append(uid)

        if not real_server_members:
            continue

        mentions = " ".join([f"<@{uid}>" for uid in real_server_members])
        
        view = AlarmExemptView()
        await alarm_channel.send(
            f"{mentions} 세라 라이브 들어갈 시간입니다!",
            view=view
        )
        print(f"[{datetime.now()}] 서버({guild_id})의 {current_hour}시 버튼식 알람 발송 완료 (실제 멘션: {len(real_server_members)}명)")

keep_alive()
bot.run(TOKEN)
