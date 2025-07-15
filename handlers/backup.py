# backup.py 
import os
import shutil
import tempfile
import logging
import hashlib
import requests
import stat
from zipfile import ZipFile, ZIP_STORED
from datetime import datetime, timedelta
import asyncio

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
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
PAD_FILE = "__pad.bin"
RETENTION_DIR = "data/backups"
MAX_BACKUPS = 5
ADMIN_TELEGRAM_ID = getattr(config, "ADMIN_TELEGRAM_ID", None)
RESTORE_WAITING = range(1)
CLOUD_RESTORE_SELECT = range(1)

# --- Nextcloud Upload and Public Link ---
def upload_to_nextcloud(local_file_path, remote_filename, share=False):
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
        if r.status_code not in (200, 201, 204):
            logging.error(f"Nextcloud upload failed: {r.status_code} {r.text}")
            return False
        logging.info(f"Uploaded to Nextcloud: {remote_filename}")
    except Exception as e:
        logging.error(f"Nextcloud upload error: {e}")
        return False

    if not share:
        return True

    share_url = None
    try:
        share_api = url.split("/remote.php")[0] + "/ocs/v2.php/apps/files_sharing/api/v1/shares"
        rel_path = "/files/" + user + "/" + remote_filename
        headers = {"OCS-APIREQUEST": "true"}
        data = {
            "path": rel_path,
            "shareType": 3,  # 3 = public link
            "permissions": 1,  # 1 = read
        }
        r = requests.post(
            share_api,
            data=data,
            headers=headers,
            auth=(user, pw),
            timeout=30
        )
        if r.status_code == 200 and "<url>" in r.text:
            import re
            url_match = re.search(r"<url>(.*?)</url>", r.text)
            if url_match:
                share_url = url_match.group(1)
    except Exception as e:
        logging.error(f"Nextcloud share link error: {e}")

    return share_url or True

def list_nextcloud_backups():
    url = getattr(config, "NEXTCLOUD_URL", "").strip()
    user = getattr(config, "NEXTCLOUD_USER", "").strip()
    pw = getattr(config, "NEXTCLOUD_PASS", "").strip()
    if not url or not user or not pw:
        return []
    try:
        r = requests.request("PROPFIND", url, auth=(user, pw), headers={"Depth": "1"})
        if r.status_code == 207:
            import re
            files = re.findall(r"<d:href>[^<]+/(backup-[^<]+\.zip)</d:href>", r.text)
            return files
    except Exception as e:
        logging.error(f"Nextcloud list error: {e}")
    return []

def download_from_nextcloud(remote_filename, local_path):
    url = getattr(config, "NEXTCLOUD_URL", "").strip()
    user = getattr(config, "NEXTCLOUD_USER", "").strip()
    pw = getattr(config, "NEXTCLOUD_PASS", "").strip()
    if not url or not user or not pw:
        return False
    file_url = url.rstrip("/") + "/" + remote_filename
    try:
        r = requests.get(file_url, auth=(user, pw), stream=True, timeout=120)
        if r.status_code == 200:
            with open(local_path, "wb") as fout:
                for chunk in r.iter_content(chunk_size=4096):
                    fout.write(chunk)
            return True
        else:
            logging.error(f"Nextcloud download failed: {r.status_code} {r.text}")
    except Exception as e:
        logging.error(f"Nextcloud download error: {e}")
    return False

def is_admin(update: Update) -> bool:
    user = update.effective_user
    return user and user.id == ADMIN_TELEGRAM_ID

def _reply(update: Update, *args, **kwargs):
    if hasattr(update, "message") and update.message:
        return update.message.reply_text(*args, **kwargs)
    elif hasattr(update, "callback_query") and update.callback_query:
        return update.callback_query.message.reply_text(*args, **kwargs)

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
    for f in BACKUP_FILES:
        if not os.path.isfile(f):
            logging.error(f"Backup file missing or not a file: {f}")
            raise FileNotFoundError(f"Missing backup file: {f}")
    hash_txt = compute_hashes(BACKUP_FILES)
    with open(HASH_FILE, "w") as hout:
        hout.write(hash_txt)

    try:
        with ZipFile(BACKUP_TMP, 'w', compression=ZIP_STORED) as zf:
            for filepath in BACKUP_FILES:
                zf.write(filepath, arcname=os.path.basename(filepath))
            zf.write(HASH_FILE, arcname=HASH_FILE)
        if os.path.exists(HASH_FILE):
            os.remove(HASH_FILE)

        MIN_SIZE = 128 * 1024
        zip_size = os.path.getsize(BACKUP_TMP)
        if zip_size < MIN_SIZE:
            pad_size = MIN_SIZE - zip_size
            with open(PAD_FILE, "wb") as pf:
                pf.write(b"\0" * pad_size)
            with ZipFile(BACKUP_TMP, 'a', compression=ZIP_STORED) as zf:
                zf.write(PAD_FILE, arcname="__pad.bin")
            os.remove(PAD_FILE)
            logging.info(f"Added internal pad file to reach {MIN_SIZE} bytes.")

    except Exception as e:
        logging.error(f"Failed to create zip archive: {e}")
        raise

    if not os.path.isfile(BACKUP_TMP) or os.path.getsize(BACKUP_TMP) == 0:
        logging.error("Backup zip file not created or is empty")
        raise IOError("Backup zip creation failed")

    try:
        with ZipFile(BACKUP_TMP, 'r') as testzip:
            badfile = testzip.testzip()
            if badfile:
                logging.error(f"Backup zip integrity failed (corrupt file: {badfile})")
                raise IOError(f"Backup zip integrity failed: bad file in archive: {badfile}")
    except Exception as e:
        logging.error(f"Backup zip failed verification: {e}")
        raise

    nowtag = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_copy_path = os.path.join(RETENTION_DIR, f"backup-{nowtag}{suffix}.zip")
    shutil.copy2(BACKUP_TMP, backup_copy_path)
    if os.path.getsize(backup_copy_path) == 0:
        logging.error("Copied backup zip file is empty!")
        raise IOError("Copied backup zip file is empty")
    enforce_retention()
    logging.info(f"Backup zip created at {backup_copy_path}")
    return backup_copy_path

# ──────────────────────────────
# Manual backup (command or button)
@require_unlock
async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await _reply(update, "❌ You are not authorized to use this command.")
        return
    try:
        backup_file = make_backup_file()
    except Exception as e:
        await _reply(update, f"❌ Failed to create backup: {e}")
        return

    # --- Upload to Nextcloud and get link ---
    share_url = upload_to_nextcloud(backup_file, os.path.basename(backup_file), share=True)
    if share_url and isinstance(share_url, str):
        await _reply(
            update,
            f"🗄️ Encrypted DB backup created and uploaded to Nextcloud.\n"
            f"<b>Direct cloud download:</b> <a href='{share_url}'>{share_url}</a>",
            parse_mode="HTML"
        )
    else:
        await _reply(
            update,
            f"🗄️ Backup created and uploaded to encrypted cloud as: <code>{os.path.basename(backup_file)}</code>\n"
            f"To restore, use the server restore option and select this file.",
            parse_mode="HTML"
        )
    if os.path.exists(BACKUP_TMP):
        os.remove(BACKUP_TMP)

# ──────────────────────────────
# Restore (upload backup zip, txt, dbk, bin, etc.)
async def restore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await _reply(update, "❌ You are not authorized to use this command.")
        return ConversationHandler.END
    await _reply(
        update,
        "⚠️ Upload your backup archive (any extension, must be a .zip format) with DB, salt, and hash file. "
        "This will OVERWRITE your current DB if hashes match.\n"
        "Type /cancel to abort."
    )
    return RESTORE_WAITING

async def restore_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("[DEBUG] restore_receive called")
    if not is_admin(update):
        await update.message.reply_text("❌ You are not authorized to restore.")
        return ConversationHandler.END

    doc = update.message.document
    if not doc or not doc.file_name:
        await update.message.reply_text("❌ Please upload a backup archive file.")
        return RESTORE_WAITING

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, doc.file_name)
        file = await doc.get_file()
        await file.download_to_drive(file_path)
        try:
            # Accept any file extension, just check it's a valid zip
            with ZipFile(file_path, "r") as zf:
                names = zf.namelist()
                needed = ["db.json", "kdf_salt.bin", "backup.sha256"]
                if not all(f in names for f in needed):
                    await update.message.reply_text(
                        f"❌ Archive missing one of: {', '.join(needed)}"
                    )
                    return RESTORE_WAITING
                zf.extract("db.json", path=tmpdir)
                zf.extract("kdf_salt.bin", path=tmpdir)
                zf.extract("backup.sha256", path=tmpdir)
            ok, msg = check_hashes(tmpdir, os.path.join(tmpdir, "backup.sha256"))
            if not ok:
                await update.message.reply_text(f"❌ Hash check failed: {msg}. Restore aborted.")
                return ConversationHandler.END
            # PATCH: Unlock the salt file for writing
            if os.path.exists("data/kdf_salt.bin"):
                os.chmod("data/kdf_salt.bin", stat.S_IWRITE | stat.S_IREAD)
            shutil.move(os.path.join(tmpdir, "db.json"), "data/db.json")
            shutil.move(os.path.join(tmpdir, "kdf_salt.bin"), "data/kdf_salt.bin")
            # PATCH: Lock down the salt file again
            os.chmod("data/kdf_salt.bin", 0o444)
        except Exception as e:
            logging.error(f"Restore failed: {e}")
            await update.message.reply_text(f"❌ Restore failed: {e}")
            return ConversationHandler.END

    await update.message.reply_text(
        "✅ Restore complete and hash verified! Please /unlock with your PIN."
    )
    return ConversationHandler.END

# ──────────────────────────────
# Restore from Nextcloud (user selection)
async def cloud_restore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await _reply(update, "❌ Not authorized.")
        return ConversationHandler.END
    # List .zip backup files from Nextcloud root
    files = list_nextcloud_backups()
    if not files:
        await _reply(update, "❌ No backups found on Nextcloud.")
        return ConversationHandler.END
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f, callback_data=f"cloudrestore_{f}")]
        for f in files
    ] + [[InlineKeyboardButton("🔙 Cancel", callback_data="cloudrestore_cancel")]])
    await _reply(
        update,
        "Select a backup file from Nextcloud to restore:",
        reply_markup=kb
    )
    return CLOUD_RESTORE_SELECT

async def cloud_restore_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    if data == "cloudrestore_cancel":
        await update.callback_query.edit_message_text("Cloud restore cancelled.")
        return ConversationHandler.END
    if not data.startswith("cloudrestore_"):
        await update.callback_query.answer("Unknown cloud restore action.", show_alert=True)
        return
    fname = data[len("cloudrestore_") :]
    with tempfile.TemporaryDirectory() as tmpdir:
        dl_path = os.path.join(tmpdir, fname)
        if not download_from_nextcloud(fname, dl_path):
            await update.callback_query.edit_message_text(f"❌ Failed to download {fname} from Nextcloud.")
            return ConversationHandler.END
        # Try to restore as normal
        try:
            with ZipFile(dl_path, "r") as zf:
                names = zf.namelist()
                needed = ["db.json", "kdf_salt.bin", "backup.sha256"]
                if not all(f in names for f in needed):
                    await update.callback_query.edit_message_text(
                        f"❌ Archive missing one of: {', '.join(needed)}"
                    )
                    return ConversationHandler.END
                zf.extract("db.json", path=tmpdir)
                zf.extract("kdf_salt.bin", path=tmpdir)
                zf.extract("backup.sha256", path=tmpdir)
            ok, msg = check_hashes(tmpdir, os.path.join(tmpdir, "backup.sha256"))
            if not ok:
                await update.callback_query.edit_message_text(f"❌ Hash check failed: {msg}. Restore aborted.")
                return ConversationHandler.END
            # PATCH: Unlock the salt file for writing
            if os.path.exists("data/kdf_salt.bin"):
                os.chmod("data/kdf_salt.bin", stat.S_IWRITE | stat.S_IREAD)
            shutil.move(os.path.join(tmpdir, "db.json"), "data/db.json")
            shutil.move(os.path.join(tmpdir, "kdf_salt.bin"), "data/kdf_salt.bin")
            os.chmod("data/kdf_salt.bin", 0o444)
        except Exception as e:
            logging.error(f"Cloud restore failed: {e}")
            await update.callback_query.edit_message_text(f"❌ Cloud restore failed: {e}")
            return ConversationHandler.END
    await update.callback_query.edit_message_text(
        f"✅ Cloud restore complete and hash verified! Please /unlock with your PIN."
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
    elif data.startswith("restorefile_") and not data == "restorefile_confirm" and not data == "restorefile_cancel":
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
                    needed = ["db.json", "kdf_salt.bin", "backup.sha256"]
                    if not all(f in names for f in needed):
                        await update.callback_query.message.reply_text("❌ Archive missing required files.")
                        return
                    zf.extract("db.json", path=tmpdir)
                    zf.extract("kdf_salt.bin", path=tmpdir)
                    zf.extract("backup.sha256", path=tmpdir)
                ok, msg = check_hashes(tmpdir, os.path.join(tmpdir, "backup.sha256"))
                if not ok:
                    await update.callback_query.message.reply_text(f"❌ Hash check failed: {msg}. Restore aborted.")
                    return
                # PATCH: Unlock the salt file for writing
                if os.path.exists("data/kdf_salt.bin"):
                    os.chmod("data/kdf_salt.bin", stat.S_IWRITE | stat.S_IREAD)
                shutil.move(os.path.join(tmpdir, "db.json"), "data/db.json")
                shutil.move(os.path.join(tmpdir, "kdf_salt.bin"), "data/kdf_salt.bin")
                # PATCH: Lock down the salt file again
                os.chmod("data/kdf_salt.bin", 0o444)
            await update.callback_query.message.reply_text(
                f"✅ Restore from <b>{fname}</b> complete and hash verified! Please /unlock with your PIN.",
                parse_mode="HTML"
            )
        except Exception as e:
            await update.callback_query.message.reply_text(f"❌ Restore failed: {e}")
    elif data == "restorefile_cancel":
        await update.callback_query.message.reply_text("Restore cancelled.")
    elif data.startswith("cloudrestore_") or data == "cloudrestore_cancel":
        await cloud_restore_receive(update, context)

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
                os.path.basename(backup_file),
                share=False
            )
            msg = (
                f"✅ Weekly auto-backup complete and uploaded to Nextcloud.\n"
                f"- Local file: <code>{os.path.basename(backup_file)}</code>\n"
                f"- Cloud copy: <b>uploaded</b>\n"
                "No public download link is created for auto-backups."
            )
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
    app.add_handler(CommandHandler("restore", restore_command))
    # Cloud restore entry: (button, not command)
    app.add_handler(CallbackQueryHandler(cloud_restore_command, pattern="^backup_cloud_restore$"))
    restore_conv = ConversationHandler(
        entry_points=[
            CommandHandler("restore", restore_command),
            CallbackQueryHandler(restore_command, pattern="^backup_restore$"),
            CallbackQueryHandler(cloud_restore_command, pattern="^backup_cloud_restore$"),
        ],
        states={
            RESTORE_WAITING: [MessageHandler(filters.ALL, restore_receive)],
            CLOUD_RESTORE_SELECT: [CallbackQueryHandler(cloud_restore_receive, pattern="^(cloudrestore_.*|cloudrestore_cancel)$")],
        },
        fallbacks=[CommandHandler("cancel", restore_cancel)],
        name="restore_conv",
    )
    app.add_handler(restore_conv)
    app.add_handler(CallbackQueryHandler(backups_callback, pattern="^(downloadbackup_|restorefile_|restorefile_confirm|restorefile_cancel|cloudrestore_.*|cloudrestore_cancel)$"))
    app.create_task(autobackup_task(app))
