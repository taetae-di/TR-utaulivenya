import discord
import pytz
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
    app.run(host='0.0.0.0', port=8000)

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
        scheduler.add_job(send_alarm, "cron", hour="*", minute=0, second=0, timezone="Asia/Seoul")
        scheduler.add_job(send_alarm, "cron", hour=0, minute=10, second=0, timezone="Asia/Seoul")
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
    # 1. 현재 시간을 서울 시간대로 명확히 가져오기
    seoul_zone = pytz.timezone("Asia/Seoul")
    current_time_seoul = datetime.now(seoul_zone)
    current_hour = current_time_seoul.hour
    current_minute = current_time_seoul.minute

    # [필터 1] 새벽 4, 5, 6시는 무조건 알람 제외 (즉시 종료)
    if current_hour in [4, 5, 6]:
        return

    # [필터 2] 00시 정각(0분)에 스케줄러가 깨운 것은 패스
    if current_hour == 0 and current_minute == 0:
        return

    # ✨ [수정] now 시계도 무조건 한국 시간(current_time_seoul) 기준으로 바인딩!
    # 기존의 'now = datetime.now()' 구문을 지우고 아래처럼 서울 시간 시계로 대체합니다.
    now = current_time_seoul

    alarm_users = db_get_alarm_users()
    if not alarm_users:
        return

    exempt_users = db_get_exempt_users()
    active_mentions = []

    # 1. 면제 시간 체크 후 유효한 유저만 알람 명단에 추가
    for user_id in alarm_users:
        is_exempt = False
        if user_id in exempt_users:
            # 면제 시간 문자열을 파이썬 시간 객체로 변환
            exempt_time_naive = datetime.strptime(exempt_users[user_id], "%Y-%m-%d %H:%M:%S")
            # ⚠️ 중요: 면제 시간 시계도 한국 시간대 정보(tzinfo)를 주입하여 비교 대상과 격을 맞춥니다.
            exempt_time = seoul_zone.localize(exempt_time_naive)
            
            if now < exempt_time:
                is_exempt = True

        if not is_exempt:
            active_mentions.append(user_id)

    if not active_mentions: 
        return

    server_channels = db_get_server_channels()
    sent_user_ids = set()

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

        # 해당 서버에 실존하는 멤버인지 한 번 더 교차 검증 및 중복 필터링
        real_server_members = []
        for uid in active_mentions:
            if uid in sent_user_ids:
                continue

            member = guild.get_member(int(uid))
            if member: 
                real_server_members.append(uid)
                sent_user_ids.add(uid)

        if not real_server_members:
            continue

        mentions = " ".join([f"<@{uid}>" for uid in real_server_members])
        
        view = AlarmExemptView()
        await alarm_channel.send(
            f"{mentions} 세라 라이브 들어갈 시간입니다!",
            view=view
        )

    # ✨ [조용히 청소] 밤 00시 10분 초기화 코드는 알람 전송 루프가 다 끝난 맨 밑바닥으로 이동!
    if current_hour == 0 and current_minute == 10:
        try:
            supabase.table("exempt_users").delete().neq("user_id", "0").execute()
        except:
            pass

keep_alive()
bot.run(TOKEN)
