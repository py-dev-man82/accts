# handlers/backup.py

import os
import shutil
import tempfile
import logging
import hashlib
import requests
from zipfile import ZipFile
from datetime import datetime, timedelta
import asyncio

from telegram import (
    Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    Application,
    CallbackQueryHandler,
)

from handlers.utils import require_unlock
import config

BACKUP_FILES = ["data/db.json", "data/kdf_salt.bin"]
BACKUP_TMP = "data/telegram_backup.zip"
HASH_FILE = "backup.sha256"
RETENTION_DIR = "data/backups"
MAX_BACKUPS = 5
ADMIN_TELEGRAM_ID = getattr(config, "ADMIN_TELEGRAM_ID", None)
RESTORE_WAITING = range(1)

# ──────────── Nextcloud WebDAV Upload (optional) ─────────────
def upload_to_nextcloud(local_file_path, remote_filename):
    url = getattr(config, "NEXTCLOUD_URL", "").strip()
    user = getattr(config, "NEXTCLOUD_USER", "").strip()
    pw = getattr(config, "NEXTCLOUD_PASS", "").strip()
    if not url or not user or not pw:
        logging.info("Nextcloud upload skipped: credentials not set.")
        return None
    try:
        with open(local_file_path, "rb") as fin:
            r = requests.put(
                url.rstrip("/") + "/" + remote_filename,
                data=fin,
                auth=(user, pw),
                timeout=120
            )
        if r.status_code in (200, 201, 204):
            logging.info(f"Uploaded to Nextcloud: {remote_filename}")
            return True
        else:
            logging.error(f"Nextcloud upload failed: {r.status_code} {r.text}")
            return False
    except Exception as e:
        logging.error(f"Nextcloud upload error: {e}")
        return False

def is_admin(update: Update) -> bool:
    user = update.effective_user
    return user and user.id == ADMIN_TELEGRAM_ID

def _reply(update: Update, *args, **kwargs):
    if hasattr(update, "message") and update.message:
        return update.message.reply_text(*args, **kwargs)
    elif hasattr(update, "callback_query") and update.callback_query:
        return update.callback_query.message.reply_text(*args, **kwargs)

def _reply_document(update: Update, *args, **kwargs):
    if hasattr(update, "message") and update.message:
        return update.message.reply_document(*args, **kwargs)
    elif hasattr(update, "callback_query") and update.callback_query:
        return update.callback_query.message.reply_document(*args, **kwargs)

def compute_hashes(files):
    lines = []
    for f in files:
        h = hashlib.sha256()
        with open(f, "rb") as fin:
            while chunk := fin.read(4096):
                h.update(chunk)
        lines.append(f"SHA256({os.path.basename(f)})= {h.hexdigest()}")
    return "\n".join(lines)

def check_hashes(tmpdir, hashfile):
    hashes = {}
    with open(hashfile, "r") as hin:
        for line in hin:
            if line.startswith("SHA256("):
                fname, hval = line.strip().split(")=", 1)
                fname = fname[7:]
                hashes[fname.strip()] = hval.strip()
    for fname, expected in hashes.items():
        path = os.path.join(tmpdir, fname)
        if not os.path.exists(path):
            return False, f"Missing file {fname}"
        h = hashlib.sha256()
        with open(path, "rb") as fin:
            while chunk := fin.read(4096):
                h.update(chunk)
        if h.hexdigest() != expected:
            return False, f"Hash mismatch for {fname}"
    return True, "OK"

def enforce_retention():
    os.makedirs(RETENTION_DIR, exist_ok=True)
    backups = sorted(
        [f for f in os.listdir(RETENTION_DIR) if f.endswith('.zip')],
        key=lambda x: os.path.getmtime(os.path.join(RETENTION_DIR, x))
    )
    if len(backups) > MAX_BACKUPS:
        for fname in backups[:-MAX_BACKUPS]:
            try:
                os.remove(os.path.join(RETENTION_DIR, fname))
            except Exception:
                pass

def make_backup_file(suffix=""):
    os.makedirs(RETENTION_DIR, exist_ok=True)
    hash_txt = compute_hashes(BACKUP_FILES)
    with open(HASH_FILE, "w") as hout:
        hout.write(hash_txt)

    with ZipFile(BACKUP_TMP, "w") as zf:
        for fname in BACKUP_FILES:
            if os.path.exists(fname):
                zf.write(fname, arcname=os.path.basename(fname))
        zf.write(HASH_FILE, arcname=HASH_FILE)
    os.remove(HASH_FILE)

    nowtag = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_copy_path = os.path.join(RETENTION_DIR, f"backup-{nowtag}{suffix}.zip")
    shutil.copy(BACKUP_TMP, backup_copy_path)
    enforce_retention()
    return backup_copy_path

# ──────────────────────────────
# Manual backup (command or button)
@require_unlock
async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await _reply(update, "❌ You are not authorized to use this command.")
        return
    backup_file = make_backup_file()
    await _reply_document(
        update,
        document=InputFile(backup_file),
        filename=os.path.basename(backup_file),
        caption="🗄️ Encrypted DB backup (with SHA256 integrity check). Keep safe!"
    )
    if os.path.exists(BACKUP_TMP):
        os.remove(BACKUP_TMP)

# ──────────────────────────────
# Restore (upload backup zip)
async def restore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await _reply(update, "❌ You are not authorized to use this command.")
        return ConversationHandler.END
    await _reply(
        update,
        "⚠️ Upload your backup archive (.zip) with DB, salt, and hash file. "
        "This will OVERWRITE your current DB if hashes match.\n"
        "Type /cancel to abort."
    )
    return RESTORE_WAITING

async def restore_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("❌ You are not authorized to restore.")
        return ConversationHandler.END

    doc = update.message.document
    if not doc or not doc.file_name.endswith(".zip"):
        await update.message.reply_text("❌ Please upload a .zip backup archive.")
        return RESTORE_WAITING

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, doc.file_name)
        await doc.get_file().download_to_drive(file_path)
        try:
            with ZipFile(file_path, "r") as zf:
                names = zf.namelist()
                if not all(f in names for f in ["db.json", "kdf_salt.bin", "backup.sha256"]):
                    await update.message.reply_text("❌ Archive missing db.json, kdf_salt.bin, or backup.sha256.")
                    return RESTORE_WAITING
                zf.extract("db.json", path=tmpdir)
                zf.extract("kdf_salt.bin", path=tmpdir)
                zf.extract("backup.sha256", path=tmpdir)
            ok, msg = check_hashes(tmpdir, os.path.join(tmpdir, "backup.sha256"))
            if not ok:
                await update.message.reply_text(f"❌ Hash check failed: {msg}. Restore aborted.")
                return ConversationHandler.END
            shutil.move(os.path.join(tmpdir, "db.json"), "data/db.json")
            shutil.move(os.path.join(tmpdir, "kdf_salt.bin"), "data/kdf_salt.bin")
        except Exception as e:
            logging.error(f"Restore failed: {e}")
            await update.message.reply_text(f"❌ Restore failed: {e}")
            return ConversationHandler.END

    await update.message.reply_text(
        "✅ Restore complete and hash verified! Please /unlock with your PIN."
    )
    return ConversationHandler.END

async def restore_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if hasattr(update, "message") and update.message:
        await update.message.reply_text("❌ Restore cancelled.")
    elif hasattr(update, "callback_query") and update.callback_query:
        await update.callback_query.message.reply_text("❌ Restore cancelled.")
    return ConversationHandler.END

# ──────────────────────────────
# List and download backups + restore from server
async def backups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await _reply(update, "❌ Not authorized.")
        return
    backups = sorted(
        [f for f in os.listdir(RETENTION_DIR) if f.endswith('.zip')],
        key=lambda x: os.path.getmtime(os.path.join(RETENTION_DIR, x)),
        reverse=True
    )
    if not backups:
        await _reply(update, "No backups found.")
        return
    buttons = []
    for fname in backups:
        buttons.append([
            InlineKeyboardButton(f"Download: {fname}", callback_data=f"downloadbackup_{fname}"),
            InlineKeyboardButton("🔄 Restore", callback_data=f"restorefile_{fname}")
        ])
    reply_markup = InlineKeyboardMarkup(buttons)
    await _reply(
        update,
        "Available backups:\nSelect to download or restore (rollback) a backup.",
        reply_markup=reply_markup
    )

async def backups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.callback_query.answer("Not authorized.", show_alert=True)
        return
    data = update.callback_query.data
    if data.startswith("downloadbackup_"):
        fname = data[len("downloadbackup_") :]
        path = os.path.join(RETENTION_DIR, fname)
        if os.path.exists(path):
            await update.callback_query.answer()
            await update.callback_query.message.reply_document(
                document=InputFile(path),
                filename=fname,
                caption="🗄️ Requested backup file."
            )
        else:
            await update.callback_query.answer("File not found.", show_alert=True)
    elif data.startswith("restorefile_"):
        fname = data[len("restorefile_") :]
        context.user_data["selected_restore"] = fname
        await update.callback_query.message.reply_text(
            f"⚠️ Are you sure you want to restore from <b>{fname}</b>? This will OVERWRITE the current database.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Yes, Restore", callback_data="restorefile_confirm")],
                [InlineKeyboardButton("❌ Cancel", callback_data="restorefile_cancel")],
            ])
        )
    elif data == "restorefile_confirm":
        fname = context.user_data.get("selected_restore")
        if not fname:
            await update.callback_query.answer("No file selected.", show_alert=True)
            return
        full_path = os.path.join(RETENTION_DIR, fname)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                with ZipFile(full_path, "r") as zf:
                    names = zf.namelist()
                    if not all(f in names for f in ["db.json", "kdf_salt.bin", "backup.sha256"]):
                        await update.callback_query.message.reply_text("❌ Archive missing required files.")
                        return
                    zf.extract("db.json", path=tmpdir)
                    zf.extract("kdf_salt.bin", path=tmpdir)
                    zf.extract("backup.sha256", path=tmpdir)
                ok, msg = check_hashes(tmpdir, os.path.join(tmpdir, "backup.sha256"))
                if not ok:
                    await update.callback_query.message.reply_text(f"❌ Hash check failed: {msg}. Restore aborted.")
                    return
                shutil.move(os.path.join(tmpdir, "db.json"), "data/db.json")
                shutil.move(os.path.join(tmpdir, "kdf_salt.bin"), "data/kdf_salt.bin")
            await update.callback_query.message.reply_text(
                f"✅ Restore from <b>{fname}</b> complete and hash verified! Please /unlock with your PIN.",
                parse_mode="HTML"
            )
        except Exception as e:
            await update.callback_query.message.reply_text(f"❌ Restore failed: {e}")
    elif data == "restorefile_cancel":
        await update.callback_query.message.reply_text("Restore cancelled.")

# ──────────────────────────────
# Weekly Autobackup Task (notifies admins, uploads to Nextcloud if set)
async def autobackup_task(app: Application):
    while True:
        now = datetime.now()
        # Run every Monday at 01:00 (customize as needed)
        next_run = (now + timedelta(days=(7 - now.weekday()))).replace(hour=1, minute=0, second=0, microsecond=0)
        wait_seconds = (next_run - now).total_seconds()
        if wait_seconds < 0:
            wait_seconds += 7 * 24 * 3600
        await asyncio.sleep(wait_seconds)
        try:
            backup_file = make_backup_file("-autobackup")
            logging.info(f"Weekly auto-backup created: {backup_file}")
            cloud_result = upload_to_nextcloud(
                backup_file,
                os.path.basename(backup_file)
            )
            if cloud_result is True:
                msg = f"✅ Weekly auto-backup uploaded to Nextcloud: <code>{os.path.basename(backup_file)}</code>"
            elif cloud_result is False:
                msg = f"⚠️ Weekly backup upload to Nextcloud FAILED!"
            else:
                msg = f"✅ Weekly auto-backup saved locally (Nextcloud not configured)."
            # Only send to single admin:
            if ADMIN_TELEGRAM_ID:
                try:
                    await app.bot.send_message(
                        ADMIN_TELEGRAM_ID,
                        msg,
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
        except Exception as e:
            logging.error(f"Weekly autobackup failed: {e}")
        await asyncio.sleep(1)

# ──────────────────────────────
def register_backup_handlers(app: Application):
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("backups", backups_command))
    restore_conv = ConversationHandler(
        entry_points=[CommandHandler("restore", restore_command)],
        states={
            RESTORE_WAITING: [MessageHandler(filters.Document.ALL & ~filters.COMMAND, restore_receive)],
        },
        fallbacks=[CommandHandler("cancel", restore_cancel)],
        name="restore_conv",
    )
    app.add_handler(restore_conv)
    app.add_handler(CallbackQueryHandler(backups_callback, pattern="^(downloadbackup_|restorefile_|restorefile_confirm|restorefile_cancel)"))
    app.create_task(autobackup_task(app))
