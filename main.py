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

def db_get_alarm_users() -> list:
    """[{ 'user_id': '...', 'guild_id': '...' }, ...] 형태의 리스트 반환"""
    try:
        res = supabase.table("alarm_users").select("user_id", "guild_id").execute()
        return res.data if res.data else []
    except Exception as e:
        print(f"DB Error (get_alarm_users): {e}")
        return []

def db_add_alarm_user(user_id: str, guild_id: str):
    """신청한 유저 ID와 서버 ID를 함께 저장"""
    try:
        supabase.table("alarm_users").upsert({"user_id": user_id, "guild_id": guild_id}).execute()
    except Exception as e: print(f"DB Error (add_alarm_user): {e}")

def db_remove_alarm_user(user_id: str, guild_id: str):
    """특정 서버에서 신청했던 알람만 선택 삭제"""
    try:
        supabase.table("alarm_users").delete().eq("user_id", user_id).eq("guild_id", guild_id).execute()
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
        guild_id = str(interaction.guild_id)
        
        current_alarm_list = db_get_alarm_users()
        is_already_registered = any(row["user_id"] == user_id and row["guild_id"] == guild_id for row in current_alarm_list)
        
        if not is_already_registered:
            db_add_alarm_user(user_id, guild_id)
            await interaction.response.send_message("🔔 이 서버에서의 옥션+라이브 알람 신청이 완료되었습니다!", ephemeral=True)
        else:
            await interaction.response.send_message("ℹ️ 이 서버에 이미 알람 신청이 되어 있습니다.", ephemeral=True)

    @discord.ui.button(label="알람 취소하기 ❌", style=discord.ButtonStyle.red, custom_id="btn_cancel")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        guild_id = str(interaction.guild_id)
        
        current_alarm_list = db_get_alarm_users()
        is_registered = any(row["user_id"] == user_id and row["guild_id"] == guild_id for row in current_alarm_list)
        
        if is_registered:
            db_remove_alarm_user(user_id, guild_id)
            await interaction.response.send_message("🔕 이 서버에서의 옥션+라이브 알람 신청이 취소되었습니다.", ephemeral=True)
        else:
            await interaction.response.send_message("ℹ️ 이 서버에는 알람 신청이 되어있지 않습니다.", ephemeral=True)


# 🔘 [버튼 UI: 오늘 알람 제외]
class AlarmExemptView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="오늘 알람 제외하기 ❌", style=discord.ButtonStyle.danger, custom_id="exempt_today_btn")
    async def exempt_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        user_id = str(interaction.user.id)
        seoul_zone = pytz.timezone("Asia/Seoul")
        now_seoul = datetime.now(seoul_zone)
        
        exempt_until = datetime(now_seoul.year, now_seoul.month, now_seoul.day, 23, 59, 59)
        
        now_naive = now_seoul.replace(tzinfo=None)
        if now_naive > exempt_until:
            exempt_until += timedelta(days=1)
            
        db_set_exempt_user(user_id, exempt_until.strftime("%Y-%m-%d %H:%M:%S"))
        
        await interaction.followup.send(
            f"🎉 알람 제외 처리가 완료되었습니다!\n"
            f"**오늘 오후 11시 59분**까지 옥션 알람 멘션에서 제외되며, 자정부터 다시 정상 작동합니다.",
            ephemeral=True
        )


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    bot.add_view(AlarmView())
    bot.add_view(AlarmExemptView())
    
    # ⚙️ [수정됨] 슬래시 명령어 동기화 방식 올바르게 수정
    try:
        guild_ids = [
            1487482092983025744,  
            1409900572168949772   
        ]
        
        for guild_id in guild_ids:
            guild_obj = discord.Object(id=guild_id)
            # 서버 단독 동기화를 보장하기 위해 copy_global_to 대신 바로 sync 실행
            bot.tree.copy_global_to(guild=guild_obj)
            synced = await bot.tree.sync(guild=guild_obj)
            print(f"[서버 {guild_id}]에 즉시 동기화 완료: {len(synced)}개 명령어")
            
    except Exception as e:
        print(f"Command sync error: {e}")

    if not scheduler.running:
        scheduler.add_job(send_alarm, "cron", hour="*", minute=27, second=0, timezone="Asia/Seoul")
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
        "🔔 **[옥션 알람 신청]**\n아래 버튼을 눌러 알람 명단에 등록하거나 취소할 수 있습니다!",
        view=AlarmView()
    )


# ⏰ [알람 발송 함수]
async def send_alarm():
    seoul_zone = pytz.timezone("Asia/Seoul")
    current_time_seoul = datetime.now(seoul_zone)
    current_hour = current_time_seoul.hour
    current_minute = current_time_seoul.minute

    if current_hour in [4, 5, 6]:
        return

    if current_hour == 0 and current_minute == 10:
        try:
            supabase.table("exempt_users").delete().neq("user_id", "0").execute()
        except:
            pass

    if current_minute == 10:
        return 

    if current_minute != 27:
        return 

    now = current_time_seoul

    # DB에서 목록 가져오기
    alarm_users_data = db_get_alarm_users() # [{'user_id': '...', 'guild_id': '...'}, ...]
    if not alarm_users_data:
        return

    exempt_users = db_get_exempt_users()
    server_channels = db_get_server_channels()

    # 서버별 유저 분류
    guild_to_users = {}

    for row in alarm_users_data:
        uid = str(row.get("user_id"))
        gid = str(row.get("guild_id"))

        if not uid or not gid:
            continue

        # 면제 상태 체크
        is_exempt = False
        int_uid = int(uid) if uid.isdigit() else None
        target_uid = uid if uid in exempt_users else (int_uid if int_uid in exempt_users else None)

        if target_uid is not None:
            exempt_time_str = str(exempt_users[target_uid])
            current_time_str = now.strftime("%Y-%m-%d %H:%M:%S")
            today_date_str = now.strftime("%Y-%m-%d")
            if current_time_str < exempt_time_str or today_date_str in exempt_time_str:
                is_exempt = True

        # 면제자가 아니면 서버별 대상 추가
        if not is_exempt:
            if gid not in guild_to_users:
                guild_to_users[gid] = []
            guild_to_users[gid].append(uid)

    # 각 서버별 알람 발송
    for guild_id, user_ids in guild_to_users.items():
        if not user_ids:
            continue

        channels = server_channels.get(guild_id)
        if not channels:
            continue

        alarm_channel_id = channels.get("alarm")
        if not alarm_channel_id:
            continue

        guild = bot.get_guild(int(guild_id))
        if not guild:
            continue

        alarm_channel = bot.get_channel(int(alarm_channel_id))
        if not alarm_channel:
            continue

        mentions = " ".join([f"<@{uid}>" for uid in user_ids])
        view = AlarmExemptView()
        
        await alarm_channel.send(
            f"{mentions} 1분 후 옥션, 라이브 들어갈 시간입니다!",
            view=view
        )

keep_alive()
bot.run(TOKEN)
