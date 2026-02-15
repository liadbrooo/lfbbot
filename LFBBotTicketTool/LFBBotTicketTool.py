"""
LFBBotTicketTool - Hauptdatei
Ein umfassendes Ticket-System mit allen modernen Funktionen
100% auf Deutsch
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

# Logging Setup
log = logging.getLogger("red.lfbbottickettool")

# Konstanten
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
        "Allgemein": {
            "emoji": "🎫",
            "description": "Allgemeine Anfragen und Fragen",
            "color": 0x3498db,
            "enabled": True,
        },
        "Support": {
            "emoji": "🛠️",
            "description": "Technischer Support und Hilfe",
            "color": 0xe74c3c,
            "enabled": True,
        },
        "Report": {
            "emoji": "⚠️",
            "description": "Spieler melden oder Probleme melden",
            "color": 0xf39c12,
            "enabled": True,
        },
        "Bewerbung": {
            "emoji": "📝",
            "description": "Bewerbungen für Team-Positionen",
            "color": 0x9b59b6,
            "enabled": True,
        },
        "Partner": {
            "emoji": "🤝",
            "description": "Partner-Anfragen und Kooperationen",
            "color": 0x1abc9c,
            "enabled": True,
        },
    },
    "default_category": "Allgemein",
    "welcome_message": "Willkommen im Ticket, {user}!\n\nEin Team-Mitglied wird sich in Kürze um dich kümmern.\nBitte beschreibe dein Anliegen so detailliert wie möglich.",
    "transcript_channel": None,
    "log_channel": None,
    "blacklist": [],
    "feedback_enabled": True,
    "auto_close_hours": 72,
    "auto_close_warning_hours": 24,
    "claim_enabled": True,
    "ticket_name_format": "ticket-{counter}",
    "notify_on_claim": True,
    "dm_notifications": True,
    "embed_color": 0x3498db,
    "button_style": "primary",
    "show_user_info": True,
    "ping_on_create": True,
    "ping_role": None,
}

DEFAULT_USER = {"tickets_created": 0, "tickets_closed": 0, "feedback": []}


class TicketButton(ui.Button):
    """Ticket Button für das Panel"""

    def __init__(self, cog, category: str, emoji: str, label: str, style: ButtonStyle):
        super().__init__(style=style, emoji=emoji, label=label, custom_id=f"lfbbot_ticket_{category}")
        self.cog = cog
        self.category = category

    async def callback(self, interaction: Interaction):
        await self.cog.create_ticket_callback(interaction, self.category)


class TicketSelectMenu(ui.Select):
    """Dropdown Menü für Ticket-Kategorien"""

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
            custom_id="lfbbot_ticket_category_select",
        )

    async def callback(self, interaction: Interaction):
        await self.cog.create_ticket_callback(interaction, self.values[0])


class TicketPanelView(ui.View):
    """Main Panel View mit Buttons"""

    def __init__(self, cog, categories: Dict, button_style: str = "primary"):
        super().__init__(timeout=None)
        style_map = {
            "primary": ButtonStyle.primary,
            "secondary": ButtonStyle.secondary,
            "success": ButtonStyle.success,
            "danger": ButtonStyle.danger,
        }
        style = style_map.get(button_style, ButtonStyle.primary)

        for name, data in categories.items():
            if data.get("enabled", True):
                button = TicketButton(
                    cog=cog,
                    category=name,
                    emoji=data.get("emoji", "🎫"),
                    label=name,
                    style=style,
                )
                self.add_item(button)


class TicketPanelDropdownView(ui.View):
    """Panel View mit Dropdown"""

    def __init__(self, cog, categories: Dict):
        super().__init__(timeout=None)
        self.add_item(TicketSelectMenu(cog, categories))


class CloseReasonModal(ui.Modal):
    """Modal für Ticket-Schließung mit Grund"""

    def __init__(self, cog, channel_id: int):
        self.cog = cog
        self.channel_id = channel_id
        super().__init__(title="Ticket schließen", timeout=300)

        self.reason = ui.TextInput(
            label="Grund für Schließung",
            style=TextStyle.paragraph,
            placeholder="Bitte gib einen Grund für die Schließung an...",
            required=True,
            max_length=500,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: Interaction):
        await self.cog.close_ticket_interaction(interaction, self.channel_id, self.reason.value)


class FeedbackModal(ui.Modal):
    """Modal für Ticket-Feedback"""

    def __init__(self, cog, ticket_id: str, user_id: int):
        self.cog = cog
        self.ticket_id = ticket_id
        self.user_id = user_id
        super().__init__(title="Ticket-Feedback", timeout=300)

        self.rating = ui.TextInput(
            label="Bewertung (1-5 Sterne)",
            style=TextStyle.short,
            placeholder="1, 2, 3, 4 oder 5",
            required=True,
            max_length=1,
        )
        self.add_item(self.rating)

        self.comment = ui.TextInput(
            label="Kommentar (optional)",
            style=TextStyle.paragraph,
            placeholder="Teile deine Erfahrung mit uns...",
            required=False,
            max_length=1000,
        )
        self.add_item(self.comment)

    async def on_submit(self, interaction: Interaction):
        try:
            rating = int(self.rating.value)
            if rating < 1 or rating > 5:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ Bitte gib eine gültige Bewertung zwischen 1 und 5 an.",
                ephemeral=True,
            )
            return

        await self.cog.save_feedback(
            interaction, self.ticket_id, self.user_id, rating, self.comment.value
        )


class TicketControlView(ui.View):
    """Control View für Tickets"""

    def __init__(self, cog, channel_id: int, ticket_data: Dict):
        super().__init__(timeout=None)
        self.cog = cog
        self.channel_id = channel_id
        self.ticket_data = ticket_data

    @ui.button(label="Schließen", emoji="🔒", style=ButtonStyle.danger, custom_id="lfbbot_ticket_close")
    async def close_button(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_modal(CloseReasonModal(self.cog, self.channel_id))

    @ui.button(label="Claim", emoji="✋", style=ButtonStyle.primary, custom_id="lfbbot_ticket_claim")
    async def claim_button(self, interaction: Interaction, button: ui.Button):
        await self.cog.claim_ticket(interaction, self.channel_id)

    @ui.button(label="Transkript", emoji="📝", style=ButtonStyle.secondary, custom_id="lfbbot_ticket_transcript")
    async def transcript_button(self, interaction: Interaction, button: ui.Button):
        await self.cog.generate_transcript(interaction, self.channel_id)

    @ui.button(label="Hinzufügen", emoji="➕", style=ButtonStyle.success, custom_id="lfbbot_ticket_add_user")
    async def add_user_button(self, interaction: Interaction, button: ui.Button):
        await interaction.response.send_message(
            "Verwende `/ticket add @user` oder `[p]ticket add @user` um einen User zum Ticket hinzuzufügen.",
            ephemeral=True,
        )


class FeedbackView(ui.View):
    """View für Feedback-Anfrage"""

    def __init__(self, cog, ticket_id: str, user_id: int):
        super().__init__(timeout=3600)
        self.cog = cog
        self.ticket_id = ticket_id
        self.user_id = user_id

    @ui.button(label="Feedback geben", emoji="⭐", style=ButtonStyle.primary)
    async def feedback_button(self, interaction: Interaction, button: ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ Du kannst nur dein eigenes Ticket bewerten.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(FeedbackModal(self.cog, self.ticket_id, self.user_id))

    @ui.button(label="Später", style=ButtonStyle.secondary)
    async def later_button(self, interaction: Interaction, button: ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Nicht für dich.", ephemeral=True)
            return

        await interaction.response.send_message("Okay, du kannst später Feedback geben.", ephemeral=True)
        self.stop()


class LFBBotTicketTool(commands.Cog):
    """
    🎫 LFBBotTicketTool - Umfassendes Ticket-System

    Ein vollständiges Ticket-System mit:
    - Multiple Ticket-Kategorien
    - Transkripte
    - Claim-System
    - Feedback-System
    - Blacklist
    - Auto-Close
    - Und vieles mehr!

    Verwende [p]ticketsetup für die Ersteinrichtung.
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210, force_registration=True)
        self.config.register_guild(**DEFAULT_GUILD)
        self.config.register_user(**DEFAULT_USER)
        self._task = None
        self._setup_task = None

    async def cog_load(self):
        """Wird beim Laden des Cogs ausgeführt"""
        self._task = asyncio.create_task(self.auto_close_loop())
        self._setup_task = asyncio.create_task(self.setup_persistent_views())
        log.info("LFBBotTicketTool geladen")

    async def cog_unload(self):
        """Wird beim Entladen des Cogs ausgeführt"""
        if self._task:
            self._task.cancel()
        if self._setup_task:
            self._setup_task.cancel()
        log.info("LFBBotTicketTool entladen")

    async def setup_persistent_views(self):
        """Setup der persistenten Views"""
        await self.bot.wait_until_red_ready()
        for guild in self.bot.guilds:
            guild_data = await self.config.guild(guild).all()
            for panel_id, panel_data in guild_data.get("panels", {}).items():
                if panel_data.get("style") == "dropdown":
                    view = TicketPanelDropdownView(self, guild_data.get("categories", {}))
                else:
                    view = TicketPanelView(
                        self, guild_data.get("categories", {}), guild_data.get("button_style", "primary")
                    )
                self.bot.add_view(view)

    async def auto_close_loop(self):
        """Loop für Auto-Close der Tickets"""
        await self.bot.wait_until_red_ready()
        while True:
            try:
                await self.check_auto_close()
            except Exception as e:
                log.error(f"Fehler im Auto-Close Loop: {e}")
            await asyncio.sleep(3600)

    async def check_auto_close(self):
        """Prüft alle Tickets auf Auto-Close"""
        for guild in self.bot.guilds:
            guild_data = await self.config.guild(guild).all()
            auto_close_hours = guild_data.get("auto_close_hours", 72)
            
            if auto_close_hours == 0:
                continue

            for channel_id, ticket_data in guild_data.get("tickets", {}).items():
                if ticket_data.get("status") != "open":
                    continue

                channel = guild.get_channel(int(channel_id))
                if not channel:
                    continue

                last_message = None
                async for msg in channel.history(limit=1):
                    last_message = msg
                    break

                if not last_message:
                    continue

                hours_since = (datetime.datetime.now(datetime.timezone.utc) - last_message.created_at).total_seconds() / 3600
                warning_hours = guild_data.get("auto_close_warning_hours", 24)

                if hours_since >= auto_close_hours:
                    await self.auto_close_ticket(guild, int(channel_id), ticket_data)
                elif hours_since >= (auto_close_hours - warning_hours):
                    if not ticket_data.get("warning_sent"):
                        await self.send_auto_close_warning(channel, auto_close_hours - hours_since)
                        async with self.config.guild(guild).tickets() as tickets:
                            if channel_id in tickets:
                                tickets[channel_id]["warning_sent"] = True

    async def send_auto_close_warning(self, channel: TextChannel, hours_left: float):
        """Sendet Warnung vor Auto-Close"""
        embed = Embed(
            title="⚠️ Auto-Close Warnung",
            description=f"Dieses Ticket wird in ca. {hours_left:.0f} Stunden automatisch geschlossen, "
            f"falls keine neue Nachricht gesendet wird.\n\n"
            f"Bitte antworte, um das Ticket offen zu halten.",
            color=Color.orange(),
        )
        try:
            await channel.send(embed=embed)
        except Exception as e:
            log.error(f"Konnte Auto-Close Warnung nicht senden: {e}")

    async def auto_close_ticket(self, guild: discord.Guild, channel_id: int, ticket_data: Dict):
        """Schließt ein Ticket automatisch"""
        channel = guild.get_channel(channel_id)
        if not channel:
            return

        try:
            embed = Embed(
                title="🔒 Ticket automatisch geschlossen",
                description="Dieses Ticket wurde aufgrund von Inaktivität automatisch geschlossen.",
                color=Color.red(),
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            await channel.send(embed=embed)
            await self.close_ticket_internal(guild, channel_id, "Automatisch geschlossen (Inaktivität)", self.bot.user)
            
            # Channel nach 10 Sekunden löschen
            await asyncio.sleep(10)
            try:
                await channel.delete(reason="Auto-Close: Inaktivität")
            except:
                pass
        except Exception as e:
            log.error(f"Fehler beim Auto-Close: {e}")

    # ==================== TICKET ERSTELLUNG ====================

    async def create_ticket_callback(self, interaction: Interaction, category: str):
        """Callback für Ticket-Erstellung"""
        guild = interaction.guild
        user = interaction.user

        # Prüfe Blacklist
        blacklist = await self.config.guild(guild).blacklist()
        if user.id in blacklist:
            await interaction.response.send_message(
                "❌ Du stehst auf der Blacklist und kannst keine Tickets erstellen.",
                ephemeral=True,
            )
            return

        # Prüfe Ticket-Limit
        ticket_limit = await self.config.guild(guild).ticket_limit()
        user_tickets = await self.get_user_open_tickets(guild, user.id)
        if len(user_tickets) >= ticket_limit:
            await interaction.response.send_message(
                f"❌ Du hast bereits das Maximum von {ticket_limit} offenen Tickets. "
                f"Bitte schließe ein Ticket bevor du ein neues erstellst.",
                ephemeral=True,
            )
            return

        # Prüfe Kategorie
        categories = await self.config.guild(guild).categories()
        if category not in categories or not categories[category].get("enabled", True):
            await interaction.response.send_message(
                "❌ Diese Ticket-Kategorie existiert nicht oder ist deaktiviert.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.create_ticket(guild, user, category, interaction)

    async def create_ticket(
        self,
        guild: discord.Guild,
        user: Union[Member, User],
        category_name: str,
        interaction: Optional[Interaction] = None,
    ):
        """Erstellt ein neues Ticket"""
        guild_config = self.config.guild(guild)
        guild_data = await guild_config.all()

        # Kategorie Channel
        ticket_category_id = guild_data.get("ticket_category")
        ticket_category = guild.get_channel(ticket_category_id) if ticket_category_id else None

        # Ticket Counter
        async with guild_config.ticket_counter() as counter:
            counter += 1
            ticket_number = counter

        # Ticket Name
        name_format = guild_data.get("ticket_name_format", "ticket-{counter}")
        channel_name = name_format.format(
            counter=ticket_number,
            user=user.name.lower()[:10],
            category=category_name.lower()[:10],
        )
        channel_name = re.sub(r"[^a-z0-9\-]", "-", channel_name)[:100]

        # Berechtigungen
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                embed_links=True,
                attach_files=True,
            ),
            guild.me: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True,
            ),
        }

        # Support Rollen hinzufügen
        support_roles = guild_data.get("support_roles", [])
        for role_id in support_roles:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    manage_messages=True,
                )

        # Ticket Channel erstellen
        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                category=ticket_category,
                overwrites=overwrites,
                reason=f"Ticket erstellt von {user} - {category_name}",
            )
        except discord.Forbidden:
            msg = "❌ Ich habe keine Berechtigung, einen Channel zu erstellen."
            if interaction:
                await interaction.followup.send(msg, ephemeral=True)
            return None
        except Exception as e:
            log.error(f"Fehler beim Erstellen des Channels: {e}")
            msg = f"❌ Fehler beim Erstellen des Tickets: {e}"
            if interaction:
                await interaction.followup.send(msg, ephemeral=True)
            return None

        # Kategorie-Daten
        cat_data = guild_data.get("categories", {}).get(category_name, {})
        cat_color = cat_data.get("color", guild_data.get("embed_color", 0x3498db))
        cat_emoji = cat_data.get("emoji", "🎫")

        # Ticket Daten speichern
        ticket_data = {
            "channel_id": channel.id,
            "user_id": user.id,
            "category": category_name,
            "created_at": datetime.datetime.now().isoformat(),
            "status": "open",
            "claim_by": None,
            "close_reason": None,
            "warning_sent": False,
        }

        async with guild_config.tickets() as tickets:
            tickets[str(channel.id)] = ticket_data

        # Willkommensnachricht
        welcome_msg = guild_data.get("welcome_message", "").format(
            user=user.mention,
            ticket_id=ticket_number,
            category=category_name,
        )

        # Embed erstellen
        embed = Embed(
            title=f"{cat_emoji} Ticket #{ticket_number} - {category_name}",
            description=welcome_msg,
            color=Color(cat_color),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )

        # User Info
        if guild_data.get("show_user_info", True):
            embed.add_field(name="Ersteller", value=f"{user.mention}\n{user} ({user.id})", inline=True)
            embed.set_thumbnail(url=user.display_avatar.url)

        embed.add_field(name="Kategorie", value=category_name, inline=True)
        embed.add_field(name="Ticket-ID", value=f"#{ticket_number}", inline=True)

        # Control View
        view = TicketControlView(self, channel.id, ticket_data)

        # Nachricht senden
        content = None
        if guild_data.get("ping_on_create", True):
            ping_role_id = guild_data.get("ping_role")
            if ping_role_id:
                ping_role = guild.get_role(ping_role_id)
                if ping_role:
                    content = ping_role.mention
            else:
                mentions = []
                for role_id in support_roles:
                    role = guild.get_role(role_id)
                    if role:
                        mentions.append(role.mention)
                if mentions:
                    content = " ".join(mentions[:3])

        try:
            await channel.send(content=content, embed=embed, view=view)
        except Exception as e:
            log.error(f"Konnte Willkommensnachricht nicht senden: {e}")

        # DM Benachrichtigung
        if guild_data.get("dm_notifications", True):
            try:
                dm_embed = Embed(
                    title="🎫 Ticket erstellt",
                    description=f"Du hast erfolgreich ein Ticket auf **{guild.name}** erstellt.\n\n"
                    f"**Kategorie:** {category_name}\n"
                    f"**Channel:** {channel.mention}",
                    color=Color.green(),
                )
                await user.send(embed=dm_embed)
            except:
                pass

        # Logging
        await self.log_event(guild, "ticket_create", {
            "user": user,
            "channel": channel,
            "category": category_name,
            "ticket_number": ticket_number,
        })

        # Antwort
        if interaction:
            await interaction.followup.send(
                f"✅ Ticket erfolgreich erstellt! {channel.mention}",
                ephemeral=True,
            )

        return channel

    # ==================== TICKET SCHLIESSUNG ====================

    async def close_ticket_interaction(
        self,
        interaction: Interaction,
        channel_id: int,
        reason: str,
    ):
        """Schließt ein Ticket über Interaction"""
        guild = interaction.guild
        user = interaction.user

        guild_config = self.config.guild(guild)
        tickets = await guild_config.tickets()

        if str(channel_id) not in tickets:
            await interaction.response.send_message(
                "❌ Dies ist kein Ticket-Channel.",
                ephemeral=True,
            )
            return

        ticket_data = tickets[str(channel_id)]

        if not await self.can_close_ticket(user, guild, ticket_data):
            await interaction.response.send_message(
                "❌ Du hast keine Berechtigung, dieses Ticket zu schließen.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        await self.close_ticket_internal(guild, channel_id, reason, user)

        # Feedback anfordern
        if await guild_config.feedback_enabled():
            ticket_user_id = ticket_data.get("user_id")
            if ticket_user_id:
                ticket_user = guild.get_member(ticket_user_id)
                if ticket_user:
                    await self.request_feedback(ticket_user, str(channel_id))

        await interaction.followup.send(
            "✅ Ticket wurde geschlossen. Der Channel wird in 10 Sekunden gelöscht.",
            ephemeral=True,
        )

        # Channel löschen nach Verzögerung
        await asyncio.sleep(10)
        channel = guild.get_channel(channel_id)
        if channel:
            try:
                await channel.delete(reason=f"Ticket geschlossen von {user}: {reason}")
            except:
                pass

    async def close_ticket_internal(
        self,
        guild: discord.Guild,
        channel_id: int,
        reason: str,
        closer: Union[Member, User],
    ):
        """Interne Ticket-Schließung"""
        guild_config = self.config.guild(guild)

        async with guild_config.tickets() as tickets:
            if str(channel_id) in tickets:
                tickets[str(channel_id)]["status"] = "closed"
                tickets[str(channel_id)]["close_reason"] = reason
                tickets[str(channel_id)]["closed_at"] = datetime.datetime.now().isoformat()
                tickets[str(channel_id)]["closed_by"] = closer.id

        # Logging
        await self.log_event(guild, "ticket_close", {
            "closer": closer,
            "channel_id": channel_id,
            "reason": reason,
        })

    async def can_close_ticket(self, user: Member, guild: discord.Guild, ticket_data: Dict) -> bool:
        """Prüft ob ein User ein Ticket schließen darf"""
        if ticket_data.get("user_id") == user.id:
            return True

        support_roles = await self.config.guild(guild).support_roles()
        if any(role.id in support_roles for role in user.roles):
            return True

        admin_roles = await self.config.guild(guild).admin_roles()
        if any(role.id in admin_roles for role in user.roles):
            return True

        if user.guild_permissions.administrator:
            return True

        return False

    # ==================== CLAIM SYSTEM ====================

    async def claim_ticket(self, interaction: Interaction, channel_id: int):
        """Claim ein Ticket"""
        guild = interaction.guild
        user = interaction.user

        guild_config = self.config.guild(guild)

        if not await guild_config.claim_enabled():
            await interaction.response.send_message(
                "❌ Das Claim-System ist deaktiviert.",
                ephemeral=True,
            )
            return

        support_roles = await guild_config.support_roles()
        if not any(role.id in support_roles for role in user.roles):
            if not user.guild_permissions.administrator:
                await interaction.response.send_message(
                    "❌ Du hast keine Berechtigung, Tickets zu claimen.",
                    ephemeral=True,
                )
                return

        async with guild_config.tickets() as tickets:
            if str(channel_id) not in tickets:
                await interaction.response.send_message(
                    "❌ Dies ist kein Ticket-Channel.",
                    ephemeral=True,
                )
                return

            ticket_data = tickets[str(channel_id)]

            if ticket_data.get("claim_by"):
                claimer_id = ticket_data["claim_by"]
                claimer = guild.get_member(claimer_id)
                await interaction.response.send_message(
                    f"❌ Dieses Ticket wurde bereits von {claimer.mention if claimer else f'<@{claimer_id}>'} geclaimt.",
                    ephemeral=True,
                )
                return

            tickets[str(channel_id)]["claim_by"] = user.id

        embed = Embed(
            title="✋ Ticket geclaimt",
            description=f"{user.mention} hat dieses Ticket übernommen und wird dich betreuen.",
            color=Color.green(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await interaction.response.send_message(embed=embed)

        # Notify Ticket User
        if await guild_config.notify_on_claim():
            ticket_data = await guild_config.tickets()
            user_id = ticket_data.get(str(channel_id), {}).get("user_id")
            if user_id:
                member = guild.get_member(user_id)
                if member:
                    try:
                        dm_embed = Embed(
                            title="👋 Dein Ticket wurde übernommen",
                            description=f"Ein Supporter kümmert sich nun um dein Ticket auf **{guild.name}**.",
                            color=Color.green(),
                        )
                        await member.send(embed=dm_embed)
                    except:
                        pass

        await self.log_event(guild, "ticket_claim", {"user": user, "channel_id": channel_id})

    # ==================== TRANSCRIPT SYSTEM ====================

    async def generate_transcript(self, interaction: Interaction, channel_id: int):
        """Generiert und sendet Transkript"""
        guild = interaction.guild
        channel = guild.get_channel(channel_id)

        if not channel:
            await interaction.response.send_message(
                "❌ Channel nicht gefunden.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        messages = []
        async for msg in channel.history(limit=None, oldest_first=True):
            messages.append(msg)

        if not messages:
            await interaction.followup.send(
                "❌ Keine Nachrichten im Channel gefunden.",
                ephemeral=True,
            )
            return

        transcript_lines = [
            f"Ticket Transkript - {channel.name}",
            f"Server: {guild.name}",
            f"Erstellt: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
            "=" * 50,
            "",
        ]

        for msg in messages:
            timestamp = msg.created_at.strftime("%d.%m.%Y %H:%M:%S")
            content = msg.content or "[Kein Text]"
            transcript_lines.append(f"[{timestamp}] {msg.author}: {content}")

        transcript_content = "\n".join(transcript_lines)

        file = discord.File(
            fp=transcript_content.encode("utf-8"),
            filename=f"transcript_{channel.name}.txt",
        )

        await interaction.followup.send(file=file, ephemeral=True)

    # ==================== FEEDBACK SYSTEM ====================

    async def request_feedback(self, user: Member, ticket_id: str):
        """Fordert Feedback vom User an"""
        try:
            embed = Embed(
                title="⭐ Ticket-Feedback",
                description="Dein Ticket wurde geschlossen. Bitte bewerte deine Erfahrung.",
                color=Color.gold(),
            )
            view = FeedbackView(self, ticket_id, user.id)
            await user.send(embed=embed, view=view)
        except:
            pass

    async def save_feedback(
        self,
        interaction: Interaction,
        ticket_id: str,
        user_id: int,
        rating: int,
        comment: Optional[str],
    ):
        """Speichert Feedback"""
        feedback_data = {
            "ticket_id": ticket_id,
            "user_id": user_id,
            "rating": rating,
            "comment": comment,
            "timestamp": datetime.datetime.now().isoformat(),
        }

        async with self.config.user_from_id(user_id).feedback() as feedback:
            feedback.append(feedback_data)

        await interaction.response.send_message(
            f"✅ Danke für dein Feedback! Bewertung: {'⭐' * rating}",
            ephemeral=True,
        )

    # ==================== HELPER FUNKTIONEN ====================

    async def get_user_open_tickets(self, guild: discord.Guild, user_id: int) -> List[Dict]:
        """Gibt alle offenen Tickets eines Users zurück"""
        tickets = await self.config.guild(guild).tickets()
        return [
            ticket
            for ticket in tickets.values()
            if ticket.get("user_id") == user_id and ticket.get("status") == "open"
        ]

    async def log_event(self, guild: discord.Guild, event_type: str, data: Dict):
        """Loggt ein Event"""
        log_channel_id = await self.config.guild(guild).log_channel()
        if not log_channel_id:
            return

        log_channel = guild.get_channel(log_channel_id)
        if not log_channel:
            return

        embed = Embed(
            title=f"📋 Ticket Log: {event_type}",
            color=Color.blue(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )

        for key, value in data.items():
            if isinstance(value, (Member, User)):
                value = f"{value} ({value.id})"
            elif isinstance(value, TextChannel):
                value = f"{value.mention} ({value.id})"
            embed.add_field(name=key, value=str(value)[:1024], inline=False)

        try:
            await log_channel.send(embed=embed)
        except:
            pass

    # ==================== USER COMMANDS ====================

    @commands.hybrid_group(name="ticket", aliases=["tickets"])
    @commands.guild_only()
    async def ticket(self, ctx: commands.Context):
        """🎫 Ticket-Befehle"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @ticket.command(name="new", aliases=["erstellen", "create", "neu"])
    @commands.guild_only()
    async def ticket_new(self, ctx: commands.Context, kategorie: Optional[str] = None):
        """
        Erstellt ein neues Ticket

        Wenn keine Kategorie angegeben wird, wird die Standard-Kategorie verwendet.
        """
        guild = ctx.guild
        user = ctx.author

        categories = await self.config.guild(guild).categories()
        enabled_categories = {k: v for k, v in categories.items() if v.get("enabled", True)}

        if not enabled_categories:
            await ctx.send("❌ Es sind keine Ticket-Kategorien konfiguriert.")
            return

        if kategorie:
            if kategorie not in enabled_categories:
                await ctx.send(
                    f"❌ Kategorie '{kategorie}' nicht gefunden. Verfügbare Kategorien: {humanize_list(list(enabled_categories.keys()))}"
                )
                return
            category = kategorie
        else:
            category = await self.config.guild(guild).default_category()
            if category not in enabled_categories:
                category = list(enabled_categories.keys())[0]

        await self.create_ticket(guild, user, category)

    @ticket.command(name="close", aliases=["schliessen", "zu"])
    @commands.guild_only()
    async def ticket_close(self, ctx: commands.Context, *, grund: str = "Kein Grund angegeben"):
        """
        Schließt das aktuelle Ticket

        Du musst dich in einem Ticket-Channel befinden.
        """
        guild = ctx.guild
        channel = ctx.channel

        tickets = await self.config.guild(guild).tickets()
        if str(channel.id) not in tickets:
            await ctx.send("❌ Dies ist kein Ticket-Channel.")
            return

        ticket_data = tickets[str(channel.id)]

        if not await self.can_close_ticket(ctx.author, guild, ticket_data):
            await ctx.send("❌ Du hast keine Berechtigung, dieses Ticket zu schließen.")
            return

        await self.close_ticket_internal(guild, channel.id, grund, ctx.author)

        # Feedback anfordern
        if await self.config.guild(guild).feedback_enabled():
            user_id = ticket_data.get("user_id")
            if user_id:
                member = guild.get_member(user_id)
                if member:
                    await self.request_feedback(member, str(channel.id))

        await ctx.send("✅ Ticket wurde geschlossen. Der Channel wird in 10 Sekunden gelöscht.")

        await asyncio.sleep(10)
        try:
            await channel.delete(reason=f"Ticket geschlossen: {grund}")
        except:
            pass

    @ticket.command(name="add", aliases=["hinzufuegen"])
    @commands.guild_only()
    async def ticket_add(self, ctx: commands.Context, user: Member):
        """Fügt einen User zum aktuellen Ticket hinzu"""
        guild = ctx.guild
        channel = ctx.channel

        tickets = await self.config.guild(guild).tickets()
        if str(channel.id) not in tickets:
            await ctx.send("❌ Dies ist kein Ticket-Channel.")
            return

        support_roles = await self.config.guild(guild).support_roles()
        if not any(role.id in support_roles for role in ctx.author.roles):
            if not ctx.author.guild_permissions.administrator:
                await ctx.send("❌ Du hast keine Berechtigung, User hinzuzufügen.")
                return

        try:
            await channel.set_permissions(
                user,
                read_messages=True,
                send_messages=True,
                embed_links=True,
                attach_files=True,
            )
            await ctx.send(f"✅ {user.mention} wurde zum Ticket hinzugefügt.")
        except Exception as e:
            await ctx.send(f"❌ Fehler beim Hinzufügen: {e}")

    @ticket.command(name="remove", aliases=["entfernen"])
    @commands.guild_only()
    async def ticket_remove(self, ctx: commands.Context, user: Member):
        """Entfernt einen User vom aktuellen Ticket"""
        guild = ctx.guild
        channel = ctx.channel

        tickets = await self.config.guild(guild).tickets()
        if str(channel.id) not in tickets:
            await ctx.send("❌ Dies ist kein Ticket-Channel.")
            return

        support_roles = await self.config.guild(guild).support_roles()
        if not any(role.id in support_roles for role in ctx.author.roles):
            if not ctx.author.guild_permissions.administrator:
                await ctx.send("❌ Du hast keine Berechtigung, User zu entfernen.")
                return

        ticket_data = tickets[str(channel.id)]
        if ticket_data.get("user_id") == user.id:
            await ctx.send("❌ Der Ticket-Ersteller kann nicht entfernt werden.")
            return

        try:
            await channel.set_permissions(user, overwrite=None)
            await ctx.send(f"✅ {user.mention} wurde vom Ticket entfernt.")
        except Exception as e:
            await ctx.send(f"❌ Fehler beim Entfernen: {e}")

    @ticket.command(name="claim")
    @commands.guild_only()
    async def ticket_claim_cmd(self, ctx: commands.Context):
        """Claim das aktuelle Ticket"""
        guild = ctx.guild
        channel = ctx.channel

        if not await self.config.guild(guild).claim_enabled():
            await ctx.send("❌ Das Claim-System ist deaktiviert.")
            return

        tickets = await self.config.guild(guild).tickets()
        if str(channel.id) not in tickets:
            await ctx.send("❌ Dies ist kein Ticket-Channel.")
            return

        support_roles = await self.config.guild(guild).support_roles()
        if not any(role.id in support_roles for role in ctx.author.roles):
            if not ctx.author.guild_permissions.administrator:
                await ctx.send("❌ Du hast keine Berechtigung, Tickets zu claimen.")
                return

        ticket_data = tickets[str(channel.id)]
        if ticket_data.get("claim_by"):
            claimer_id = ticket_data["claim_by"]
            claimer = guild.get_member(claimer_id)
            await ctx.send(
                f"❌ Dieses Ticket wurde bereits von {claimer.mention if claimer else f'<@{claimer_id}>'} geclaimt."
            )
            return

        async with self.config.guild(guild).tickets() as tickets_data:
            tickets_data[str(channel.id)]["claim_by"] = ctx.author.id

        embed = Embed(
            title="✋ Ticket geclaimt",
            description=f"{ctx.author.mention} hat dieses Ticket übernommen.",
            color=Color.green(),
        )
        await ctx.send(embed=embed)

    @ticket.command(name="transcript")
    @commands.guild_only()
    async def ticket_transcript(self, ctx: commands.Context):
        """Generiert ein Transkript des aktuellen Tickets"""
        guild = ctx.guild
        channel = ctx.channel

        tickets = await self.config.guild(guild).tickets()
        if str(channel.id) not in tickets:
            await ctx.send("❌ Dies ist kein Ticket-Channel.")
            return

        async with ctx.typing():
            messages = []
            async for msg in channel.history(limit=None, oldest_first=True):
                messages.append(msg)

            if not messages:
                await ctx.send("❌ Keine Nachrichten im Channel gefunden.")
                return

            transcript_lines = [
                f"Ticket Transkript - {channel.name}",
                f"Server: {guild.name}",
                f"Erstellt: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
                "=" * 50,
                "",
            ]

            for msg in messages:
                timestamp = msg.created_at.strftime("%d.%m.%Y %H:%M:%S")
                transcript_lines.append(f"[{timestamp}] {msg.author}: {msg.content or '[Kein Text]'}")

            transcript_content = "\n".join(transcript_lines)

            file = discord.File(
                fp=transcript_content.encode("utf-8"),
                filename=f"transcript_{channel.name}.txt",
            )

            await ctx.send(file=file)

    @ticket.command(name="info")
    @commands.guild_only()
    async def ticket_info(self, ctx: commands.Context):
        """Zeigt Informationen zum aktuellen Ticket"""
        guild = ctx.guild
        channel = ctx.channel

        tickets = await self.config.guild(guild).tickets()
        if str(channel.id) not in tickets:
            await ctx.send("❌ Dies ist kein Ticket-Channel.")
            return

        ticket_data = tickets[str(channel.id)]
        user_id = ticket_data.get("user_id")
        user = guild.get_member(user_id) or await self.bot.fetch_user(user_id)

        created_at = datetime.datetime.fromisoformat(
            ticket_data.get("created_at", datetime.datetime.now().isoformat())
        )

        embed = Embed(
            title="📋 Ticket Informationen",
            color=Color(await self.config.guild(guild).embed_color()),
        )
        embed.add_field(name="Ersteller", value=f"{user.mention}\n{user} ({user.id})", inline=False)
        embed.add_field(name="Kategorie", value=ticket_data.get("category", "Unbekannt"), inline=True)
        embed.add_field(name="Status", value=ticket_data.get("status", "open"), inline=True)
        embed.add_field(name="Erstellt am", value=created_at.strftime("%d.%m.%Y %H:%M"), inline=True)

        if ticket_data.get("claim_by"):
            claimer_id = ticket_data["claim_by"]
            claimer = guild.get_member(claimer_id)
            embed.add_field(
                name="Geclaimt von",
                value=claimer.mention if claimer else f"<@{claimer_id}>",
                inline=True,
            )

        if ticket_data.get("status") == "closed":
            embed.add_field(name="Schließungsgrund", value=ticket_data.get("close_reason", "Unbekannt"), inline=False)

        await ctx.send(embed=embed)

    @ticket.command(name="stats", aliases=["statistiken"])
    @commands.guild_only()
    async def ticket_stats(self, ctx: commands.Context, user: Member = None):
        """Zeigt Ticket-Statistiken"""
        guild = ctx.guild
        tickets = await self.config.guild(guild).tickets()

        if user:
            user_tickets = [t for t in tickets.values() if t.get("user_id") == user.id]
            open_tickets = [t for t in user_tickets if t.get("status") == "open"]
            closed_tickets = [t for t in user_tickets if t.get("status") == "closed"]

            embed = Embed(title=f"📊 Ticket-Statistiken für {user}", color=Color.blue())
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="Erstellte Tickets", value=str(len(user_tickets)), inline=True)
            embed.add_field(name="Offene Tickets", value=str(len(open_tickets)), inline=True)
            embed.add_field(name="Geschlossene Tickets", value=str(len(closed_tickets)), inline=True)

            user_data = await self.config.user(user).all()
            feedback = user_data.get("feedback", [])
            if feedback:
                avg_rating = sum(f.get("rating", 0) for f in feedback) / len(feedback)
                embed.add_field(name="Durchschnittliche Bewertung", value=f"{avg_rating:.1f} ⭐", inline=True)
        else:
            total = len(tickets)
            open_tickets = len([t for t in tickets.values() if t.get("status") == "open"])
            closed_tickets = len([t for t in tickets.values() if t.get("status") == "closed"])

            categories = await self.config.guild(guild).categories()
            cat_stats = {}
            for t in tickets.values():
                cat = t.get("category", "Unbekannt")
                cat_stats[cat] = cat_stats.get(cat, 0) + 1

            embed = Embed(title="📊 Ticket-Statistiken", color=Color.blue())
            embed.add_field(name="Gesamt Tickets", value=str(total), inline=True)
            embed.add_field(name="Offene Tickets", value=str(open_tickets), inline=True)
            embed.add_field(name="Geschlossene Tickets", value=str(closed_tickets), inline=True)

            if cat_stats:
                cat_text = "\n".join(
                    [f"{k}: {v}" for k, v in sorted(cat_stats.items(), key=lambda x: x[1], reverse=True)]
                )
                embed.add_field(name="Nach Kategorie", value=cat_text, inline=False)

            panels = await self.config.guild(guild).panels()
            embed.add_field(name="Panels", value=str(len(panels)), inline=True)

        await ctx.send(embed=embed)

    # ==================== ADMIN COMMANDS ====================

    @commands.group(name="ticketset", aliases=["ticketsystem", "ticketsetup"])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def ticketset(self, ctx: commands.Context):
        """Ticket-System Einstellungen"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @ticketset.command(name="quicksetup", aliases=["schnellstart", "setup"])
    async def ticketset_quicksetup(self, ctx: commands.Context):
        """
        🚀 Schnelleinrichtung des Ticket-Systems

        Interaktiver Setup-Assistent für die Ersteinrichtung.
        """
        guild = ctx.guild
        
        # Prüfe ob Support-Rollen gesetzt sind
        support_roles = await self.config.guild(guild).support_roles()
        if not support_roles:
            # Versuche @Support Rolle zu finden
            support_role = discord.utils.get(guild.roles, name="Support")
            if support_role:
                await self.config.guild(guild).support_roles.set([support_role.id])
                await ctx.send(f"✅ Support-Rolle automatisch erkannt: {support_role.mention}")
            else:
                await ctx.send(
                    "⚠️ Keine Support-Rolle gefunden!\n"
                    "Erstelle eine Rolle namens 'Support' oder setze sie mit:\n"
                    f"`{ctx.prefix}ticketset supportrole @Rolle`"
                )
                return
        
        # Prüfe Kategorie
        ticket_category = await self.config.guild(guild).ticket_category()
        if not ticket_category:
            # Versuche Kategorie zu finden
            category = discord.utils.get(guild.categories, name="Tickets")
            if category:
                await self.config.guild(guild).ticket_category.set(category.id)
                await ctx.send(f"✅ Ticket-Kategorie automatisch erkannt: {category.name}")
            else:
                # Erstelle Kategorie
                try:
                    overwrites = {
                        guild.default_role: discord.PermissionOverwrite(read_messages=False),
                        guild.me: discord.PermissionOverwrite(
                            read_messages=True,
                            send_messages=True,
                            manage_channels=True,
                        ),
                    }
                    # Support-Rollen hinzufügen
                    for role_id in support_roles:
                        role = guild.get_role(role_id)
                        if role:
                            overwrites[role] = discord.PermissionOverwrite(
                                read_messages=True,
                                send_messages=True,
                            )
                    
                    category = await guild.create_category(
                        "Tickets",
                        overwrites=overwrites,
                        reason="Ticket-System Setup"
                    )
                    await self.config.guild(guild).ticket_category.set(category.id)
                    await ctx.send(f"✅ Ticket-Kategorie erstellt: {category.name}")
                except Exception as e:
                    await ctx.send(f"❌ Konnte Kategorie nicht erstellen: {e}")
        
        # Zeige Zusammenfassung
        embed = Embed(
            title="✅ Ticket-System Einrichtung abgeschlossen!",
            description="Dein Ticket-System ist bereit. Erstelle jetzt ein Panel:",
            color=Color.green(),
        )
        embed.add_field(
            name="Panel erstellen",
            value=f"`{ctx.prefix}ticketset panel create`",
            inline=False,
        )
        embed.add_field(
            name="Einstellungen ansehen",
            value=f"`{ctx.prefix}ticketset showsettings`",
            inline=False,
        )
        embed.add_field(
            name="Hilfe",
            value=f"`{ctx.prefix}help ticket`\n`{ctx.prefix}help ticketset`",
            inline=False,
        )
        
        await ctx.send(embed=embed)

    @ticketset.command(name="category", aliases=["kategorie"])
    async def ticketset_category(self, ctx: commands.Context, category: CategoryChannel = None):
        """Setzt die Kategorie, in der Tickets erstellt werden"""
        if category is None:
            await self.config.guild(ctx.guild).ticket_category.clear()
            await ctx.send("✅ Ticket-Kategorie wurde entfernt.")
        else:
            await self.config.guild(ctx.guild).ticket_category.set(category.id)
            await ctx.send(f"✅ Ticket-Kategorie wurde auf {category.mention} gesetzt.")

    @ticketset.command(name="supportrole", aliases=["supportrolle"])
    async def ticketset_supportrole(self, ctx: commands.Context, *roles: Role):
        """Setzt die Support-Rollen"""
        if not roles:
            await self.config.guild(ctx.guild).support_roles.clear()
            await ctx.send("✅ Support-Rollen wurden entfernt.")
        else:
            role_ids = [r.id for r in roles]
            await self.config.guild(ctx.guild).support_roles.set(role_ids)
            await ctx.send(f"✅ Support-Rollen gesetzt: {humanize_list([r.mention for r in roles])}")

    @ticketset.command(name="adminrole", aliases=["adminrolle"])
    async def ticketset_adminrole(self, ctx: commands.Context, *roles: Role):
        """Setzt die Admin-Rollen für das Ticket-System"""
        if not roles:
            await self.config.guild(ctx.guild).admin_roles.clear()
            await ctx.send("✅ Admin-Rollen wurden entfernt.")
        else:
            role_ids = [r.id for r in roles]
            await self.config.guild(ctx.guild).admin_roles.set(role_ids)
            await ctx.send(f"✅ Admin-Rollen gesetzt: {humanize_list([r.mention for r in roles])}")

    @ticketset.command(name="limit")
    async def ticketset_limit(self, ctx: commands.Context, limit: int):
        """Setzt das Maximum an offenen Tickets pro User (Standard: 3)"""
        if limit < 1:
            await ctx.send("❌ Das Limit muss mindestens 1 sein.")
            return

        await self.config.guild(ctx.guild).ticket_limit.set(limit)
        await ctx.send(f"✅ Ticket-Limit auf {limit} gesetzt.")

    @ticketset.command(name="logchannel", aliases=["log"])
    async def ticketset_logchannel(self, ctx: commands.Context, channel: TextChannel = None):
        """Setzt den Log-Channel für Ticket-Events"""
        if channel is None:
            await self.config.guild(ctx.guild).log_channel.clear()
            await ctx.send("✅ Log-Channel wurde entfernt.")
        else:
            await self.config.guild(ctx.guild).log_channel.set(channel.id)
            await ctx.send(f"✅ Log-Channel auf {channel.mention} gesetzt.")

    @ticketset.command(name="autoclose")
    async def ticketset_autoclose(self, ctx: commands.Context, stunden: int, warnung: int = 24):
        """
        Setzt die Auto-Close Zeit in Stunden (0 zum Deaktivieren)

        Beispiel: `[p]ticketset autoclose 72 24` = Auto-Close nach 72h, Warnung 24h vorher
        """
        if stunden < 0:
            await ctx.send("❌ Die Zeit muss positiv sein.")
            return

        if stunden == 0:
            await self.config.guild(ctx.guild).auto_close_hours.set(0)
            await ctx.send("✅ Auto-Close deaktiviert.")
        else:
            await self.config.guild(ctx.guild).auto_close_hours.set(stunden)
            await self.config.guild(ctx.guild).auto_close_warning_hours.set(warnung)
            await ctx.send(f"✅ Auto-Close nach {stunden}h gesetzt, Warnung {warnung}h vorher.")

    @ticketset.command(name="color", aliases=["farbe"])
    async def ticketset_color(self, ctx: commands.Context, color: str):
        """Setzt die Farbe für Ticket-Embeds (Hex-Code, z.B. #3498db)"""
        try:
            if color.startswith("#"):
                color_int = int(color[1:], 16)
            else:
                color_int = int(color)
            await self.config.guild(ctx.guild).embed_color.set(color_int)
            embed = Embed(title="Farbe gesetzt", color=Color(color_int))
            await ctx.send("✅ Farbe gesetzt:", embed=embed)
        except ValueError:
            await ctx.send("❌ Ungültige Farbe. Verwende einen Hex-Code (z.B. #3498db).")

    @ticketset.command(name="dm")
    async def ticketset_dm(self, ctx: commands.Context, aktiviert: bool):
        """Aktiviert/deaktiviert DM-Benachrichtigungen bei Ticket-Erstellung"""
        await self.config.guild(ctx.guild).dm_notifications.set(aktiviert)
        status = "aktiviert" if aktiviert else "deaktiviert"
        await ctx.send(f"✅ DM-Benachrichtigungen {status}.")

    @ticketset.command(name="claim")
    async def ticketset_claim(self, ctx: commands.Context, aktiviert: bool):
        """Aktiviert/deaktiviert das Claim-System"""
        await self.config.guild(ctx.guild).claim_enabled.set(aktiviert)
        status = "aktiviert" if aktiviert else "deaktiviert"
        await ctx.send(f"✅ Claim-System {status}.")

    @ticketset.command(name="feedback")
    async def ticketset_feedback(self, ctx: commands.Context, aktiviert: bool):
        """Aktiviert/deaktiviert das Feedback-System"""
        await self.config.guild(ctx.guild).feedback_enabled.set(aktiviert)
        status = "aktiviert" if aktiviert else "deaktiviert"
        await ctx.send(f"✅ Feedback-System {status}.")

    @ticketset.command(name="ping")
    async def ticketset_ping(self, ctx: commands.Context, aktiviert: bool):
        """Aktiviert/deaktiviert das Ping beim Ticket-Erstellen"""
        await self.config.guild(ctx.guild).ping_on_create.set(aktiviert)
        status = "aktiviert" if aktiviert else "deaktiviert"
        await ctx.send(f"✅ Ping beim Erstellen {status}.")

    @ticketset.command(name="pingrole")
    async def ticketset_pingrole(self, ctx: commands.Context, role: Role = None):
        """Setzt die Rolle, die bei neuen Tickets gepingt wird"""
        if role is None:
            await self.config.guild(ctx.guild).ping_role.clear()
            await ctx.send("✅ Ping-Rolle entfernt.")
        else:
            await self.config.guild(ctx.guild).ping_role.set(role.id)
            await ctx.send(f"✅ Ping-Rolle auf {role.mention} gesetzt.")

    @ticketset.command(name="showsettings", aliases=["einstellungen", "settings"])
    async def ticketset_showsettings(self, ctx: commands.Context):
        """Zeigt die aktuellen Einstellungen"""
        guild_data = await self.config.guild(ctx.guild).all()

        embed = Embed(
            title="📋 Ticket-System Einstellungen",
            color=Color(guild_data.get("embed_color", 0x3498db)),
        )

        cat_id = guild_data.get("ticket_category")
        cat = ctx.guild.get_channel(cat_id) if cat_id else None
        embed.add_field(name="Ticket-Kategorie", value=cat.mention if cat else "Nicht gesetzt", inline=True)

        support_ids = guild_data.get("support_roles", [])
        support_roles = [ctx.guild.get_role(r) for r in support_ids if ctx.guild.get_role(r)]
        embed.add_field(
            name="Support-Rollen",
            value=humanize_list([r.mention for r in support_roles]) if support_roles else "Keine",
            inline=False,
        )

        embed.add_field(name="Ticket-Limit", value=str(guild_data.get("ticket_limit", 3)), inline=True)
        embed.add_field(name="Auto-Close", value=f"{guild_data.get('auto_close_hours', 72)}h", inline=True)

        switches = [
            f"Claim-System: {'✅' if guild_data.get('claim_enabled') else '❌'}",
            f"Feedback: {'✅' if guild_data.get('feedback_enabled') else '❌'}",
            f"DM-Benachrichtigung: {'✅' if guild_data.get('dm_notifications') else '❌'}",
            f"Ping beim Erstellen: {'✅' if guild_data.get('ping_on_create') else '❌'}",
        ]
        embed.add_field(name="Funktionen", value="\n".join(switches), inline=False)

        await ctx.send(embed=embed)

    # ==================== KATEGORIE VERWALTUNG ====================

    @ticketset.group(name="category", aliases=["kategorien"])
    async def ticketset_category_group(self, ctx: commands.Context):
        """Verwaltung der Ticket-Kategorien"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @ticketset_category_group.command(name="add", aliases=["hinzufuegen"])
    async def category_add(
        self,
        ctx: commands.Context,
        name: str,
        emoji: str = "🎫",
        *,
        beschreibung: str = "Keine Beschreibung",
    ):
        """Fügt eine neue Ticket-Kategorie hinzu"""
        categories = await self.config.guild(ctx.guild).categories()

        if name in categories:
            await ctx.send(f"❌ Kategorie '{name}' existiert bereits.")
            return

        categories[name] = {
            "emoji": emoji,
            "description": beschreibung,
            "color": 0x3498db,
            "enabled": True,
        }

        await self.config.guild(ctx.guild).categories.set(categories)
        await ctx.send(f"✅ Kategorie '{name}' hinzugefügt.")

    @ticketset_category_group.command(name="remove", aliases=["entfernen", "delete"])
    async def category_remove(self, ctx: commands.Context, name: str):
        """Entfernt eine Ticket-Kategorie"""
        categories = await self.config.guild(ctx.guild).categories()

        if name not in categories:
            await ctx.send(f"❌ Kategorie '{name}' nicht gefunden.")
            return

        del categories[name]
        await self.config.guild(ctx.guild).categories.set(categories)
        await ctx.send(f"✅ Kategorie '{name}' entfernt.")

    @ticketset_category_group.command(name="toggle", aliases=["umschalten"])
    async def category_toggle(self, ctx: commands.Context, name: str):
        """Aktiviert oder deaktiviert eine Kategorie"""
        categories = await self.config.guild(ctx.guild).categories()

        if name not in categories:
            await ctx.send(f"❌ Kategorie '{name}' nicht gefunden.")
            return

        categories[name]["enabled"] = not categories[name].get("enabled", True)
        await self.config.guild(ctx.guild).categories.set(categories)

        status = "aktiviert" if categories[name]["enabled"] else "deaktiviert"
        await ctx.send(f"✅ Kategorie '{name}' {status}.")

    @ticketset_category_group.command(name="list", aliases=["liste"])
    async def category_list(self, ctx: commands.Context):
        """Listet alle Ticket-Kategorien auf"""
        categories = await self.config.guild(ctx.guild).categories()

        if not categories:
            await ctx.send("Keine Kategorien konfiguriert.")
            return

        embed = Embed(
            title="📋 Ticket-Kategorien",
            color=Color(await self.config.guild(ctx.guild).embed_color()),
        )

        for name, data in categories.items():
            status = "✅" if data.get("enabled", True) else "❌"
            emoji = data.get("emoji", "🎫")
            desc = data.get("description", "Keine Beschreibung")
            embed.add_field(name=f"{status} {emoji} {name}", value=desc, inline=False)

        await ctx.send(embed=embed)

    # ==================== PANEL VERWALTUNG ====================

    @ticketset.group(name="panel")
    async def ticketset_panel(self, ctx: commands.Context):
        """Verwaltung der Ticket-Panels"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @ticketset_panel.command(name="create", aliases=["erstellen", "send"])
    async def panel_create(
        self,
        ctx: commands.Context,
        channel: TextChannel = None,
        stil: str = "buttons",
        *,
        titel: str = "🎫 Ticket-System",
    ):
        """
        Erstellt ein Ticket-Panel

        Stil: buttons (Buttons) oder dropdown (Dropdown-Menü)
        """
        channel = channel or ctx.channel
        guild_data = await self.config.guild(ctx.guild).all()
        categories = guild_data.get("categories", {})

        if not categories:
            await ctx.send("❌ Keine Kategorien konfiguriert. Erstelle zuerst Kategorien.")
            return

        enabled_categories = {k: v for k, v in categories.items() if v.get("enabled", True)}
        if not enabled_categories:
            await ctx.send("❌ Keine aktivierten Kategorien.")
            return

        embed = Embed(
            title=titel,
            description="Wähle eine Kategorie unten, um ein Ticket zu erstellen.",
            color=Color(guild_data.get("embed_color", 0x3498db)),
        )

        for name, data in enabled_categories.items():
            emoji = data.get("emoji", "🎫")
            desc = data.get("description", "Keine Beschreibung")
            embed.add_field(name=f"{emoji} {name}", value=desc, inline=False)

        if stil.lower() == "dropdown":
            view = TicketPanelDropdownView(self, enabled_categories)
            panel_style = "dropdown"
        else:
            view = TicketPanelView(
                self, enabled_categories, guild_data.get("button_style", "primary")
            )
            panel_style = "buttons"

        message = await channel.send(embed=embed, view=view)

        panel_id = str(message.id)
        async with self.config.guild(ctx.guild).panels() as panels:
            panels[panel_id] = {
                "channel_id": channel.id,
                "message_id": message.id,
                "style": panel_style,
                "created_at": datetime.datetime.now().isoformat(),
            }

        await ctx.send(f"✅ Panel erstellt in {channel.mention}")

    @ticketset_panel.command(name="delete", aliases=["entfernen", "remove"])
    async def panel_delete(self, ctx: commands.Context, message_id: str):
        """Löscht ein Panel"""
        panels = await self.config.guild(ctx.guild).panels()

        if message_id not in panels:
            await ctx.send("❌ Panel nicht gefunden.")
            return

        panel_data = panels[message_id]
        channel = ctx.guild.get_channel(panel_data["channel_id"])

        if channel:
            try:
                message = await channel.fetch_message(int(message_id))
                await message.delete()
            except:
                pass

        del panels[message_id]
        await self.config.guild(ctx.guild).panels.set(panels)
        await ctx.send("✅ Panel gelöscht.")

    @ticketset_panel.command(name="list", aliases=["liste"])
    async def panel_list(self, ctx: commands.Context):
        """Listet alle Panels auf"""
        panels = await self.config.guild(ctx.guild).panels()

        if not panels:
            await ctx.send("Keine Panels vorhanden.")
            return

        embed = Embed(title="📋 Ticket-Panels", color=Color.blue())

        for panel_id, data in panels.items():
            channel = ctx.guild.get_channel(data.get("channel_id"))
            channel_name = channel.mention if channel else "Unbekannt"
            style = data.get("style", "buttons")
            embed.add_field(
                name=f"Panel {panel_id[:8]}...",
                value=f"Channel: {channel_name}\nStil: {style}",
                inline=False,
            )

        await ctx.send(embed=embed)

    # ==================== BLACKLIST ====================

    @ticketset.group(name="blacklist")
    async def ticketset_blacklist(self, ctx: commands.Context):
        """Blacklist-Verwaltung"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @ticketset_blacklist.command(name="add")
    async def blacklist_add(self, ctx: commands.Context, user: Member):
        """Fügt einen User zur Blacklist hinzu"""
        blacklist = await self.config.guild(ctx.guild).blacklist()

        if user.id in blacklist:
            await ctx.send("❌ User ist bereits auf der Blacklist.")
            return

        blacklist.append(user.id)
        await self.config.guild(ctx.guild).blacklist.set(blacklist)
        await ctx.send(f"✅ {user.mention} wurde zur Blacklist hinzugefügt.")

    @ticketset_blacklist.command(name="remove")
    async def blacklist_remove(self, ctx: commands.Context, user: Member):
        """Entfernt einen User von der Blacklist"""
        blacklist = await self.config.guild(ctx.guild).blacklist()

        if user.id not in blacklist:
            await ctx.send("❌ User ist nicht auf der Blacklist.")
            return

        blacklist.remove(user.id)
        await self.config.guild(ctx.guild).blacklist.set(blacklist)
        await ctx.send(f"✅ {user.mention} wurde von der Blacklist entfernt.")

    @ticketset_blacklist.command(name="list")
    async def blacklist_list(self, ctx: commands.Context):
        """Zeigt die Blacklist"""
        blacklist = await self.config.guild(ctx.guild).blacklist()

        if not blacklist:
            await ctx.send("Die Blacklist ist leer.")
            return

        users = []
        for user_id in blacklist:
            user = ctx.guild.get_member(user_id)
            users.append(user.mention if user else f"<@{user_id}>")

        embed = Embed(title="🚫 Blacklist", description="\n".join(users))
        await ctx.send(embed=embed)

    # ==================== RESET ====================

    @ticketset.command(name="reset")
    async def ticketset_reset(self, ctx: commands.Context, bestaetigung: str = None):
        """
        Setzt alle Ticket-Einstellungen zurück

        WARNUNG: Dies löscht alle Daten!
        Verwendung: `[p]ticketset reset bestätigen`
        """
        if bestaetigung != "bestätigen":
            await ctx.send("⚠️ Um alle Einstellungen zurückzusetzen, verwende:\n`[p]ticketset reset bestätigen`")
            return

        await self.config.guild(ctx.guild).clear()
        await ctx.send("✅ Alle Ticket-Einstellungen wurden zurückgesetzt.")
