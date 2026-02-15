"""
LFBBotTicketTool - Umfassendes Ticket-System für Red-DiscordBot
Version: 1.0.0 - 100% Deutsch
"""

import asyncio
import datetime
import logging
import re
from typing import Optional, Dict, List, Union

import discord
from discord import (
    ui,
    ButtonStyle,
    TextStyle,
    Interaction,
    Member,
    User,
    TextChannel,
    CategoryChannel,
    Role,
    Embed,
    Color,
)
from redbot.core import Config, commands, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import humanize_list

log = logging.getLogger("red.lfbbottickettool")

DEFAULT_GUILD = {
    "ticket_category": None,
    "archive_category": None,
    "support_roles": [],
    "admin_roles": [],
    "ticket_limit": 3,
    "ticket_counter": 0,
    "tickets": {},
    "panels": {},
    "categories": {
        "Allgemein": {"emoji": "🎫", "description": "Allgemeine Anfragen", "color": 0x3498db, "enabled": True},
        "Support": {"emoji": "🛠️", "description": "Technischer Support", "color": 0xe74c3c, "enabled": True},
        "Report": {"emoji": "⚠️", "description": "Spieler melden", "color": 0xf39c12, "enabled": True},
        "Bewerbung": {"emoji": "📝", "description": "Bewerbungen", "color": 0x9b59b6, "enabled": True},
        "Partner": {"emoji": "🤝", "description": "Partner-Anfragen", "color": 0x1abc9c, "enabled": True},
    },
    "default_category": "Allgemein",
    "welcome_message": "Willkommen {user}!\n\nEin Team-Mitglied wird sich in Kürze um dich kümmern.\nBitte beschreibe dein Anliegen so detailliert wie möglich.",
    "log_channel": None,
    "blacklist": [],
    "feedback_enabled": True,
    "auto_close_hours": 72,
    "auto_close_warning_hours": 24,
    "claim_enabled": True,
    "ticket_name_format": "ticket-{counter}",
    "dm_notifications": True,
    "embed_color": 0x3498db,
    "button_style": "primary",
    "show_user_info": True,
    "ping_on_create": True,
    "ping_role": None,
}


class TicketButton(ui.Button):
    def __init__(self, cog, category: str, emoji: str, label: str, style: ButtonStyle):
        super().__init__(style=style, emoji=emoji, label=label, custom_id=f"lfb_ticket_{category}")
        self.cog = cog
        self.category = category

    async def callback(self, interaction: Interaction):
        await self.cog.create_ticket_callback(interaction, self.category)


class TicketSelectMenu(ui.Select):
    def __init__(self, cog, categories: Dict):
        self.cog = cog
        options = []
        for name, data in categories.items():
            if data.get("enabled", True):
                options.append(
                    discord.SelectOption(
                        label=name,
                        description=data.get("description", "Keine Beschreibung")[:100],
                        emoji=data.get("emoji", "🎫"),
                        value=name,
                    )
                )
        super().__init__(
            placeholder="Wähle eine Ticket-Kategorie...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="lfb_ticket_select",
        )

    async def callback(self, interaction: Interaction):
        await self.cog.create_ticket_callback(interaction, self.values[0])


class TicketPanelView(ui.View):
    def __init__(self, cog, categories: Dict, button_style: str = "primary"):
        super().__init__(timeout=None)
        style_map = {"primary": ButtonStyle.primary, "secondary": ButtonStyle.secondary, "success": ButtonStyle.success, "danger": ButtonStyle.danger}
        style = style_map.get(button_style, ButtonStyle.primary)
        for name, data in categories.items():
            if data.get("enabled", True):
                self.add_item(TicketButton(cog=cog, category=name, emoji=data.get("emoji", "🎫"), label=name, style=style))


class TicketPanelDropdownView(ui.View):
    def __init__(self, cog, categories: Dict):
        super().__init__(timeout=None)
        self.add_item(TicketSelectMenu(cog, categories))


class CloseReasonModal(ui.Modal):
    def __init__(self, cog, channel_id: int):
        self.cog = cog
        self.channel_id = channel_id
        super().__init__(title="Ticket schließen", timeout=300)
        self.reason = ui.TextInput(label="Grund für Schließung", style=TextStyle.paragraph, placeholder="Bitte gib einen Grund an...", required=True, max_length=500)
        self.add_item(self.reason)

    async def on_submit(self, interaction: Interaction):
        await self.cog.close_ticket_interaction(interaction, self.channel_id, self.reason.value)


class FeedbackModal(ui.Modal):
    def __init__(self, cog, ticket_id: str, user_id: int):
        self.cog = cog
        self.ticket_id = ticket_id
        self.user_id = user_id
        super().__init__(title="Ticket-Feedback", timeout=300)
        self.rating = ui.TextInput(label="Bewertung (1-5)", style=TextStyle.short, placeholder="1, 2, 3, 4 oder 5", required=True, max_length=1)
        self.add_item(self.rating)
        self.comment = ui.TextInput(label="Kommentar (optional)", style=TextStyle.paragraph, placeholder="Deine Erfahrung...", required=False, max_length=1000)
        self.add_item(self.comment)

    async def on_submit(self, interaction: Interaction):
        try:
            rating = int(self.rating.value)
            if rating < 1 or rating > 5:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Bitte gib eine Zahl zwischen 1 und 5 an.", ephemeral=True)
            return
        await self.cog.save_feedback(interaction, self.ticket_id, self.user_id, rating, self.comment.value)


class TicketControlView(ui.View):
    def __init__(self, cog, channel_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.channel_id = channel_id

    @ui.button(label="Schließen", emoji="🔒", style=ButtonStyle.danger, custom_id="lfb_close")
    async def close_btn(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_modal(CloseReasonModal(self.cog, self.channel_id))

    @ui.button(label="Claim", emoji="✋", style=ButtonStyle.primary, custom_id="lfb_claim")
    async def claim_btn(self, interaction: Interaction, button: ui.Button):
        await self.cog.claim_ticket(interaction, self.channel_id)

    @ui.button(label="Transkript", emoji="📝", style=ButtonStyle.secondary, custom_id="lfb_transcript")
    async def transcript_btn(self, interaction: Interaction, button: ui.Button):
        await self.cog.generate_transcript_cmd(interaction, self.channel_id)


class FeedbackView(ui.View):
    def __init__(self, cog, ticket_id: str, user_id: int):
        super().__init__(timeout=3600)
        self.cog = cog
        self.ticket_id = ticket_id
        self.user_id = user_id

    @ui.button(label="Feedback geben", emoji="⭐", style=ButtonStyle.primary)
    async def feedback_btn(self, interaction: Interaction, button: ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Nur der Ticket-Ersteller kann Feedback geben.", ephemeral=True)
            return
        await interaction.response.send_modal(FeedbackModal(self.cog, self.ticket_id, self.user_id))

    @ui.button(label="Später", style=ButtonStyle.secondary)
    async def later_btn(self, interaction: Interaction, button: ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Nicht für dich.", ephemeral=True)
            return
        await interaction.response.send_message("Okay, du kannst später Feedback geben.", ephemeral=True)
        self.stop()


class LFBBotTicketTool(commands.Cog):
    """🎫 Umfassendes Ticket-System - 100% Deutsch"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210, force_registration=True)
        self.config.register_guild(**DEFAULT_GUILD)
        self._task = None

    async def cog_load(self):
        self._task = asyncio.create_task(self.auto_close_loop())
        await self.setup_views()
        log.info("LFBBotTicketTool geladen")

    async def cog_unload(self):
        if self._task:
            self._task.cancel()
        log.info("LFBBotTicketTool entladen")

    async def setup_views(self):
        await self.bot.wait_until_red_ready()
        for guild in self.bot.guilds:
            data = await self.config.guild(guild).all()
            for pid, pdata in data.get("panels", {}).items():
                cats = data.get("categories", {})
                if pdata.get("style") == "dropdown":
                    self.bot.add_view(TicketPanelDropdownView(self, cats))
                else:
                    self.bot.add_view(TicketPanelView(self, cats, data.get("button_style", "primary")))

    async def auto_close_loop(self):
        await self.bot.wait_until_red_ready()
        while True:
            try:
                await self.check_auto_close()
            except Exception as e:
                log.error(f"Auto-Close Fehler: {e}")
            await asyncio.sleep(3600)

    async def check_auto_close(self):
        for guild in self.bot.guilds:
            data = await self.config.guild(guild).all()
            hours = data.get("auto_close_hours", 72)
            if hours == 0:
                continue
            for cid, tdata in data.get("tickets", {}).items():
                if tdata.get("status") != "open":
                    continue
                channel = guild.get_channel(int(cid))
                if not channel:
                    continue
                last_msg = None
                async for msg in channel.history(limit=1):
                    last_msg = msg
                    break
                if not last_msg:
                    continue
                since = (datetime.datetime.now(datetime.timezone.utc) - last_msg.created_at).total_seconds() / 3600
                if since >= hours:
                    await self.do_auto_close(guild, int(cid), tdata)

    async def do_auto_close(self, guild, cid, tdata):
        channel = guild.get_channel(cid)
        if not channel:
            return
        try:
            await channel.send(embed=Embed(title="🔒 Auto-Close", description="Ticket aufgrund von Inaktivität geschlossen.", color=Color.red()))
            await self.close_ticket_internal(guild, cid, "Inaktivität", self.bot.user)
            await asyncio.sleep(10)
            await channel.delete(reason="Auto-Close")
        except:
            pass

    # === TICKET ERSTELLUNG ===
    async def create_ticket_callback(self, interaction: Interaction, category: str):
        guild, user = interaction.guild, interaction.user
        if user.id in await self.config.guild(guild).blacklist():
            await interaction.response.send_message("❌ Du stehst auf der Blacklist.", ephemeral=True)
            return
        limit = await self.config.guild(guild).ticket_limit()
        user_tickets = len([t for t in (await self.config.guild(guild).tickets()).values() if t.get("user_id") == user.id and t.get("status") == "open"])
        if user_tickets >= limit:
            await interaction.response.send_message(f"❌ Du hast bereits {limit} offene Tickets.", ephemeral=True)
            return
        cats = await self.config.guild(guild).categories()
        if category not in cats or not cats[category].get("enabled", True):
            await interaction.response.send_message("❌ Kategorie nicht gefunden.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.create_ticket(guild, user, category, interaction)

    async def create_ticket(self, guild, user, cat_name, interaction=None):
        cfg = self.config.guild(guild)
        data = await cfg.all()
        cat_id = data.get("ticket_category")
        parent = guild.get_channel(cat_id) if cat_id else None
        async with cfg.ticket_counter() as counter:
            counter += 1
            num = counter
        name = data.get("ticket_name_format", "ticket-{counter}").format(counter=num, user=user.name.lower()[:10], category=cat_name.lower()[:10])
        name = re.sub(r"[^a-z0-9\-]", "-", name)[:100]
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True, manage_messages=True),
        }
        for rid in data.get("support_roles", []):
            r = guild.get_role(rid)
            if r:
                overwrites[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True)
        try:
            channel = await guild.create_text_channel(name=name, category=parent, overwrites=overwrites, reason=f"Ticket von {user}")
        except discord.Forbidden:
            if interaction:
                await interaction.followup.send("❌ Keine Berechtigung.", ephemeral=True)
            return None
        except Exception as e:
            if interaction:
                await interaction.followup.send(f"❌ Fehler: {e}", ephemeral=True)
            return None

        cat_data = data.get("categories", {}).get(cat_name, {})
        color = cat_data.get("color", data.get("embed_color", 0x3498db))
        emoji = cat_data.get("emoji", "🎫")
        tdata = {"channel_id": channel.id, "user_id": user.id, "category": cat_name, "created_at": datetime.datetime.now().isoformat(), "status": "open", "claim_by": None}
        async with cfg.tickets() as tickets:
            tickets[str(channel.id)] = tdata

        welcome = data.get("welcome_message", "").format(user=user.mention, ticket_id=num, category=cat_name)
        embed = Embed(title=f"{emoji} Ticket #{num}", description=welcome, color=Color(color), timestamp=datetime.datetime.now(datetime.timezone.utc))
        if data.get("show_user_info", True):
            embed.add_field(name="Ersteller", value=f"{user.mention}\n{user} ({user.id})")
            embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Kategorie", value=cat_name, inline=True)

        content = None
        if data.get("ping_on_create", True):
            prid = data.get("ping_role")
            if prid:
                pr = guild.get_role(prid)
                if pr:
                    content = pr.mention
            else:
                mentions = [guild.get_role(r).mention for r in data.get("support_roles", []) if guild.get_role(r)][:3]
                if mentions:
                    content = " ".join(mentions)

        view = TicketControlView(self, channel.id)
        await channel.send(content=content, embed=embed, view=view)

        if data.get("dm_notifications", True):
            try:
                await user.send(embed=Embed(title="🎫 Ticket erstellt", description=f"Ticket auf **{guild.name}** erstellt.\n**Channel:** {channel.mention}", color=Color.green()))
            except:
                pass

        await self.log_event(guild, "create", {"user": user, "channel": channel, "category": cat_name})
        if interaction:
            await interaction.followup.send(f"✅ Ticket erstellt! {channel.mention}", ephemeral=True)
        return channel

    # === TICKET SCHLIESSUNG ===
    async def close_ticket_interaction(self, interaction, cid, reason):
        guild, user = interaction.guild, interaction.user
        cfg = self.config.guild(guild)
        tickets = await cfg.tickets()
        if str(cid) not in tickets:
            await interaction.response.send_message("❌ Kein Ticket-Channel.", ephemeral=True)
            return
        tdata = tickets[str(cid)]
        if not await self.can_close(user, guild, tdata):
            await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
            return
        await interaction.response.defer()
        await self.close_ticket_internal(guild, cid, reason, user)
        if await cfg.feedback_enabled():
            tuser = guild.get_member(tdata.get("user_id"))
            if tuser:
                try:
                    await tuser.send(embed=Embed(title="⭐ Feedback", description="Bitte bewerte dein Ticket.", color=Color.gold()), view=FeedbackView(self, str(cid), tuser.id))
                except:
                    pass
        await interaction.followup.send("✅ Ticket geschlossen. Channel wird in 10s gelöscht.", ephemeral=True)
        await asyncio.sleep(10)
        ch = guild.get_channel(cid)
        if ch:
            try:
                await ch.delete(reason=f"Geschlossen: {reason}")
            except:
                pass

    async def close_ticket_internal(self, guild, cid, reason, closer):
        cfg = self.config.guild(guild)
        async with cfg.tickets() as tickets:
            if str(cid) in tickets:
                tickets[str(cid)]["status"] = "closed"
                tickets[str(cid)]["close_reason"] = reason
                tickets[str(cid)]["closed_by"] = closer.id
        await self.log_event(guild, "close", {"closer": closer, "channel_id": cid, "reason": reason})

    async def can_close(self, user, guild, tdata):
        if tdata.get("user_id") == user.id:
            return True
        sroles = await self.config.guild(guild).support_roles()
        if any(r.id in sroles for r in user.roles):
            return True
        aroles = await self.config.guild(guild).admin_roles()
        if any(r.id in aroles for r in user.roles):
            return True
        if user.guild_permissions.administrator:
            return True
        return False

    # === CLAIM ===
    async def claim_ticket(self, interaction, cid):
        guild, user = interaction.guild, interaction.user
        cfg = self.config.guild(guild)
        if not await cfg.claim_enabled():
            await interaction.response.send_message("❌ Claim deaktiviert.", ephemeral=True)
            return
        sroles = await cfg.support_roles()
        if not any(r.id in sroles for r in user.roles) and not user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
            return
        async with cfg.tickets() as tickets:
            if str(cid) not in tickets:
                await interaction.response.send_message("❌ Kein Ticket.", ephemeral=True)
                return
            if tickets[str(cid)].get("claim_by"):
                c = guild.get_member(tickets[str(cid)]["claim_by"])
                await interaction.response.send_message(f"❌ Bereits von {c.mention if c else 'jemandem'} geclaimt.", ephemeral=True)
                return
            tickets[str(cid)]["claim_by"] = user.id
        await interaction.response.send_message(embed=Embed(title="✋ Geclaimt", description=f"{user.mention} kümmert sich.", color=Color.green()))
        await self.log_event(guild, "claim", {"user": user, "channel_id": cid})

    # === TRANSCRIPT ===
    async def generate_transcript_cmd(self, interaction, cid):
        channel = interaction.guild.get_channel(cid)
        if not channel:
            await interaction.response.send_message("❌ Channel nicht gefunden.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        msgs = []
        async for m in channel.history(limit=None, oldest_first=True):
            msgs.append(m)
        if not msgs:
            await interaction.followup.send("❌ Keine Nachrichten.", ephemeral=True)
            return
        lines = [f"Transkript - {channel.name}", f"Server: {interaction.guild.name}", f"Zeit: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}", "=" * 40, ""]
        for m in msgs:
            lines.append(f"[{m.created_at.strftime('%d.%m.%Y %H:%M')}] {m.author}: {m.content or '[Medien]'}")
        file = discord.File(fp="\n".join(lines).encode("utf-8"), filename=f"transcript_{channel.name}.txt")
        await interaction.followup.send(file=file, ephemeral=True)

    # === FEEDBACK ===
    async def save_feedback(self, interaction, tid, uid, rating, comment):
        async with self.config.user_from_id(uid).feedback() as fb:
            fb.append({"ticket_id": tid, "rating": rating, "comment": comment, "time": datetime.datetime.now().isoformat()})
        await interaction.response.send_message(f"✅ Danke! Bewertung: {'⭐' * rating}", ephemeral=True)

    # === HELPERS ===
    async def log_event(self, guild, etype, data):
        lid = await self.config.guild(guild).log_channel()
        if not lid:
            return
        lc = guild.get_channel(lid)
        if not lc:
            return
        e = Embed(title=f"📋 {etype}", color=Color.blue(), timestamp=datetime.datetime.now(datetime.timezone.utc))
        for k, v in data.items():
            if isinstance(v, (Member, User)):
                v = f"{v} ({v.id})"
            elif isinstance(v, TextChannel):
                v = f"{v.mention}"
            e.add_field(name=k, value=str(v)[:1024], inline=False)
        try:
            await lc.send(embed=e)
        except:
            pass

    # === USER COMMANDS ===
    @commands.hybrid_group(name="ticket", aliases=["tickets"])
    @commands.guild_only()
    async def ticket(self, ctx):
        """🎫 Ticket-Befehle"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @ticket.command(name="new", aliases=["neu", "create", "erstellen"])
    async def t_new(self, ctx, kategorie: Optional[str] = None):
        """Erstellt ein neues Ticket"""
        cats = await self.config.guild(ctx.guild).categories()
        enabled = {k: v for k, v in cats.items() if v.get("enabled", True)}
        if not enabled:
            await ctx.send("❌ Keine Kategorien.")
            return
        cat = kategorie or (await self.config.guild(ctx.guild).default_category()) or list(enabled.keys())[0]
        if cat not in enabled:
            await ctx.send(f"❌ Kategorie nicht gefunden. Verfügbar: {humanize_list(list(enabled.keys()))}")
            return
        await self.create_ticket(ctx.guild, ctx.author, cat)

    @ticket.command(name="close", aliases=["schliessen", "zu"])
    async def t_close(self, ctx, *, grund: str = "Kein Grund"):
        """Schließt das aktuelle Ticket"""
        tickets = await self.config.guild(ctx.guild).tickets()
        if str(ctx.channel.id) not in tickets:
            await ctx.send("❌ Kein Ticket-Channel.")
            return
        tdata = tickets[str(ctx.channel.id)]
        if not await self.can_close(ctx.author, ctx.guild, tdata):
            await ctx.send("❌ Keine Berechtigung.")
            return
        await self.close_ticket_internal(ctx.guild, ctx.channel.id, grund, ctx.author)
        if await self.config.guild(ctx.guild).feedback_enabled():
            u = ctx.guild.get_member(tdata.get("user_id"))
            if u:
                try:
                    await u.send(embed=Embed(title="⭐ Feedback", description="Bitte bewerte dein Ticket.", color=Color.gold()), view=FeedbackView(self, str(ctx.channel.id), u.id))
                except:
                    pass
        await ctx.send("✅ Geschlossen. Channel wird in 10s gelöscht.")
        await asyncio.sleep(10)
        try:
            await ctx.channel.delete(reason=grund)
        except:
            pass

    @ticket.command(name="add", aliases=["hinzufuegen"])
    async def t_add(self, ctx, user: Member):
        """Fügt User zum Ticket hinzu"""
        tickets = await self.config.guild(ctx.guild).tickets()
        if str(ctx.channel.id) not in tickets:
            await ctx.send("❌ Kein Ticket.")
            return
        sroles = await self.config.guild(ctx.guild).support_roles()
        if not any(r.id in sroles for r in ctx.author.roles) and not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Keine Berechtigung.")
            return
        try:
            await ctx.channel.set_permissions(user, read_messages=True, send_messages=True, embed_links=True, attach_files=True)
            await ctx.send(f"✅ {user.mention} hinzugefügt.")
        except Exception as e:
            await ctx.send(f"❌ Fehler: {e}")

    @ticket.command(name="remove", aliases=["entfernen"])
    async def t_remove(self, ctx, user: Member):
        """Entfernt User vom Ticket"""
        tickets = await self.config.guild(ctx.guild).tickets()
        if str(ctx.channel.id) not in tickets:
            await ctx.send("❌ Kein Ticket.")
            return
        sroles = await self.config.guild(ctx.guild).support_roles()
        if not any(r.id in sroles for r in ctx.author.roles) and not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Keine Berechtigung.")
            return
        if tickets[str(ctx.channel.id)].get("user_id") == user.id:
            await ctx.send("❌ Ersteller kann nicht entfernt werden.")
            return
        try:
            await ctx.channel.set_permissions(user, overwrite=None)
            await ctx.send(f"✅ {user.mention} entfernt.")
        except Exception as e:
            await ctx.send(f"❌ Fehler: {e}")

    @ticket.command(name="claim")
    async def t_claim(self, ctx):
        """Claim das Ticket"""
        if not await self.config.guild(ctx.guild).claim_enabled():
            await ctx.send("❌ Claim deaktiviert.")
            return
        tickets = await self.config.guild(ctx.guild).tickets()
        if str(ctx.channel.id) not in tickets:
            await ctx.send("❌ Kein Ticket.")
            return
        sroles = await self.config.guild(ctx.guild).support_roles()
        if not any(r.id in sroles for r in ctx.author.roles) and not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Keine Berechtigung.")
            return
        if tickets[str(ctx.channel.id)].get("claim_by"):
            c = ctx.guild.get_member(tickets[str(ctx.channel.id)]["claim_by"])
            await ctx.send(f"❌ Bereits von {c.mention if c else 'jemandem'} geclaimt.")
            return
        async with self.config.guild(ctx.guild).tickets() as t:
            t[str(ctx.channel.id)]["claim_by"] = ctx.author.id
        await ctx.send(embed=Embed(title="✋ Geclaimt", description=f"{ctx.author.mention} kümmert sich.", color=Color.green()))

    @ticket.command(name="transcript")
    async def t_transcript(self, ctx):
        """Erstellt Transkript"""
        tickets = await self.config.guild(ctx.guild).tickets()
        if str(ctx.channel.id) not in tickets:
            await ctx.send("❌ Kein Ticket.")
            return
        async with ctx.typing():
            msgs = []
            async for m in ctx.channel.history(limit=None, oldest_first=True):
                msgs.append(m)
            if not msgs:
                await ctx.send("❌ Keine Nachrichten.")
                return
            lines = [f"Transkript - {ctx.channel.name}", f"Server: {ctx.guild.name}", f"Zeit: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}", "=" * 40, ""]
            for m in msgs:
                lines.append(f"[{m.created_at.strftime('%d.%m.%Y %H:%M')}] {m.author}: {m.content or '[Medien]'}")
            await ctx.send(file=discord.File(fp="\n".join(lines).encode("utf-8"), filename=f"transcript_{ctx.channel.name}.txt"))

    @ticket.command(name="info")
    async def t_info(self, ctx):
        """Zeigt Ticket-Info"""
        tickets = await self.config.guild(ctx.guild).tickets()
        if str(ctx.channel.id) not in tickets:
            await ctx.send("❌ Kein Ticket.")
            return
        t = tickets[str(ctx.channel.id)]
        u = ctx.guild.get_member(t.get("user_id")) or await self.bot.fetch_user(t.get("user_id"))
        e = Embed(title="📋 Ticket-Info", color=Color(await self.config.guild(ctx.guild).embed_color()))
        e.add_field(name="Ersteller", value=f"{u.mention}\n{u} ({u.id})", inline=False)
        e.add_field(name="Kategorie", value=t.get("category", "?"), inline=True)
        e.add_field(name="Status", value=t.get("status", "open"), inline=True)
        if t.get("claim_by"):
            c = ctx.guild.get_member(t["claim_by"])
            e.add_field(name="Claim", value=c.mention if c else f"<@{t['claim_by']}>", inline=True)
        await ctx.send(embed=e)

    @ticket.command(name="stats")
    async def t_stats(self, ctx, user: Member = None):
        """Zeigt Statistiken"""
        tickets = await self.config.guild(ctx.guild).tickets()
        if user:
            ut = [t for t in tickets.values() if t.get("user_id") == user.id]
            e = Embed(title=f"📊 Stats für {user}", color=Color.blue())
            e.add_field(name="Gesamt", value=str(len(ut)), inline=True)
            e.add_field(name="Offen", value=str(len([t for t in ut if t.get("status") == "open"])), inline=True)
            e.add_field(name="Geschlossen", value=str(len([t for t in ut if t.get("status") == "closed"])), inline=True)
        else:
            e = Embed(title="📊 Server Stats", color=Color.blue())
            e.add_field(name="Gesamt", value=str(len(tickets)), inline=True)
            e.add_field(name="Offen", value=str(len([t for t in tickets.values() if t.get("status") == "open"])), inline=True)
            e.add_field(name="Geschlossen", value=str(len([t for t in tickets.values() if t.get("status") == "closed"])), inline=True)
        await ctx.send(embed=e)

    # === ADMIN COMMANDS ===
    @commands.group(name="ticketset", aliases=["ticketsystem"])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def ticketset(self, ctx):
        """Ticket-System Einstellungen"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @ticketset.command(name="quicksetup", aliases=["setup"])
    async def ts_quicksetup(self, ctx):
        """🚀 Schnelleinrichtung"""
        guild = ctx.guild
        sroles = await self.config.guild(guild).support_roles()
        if not sroles:
            sr = discord.utils.get(guild.roles, name="Support")
            if sr:
                await self.config.guild(guild).support_roles.set([sr.id])
                await ctx.send(f"✅ Support-Rolle: {sr.mention}")
            else:
                await ctx.send(f"⚠️ Keine Support-Rolle! Erstelle sie oder nutze:\n`{ctx.prefix}ticketset supportrole @Rolle`")
                return
        tc = await self.config.guild(guild).ticket_category()
        if not tc:
            cat = discord.utils.get(guild.categories, name="Tickets")
            if cat:
                await self.config.guild(guild).ticket_category.set(cat.id)
                await ctx.send(f"✅ Kategorie: {cat.name}")
            else:
                srs = await self.config.guild(guild).support_roles()
                overs = {guild.default_role: discord.PermissionOverwrite(read_messages=False), guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)}
                for rid in srs:
                    r = guild.get_role(rid)
                    if r:
                        overs[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                try:
                    cat = await guild.create_category("Tickets", overwrites=overs, reason="Ticket Setup")
                    await self.config.guild(guild).ticket_category.set(cat.id)
                    await ctx.send(f"✅ Kategorie erstellt: {cat.name}")
                except Exception as e:
                    await ctx.send(f"❌ Konnte Kategorie nicht erstellen: {e}")
        e = Embed(title="✅ Setup abgeschlossen!", description="Erstelle jetzt ein Panel:", color=Color.green())
        e.add_field(name="Panel", value=f"`{ctx.prefix}ticketset panel create`")
        e.add_field(name="Hilfe", value=f"`{ctx.prefix}help ticket`")
        await ctx.send(embed=e)

    @ticketset.command(name="ticketcat", aliases=["ticketkategorie"])
    async def ts_ticketcat(self, ctx, category: CategoryChannel = None):
        """Setzt die Ticket-Kategorie"""
        if not category:
            await self.config.guild(ctx.guild).ticket_category.clear()
            await ctx.send("✅ Entfernt.")
        else:
            await self.config.guild(ctx.guild).ticket_category.set(category.id)
            await ctx.send(f"✅ Kategorie: {category.mention}")

    @ticketset.command(name="supportrole", aliases=["supportrolle"])
    async def ts_supportrole(self, ctx, *roles: Role):
        """Setzt Support-Rollen"""
        if not roles:
            await self.config.guild(ctx.guild).support_roles.clear()
            await ctx.send("✅ Entfernt.")
        else:
            await self.config.guild(ctx.guild).support_roles.set([r.id for r in roles])
            await ctx.send(f"✅ Rollen: {humanize_list([r.mention for r in roles])}")

    @ticketset.command(name="adminrole", aliases=["adminrolle"])
    async def ts_adminrole(self, ctx, *roles: Role):
        """Setzt Admin-Rollen"""
        if not roles:
            await self.config.guild(ctx.guild).admin_roles.clear()
            await ctx.send("✅ Entfernt.")
        else:
            await self.config.guild(ctx.guild).admin_roles.set([r.id for r in roles])
            await ctx.send(f"✅ Rollen: {humanize_list([r.mention for r in roles])}")

    @ticketset.command(name="limit")
    async def ts_limit(self, ctx, limit: int):
        """Setzt Ticket-Limit pro User"""
        if limit < 1:
            await ctx.send("❌ Mindestens 1.")
            return
        await self.config.guild(ctx.guild).ticket_limit.set(limit)
        await ctx.send(f"✅ Limit: {limit}")

    @ticketset.command(name="logchannel", aliases=["log"])
    async def ts_log(self, ctx, channel: TextChannel = None):
        """Setzt Log-Channel"""
        if not channel:
            await self.config.guild(ctx.guild).log_channel.clear()
            await ctx.send("✅ Entfernt.")
        else:
            await self.config.guild(ctx.guild).log_channel.set(channel.id)
            await ctx.send(f"✅ Log: {channel.mention}")

    @ticketset.command(name="autoclose")
    async def ts_autoclose(self, ctx, stunden: int):
        """Auto-Close in Stunden (0 = aus)"""
        if stunden < 0:
            await ctx.send("❌ Muss positiv sein.")
            return
        await self.config.guild(ctx.guild).auto_close_hours.set(stunden)
        if stunden == 0:
            await ctx.send("✅ Auto-Close deaktiviert.")
        else:
            await ctx.send(f"✅ Auto-Close nach {stunden}h.")

    @ticketset.command(name="color", aliases=["farbe"])
    async def ts_color(self, ctx, color: str):
        """Setzt Embed-Farbe (Hex, z.B. #3498db)"""
        try:
            c = int(color[1:], 16) if color.startswith("#") else int(color)
            await self.config.guild(ctx.guild).embed_color.set(c)
            await ctx.send(embed=Embed(title="✅ Farbe", color=Color(c)))
        except:
            await ctx.send("❌ Ungültige Farbe.")

    @ticketset.command(name="dm")
    async def ts_dm(self, ctx, aktiv: bool):
        """DM-Benachrichtigungen an/aus"""
        await self.config.guild(ctx.guild).dm_notifications.set(aktiv)
        await ctx.send(f"✅ DM: {'an' if aktiv else 'aus'}")

    @ticketset.command(name="claim")
    async def ts_claim(self, ctx, aktiv: bool):
        """Claim-System an/aus"""
        await self.config.guild(ctx.guild).claim_enabled.set(aktiv)
        await ctx.send(f"✅ Claim: {'an' if aktiv else 'aus'}")

    @ticketset.command(name="feedback")
    async def ts_feedback(self, ctx, aktiv: bool):
        """Feedback-System an/aus"""
        await self.config.guild(ctx.guild).feedback_enabled.set(aktiv)
        await ctx.send(f"✅ Feedback: {'an' if aktiv else 'aus'}")

    @ticketset.command(name="ping")
    async def ts_ping(self, ctx, aktiv: bool):
        """Ping bei Erstellung an/aus"""
        await self.config.guild(ctx.guild).ping_on_create.set(aktiv)
        await ctx.send(f"✅ Ping: {'an' if aktiv else 'aus'}")

    @ticketset.command(name="pingrole")
    async def ts_pingrole(self, ctx, role: Role = None):
        """Rolle die gepingt wird"""
        if not role:
            await self.config.guild(ctx.guild).ping_role.clear()
            await ctx.send("✅ Entfernt.")
        else:
            await self.config.guild(ctx.guild).ping_role.set(role.id)
            await ctx.send(f"✅ Ping-Rolle: {role.mention}")

    @ticketset.command(name="showsettings", aliases=["settings"])
    async def ts_settings(self, ctx):
        """Zeigt Einstellungen"""
        d = await self.config.guild(ctx.guild).all()
        e = Embed(title="📋 Einstellungen", color=Color(d.get("embed_color", 0x3498db)))
        cat = ctx.guild.get_channel(d.get("ticket_category")) if d.get("ticket_category") else None
        e.add_field(name="Kategorie", value=cat.mention if cat else "Keine", inline=True)
        srs = [ctx.guild.get_role(r) for r in d.get("support_roles", []) if ctx.guild.get_role(r)]
        e.add_field(name="Support-Rollen", value=humanize_list([r.mention for r in srs]) if srs else "Keine", inline=False)
        e.add_field(name="Limit", value=str(d.get("ticket_limit", 3)), inline=True)
        e.add_field(name="Auto-Close", value=f"{d.get('auto_close_hours', 72)}h", inline=True)
        e.add_field(name="Claim", value="✅" if d.get("claim_enabled") else "❌", inline=True)
        e.add_field(name="Feedback", value="✅" if d.get("feedback_enabled") else "❌", inline=True)
        e.add_field(name="DM", value="✅" if d.get("dm_notifications") else "❌", inline=True)
        await ctx.send(embed=e)

    # === KATEGORIEN ===
    @ticketset.group(name="cats", aliases=["kategorien"])
    async def ts_cats(self, ctx):
        """Ticket-Kategorien verwalten"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @ts_cats.command(name="add")
    async def cats_add(self, ctx, name: str, emoji: str = "🎫", *, beschreibung: str = "Keine Beschreibung"):
        """Kategorie hinzufügen"""
        cats = await self.config.guild(ctx.guild).categories()
        if name in cats:
            await ctx.send("❌ Existiert bereits.")
            return
        cats[name] = {"emoji": emoji, "description": beschreibung, "color": 0x3498db, "enabled": True}
        await self.config.guild(ctx.guild).categories.set(cats)
        await ctx.send(f"✅ Kategorie '{name}' hinzugefügt.")

    @ts_cats.command(name="remove", aliases=["delete"])
    async def cats_remove(self, ctx, name: str):
        """Kategorie entfernen"""
        cats = await self.config.guild(ctx.guild).categories()
        if name not in cats:
            await ctx.send("❌ Nicht gefunden.")
            return
        del cats[name]
        await self.config.guild(ctx.guild).categories.set(cats)
        await ctx.send(f"✅ '{name}' entfernt.")

    @ts_cats.command(name="toggle")
    async def cats_toggle(self, ctx, name: str):
        """Kategorie an/aus"""
        cats = await self.config.guild(ctx.guild).categories()
        if name not in cats:
            await ctx.send("❌ Nicht gefunden.")
            return
        cats[name]["enabled"] = not cats[name].get("enabled", True)
        await self.config.guild(ctx.guild).categories.set(cats)
        await ctx.send(f"✅ '{name}' {'aktiviert' if cats[name]['enabled'] else 'deaktiviert'}.")

    @ts_cats.command(name="list")
    async def cats_list(self, ctx):
        """Kategorien auflisten"""
        cats = await self.config.guild(ctx.guild).categories()
        if not cats:
            await ctx.send("Keine Kategorien.")
            return
        e = Embed(title="📋 Kategorien", color=Color(await self.config.guild(ctx.guild).embed_color()))
        for n, d in cats.items():
            st = "✅" if d.get("enabled", True) else "❌"
            e.add_field(name=f"{st} {d.get('emoji', '🎫')} {n}", value=d.get("description", "?"), inline=False)
        await ctx.send(embed=e)

    # === PANELS ===
    @ticketset.group(name="panel")
    async def ts_panel(self, ctx):
        """Panel verwalten"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @ts_panel.command(name="create")
    async def panel_create(self, ctx, channel: TextChannel = None, stil: str = "buttons", *, titel: str = "🎫 Ticket-System"):
        """Panel erstellen (stil: buttons oder dropdown)"""
        channel = channel or ctx.channel
        data = await self.config.guild(ctx.guild).all()
        cats = {k: v for k, v in data.get("categories", {}).items() if v.get("enabled", True)}
        if not cats:
            await ctx.send("❌ Keine aktiven Kategorien.")
            return
        e = Embed(title=titel, description="Wähle eine Kategorie:", color=Color(data.get("embed_color", 0x3498db)))
        for n, d in cats.items():
            e.add_field(name=f"{d.get('emoji', '🎫')} {n}", value=d.get("description", "?"), inline=False)
        view = TicketPanelDropdownView(self, cats) if stil.lower() == "dropdown" else TicketPanelView(self, cats, data.get("button_style", "primary"))
        msg = await channel.send(embed=e, view=view)
        async with self.config.guild(ctx.guild).panels() as panels:
            panels[str(msg.id)] = {"channel_id": channel.id, "style": stil, "created": datetime.datetime.now().isoformat()}
        await ctx.send(f"✅ Panel erstellt in {channel.mention}")

    @ts_panel.command(name="delete")
    async def panel_delete(self, ctx, message_id: str):
        """Panel löschen"""
        panels = await self.config.guild(ctx.guild).panels()
        if message_id not in panels:
            await ctx.send("❌ Nicht gefunden.")
            return
        pd = panels[message_id]
        ch = ctx.guild.get_channel(pd.get("channel_id"))
        if ch:
            try:
                m = await ch.fetch_message(int(message_id))
                await m.delete()
            except:
                pass
        del panels[message_id]
        await self.config.guild(ctx.guild).panels.set(panels)
        await ctx.send("✅ Gelöscht.")

    @ts_panel.command(name="list")
    async def panel_list(self, ctx):
        """Panels auflisten"""
        panels = await self.config.guild(ctx.guild).panels()
        if not panels:
            await ctx.send("Keine Panels.")
            return
        e = Embed(title="📋 Panels", color=Color.blue())
        for pid, pd in panels.items():
            ch = ctx.guild.get_channel(pd.get("channel_id"))
            e.add_field(name=pid[:10] + "...", value=f"Channel: {ch.mention if ch else '?'}\nStil: {pd.get('style', 'buttons')}", inline=False)
        await ctx.send(embed=e)

    # === BLACKLIST ===
    @ticketset.group(name="blacklist")
    async def ts_blacklist(self, ctx):
        """Blacklist verwalten"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @ts_blacklist.command(name="add")
    async def bl_add(self, ctx, user: Member):
        """User zur Blacklist hinzufügen"""
        bl = await self.config.guild(ctx.guild).blacklist()
        if user.id in bl:
            await ctx.send("❌ Bereits vorhanden.")
            return
        bl.append(user.id)
        await self.config.guild(ctx.guild).blacklist.set(bl)
        await ctx.send(f"✅ {user.mention} zur Blacklist hinzugefügt.")

    @ts_blacklist.command(name="remove")
    async def bl_remove(self, ctx, user: Member):
        """User von Blacklist entfernen"""
        bl = await self.config.guild(ctx.guild).blacklist()
        if user.id not in bl:
            await ctx.send("❌ Nicht gefunden.")
            return
        bl.remove(user.id)
        await self.config.guild(ctx.guild).blacklist.set(bl)
        await ctx.send(f"✅ {user.mention} entfernt.")

    @ts_blacklist.command(name="list")
    async def bl_list(self, ctx):
        """Blacklist anzeigen"""
        bl = await self.config.guild(ctx.guild).blacklist()
        if not bl:
            await ctx.send("Leer.")
            return
        users = [ctx.guild.get_member(u) for u in bl]
        await ctx.send(embed=Embed(title="🚫 Blacklist", description="\n".join([u.mention if u else f"<@{uid}>" for uid, u in zip(bl, users)])))

    # === RESET ===
    @ticketset.command(name="reset")
    async def ts_reset(self, ctx, confirm: str = None):
        """Alle Einstellungen zurücksetzen"""
        if confirm != "bestätigen":
            await ctx.send("⚠️ Nutze: `[p]ticketset reset bestätigen`")
            return
        await self.config.guild(ctx.guild).clear()
        await ctx.send("✅ Zurückgesetzt.")
