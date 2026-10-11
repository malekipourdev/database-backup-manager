"""Bot texts in Persian and English, plus locale-aware number, size and date formatting."""

from datetime import datetime
from zoneinfo import ZoneInfo

LANGUAGES = ("fa", "en")

TEXTS: dict[str, dict[str, str]] = {
    "fa": {
        "unauthorized": (
            "⛔️ شما اجازه‌ی استفاده از این ربات را ندارید.\n\n"
            "شناسه‌ی عددی شما: {user_id}\n"
            "برای دسترسی، مدیر پنل باید این شناسه را در بخش «ربات‌ها» ثبت کند، "
            "یا یک کد اتصال به شما بدهد."
        ),
        "unauthorized_short": "⛔️ دسترسی ندارید.",
        "linked": "✅ حساب شما با نام «{name}» به پنل متصل شد.",
        "link_invalid": "⛔️ کد اتصال نامعتبر است یا منقضی شده.",
        "expired_button": "این دکمه منقضی شده؛ دوباره از منو شروع کنید.",
        "error": "⚠️ خطا: {message}",
        "working": "⏳ در حال انجام…",
        "menu_title": "🗄 پنل پشتیبان‌گیری MySQL\nیک گزینه را انتخاب کنید:",
        "btn_status": "📊 وضعیت",
        "btn_instances": "🖥 سرورها",
        "btn_runs": "📜 آخرین بکاپ‌ها",
        "btn_schedules": "⏰ زمان‌بندی‌ها",
        "btn_retention": "🧹 سیاست نگهداری",
        "btn_settings": "🔔 اعلان‌ها و زبان",
        "btn_menu": "🏠 منو",
        "btn_back": "« بازگشت",
        "btn_refresh": "🔄 به‌روزرسانی",
        "btn_prev": "‹ قبلی",
        "btn_next": "بعدی ›",
        "btn_yes": "✅ بله",
        "btn_cancel": "✖️ انصراف",
        "status_title": "📊 وضعیت کلی",
        "status_instances": "🖥 سرورها: {n}",
        "status_active": "⏳ در حال اجرا/صف: {n}",
        "status_24h": "📅 ۲۴ ساعت گذشته: {ok} موفق، {failed} ناموفق",
        "status_last_ok": "✅ آخرین بکاپ موفق: {db} از {instance} — {time}",
        "status_last_ok_none": "✅ آخرین بکاپ موفق: هنوز نداریم",
        "status_disk": "💽 فضای آزاد محل بکاپ‌ها: {free} از {total}",
        "status_remote_on": "☁️ فضای ابری: فعال ({bucket})",
        "status_remote_off": "☁️ فضای ابری: غیرفعال",
        "status_next": "⏰ اجرای بعدی: {name} ({instance}) — {time}",
        "status_next_none": "⏰ زمان‌بندی فعالی وجود ندارد",
        "instances_title": "🖥 سرورها ({n}):",
        "instances_empty": "هنوز سروری ثبت نشده است. سرورها را از پنل وب اضافه کنید.",
        "instance_title": "🖥 {name}",
        "instance_address": "نشانی: {address}",
        "instance_server": "نوع: {server}",
        "instance_server_unknown": "نوع: نامشخص (هنوز آزمایش نشده)",
        "instance_marked": "دیتابیس‌های علامت‌خورده ({n}): {names}",
        "instance_marked_none": "هیچ دیتابیسی برای بکاپ علامت نخورده.",
        "instance_last_run": "آخرین بکاپ: {status} — {time}",
        "btn_test": "🔌 آزمایش اتصال",
        "btn_backup_all": "💾 بکاپ همه‌ی علامت‌خورده‌ها ({n})",
        "btn_backup_one": "🗄 بکاپ یک دیتابیس",
        "btn_instance_runs": "📜 بکاپ‌های این سرور",
        "btn_instance_schedules": "⏰ زمان‌بندی‌های این سرور",
        "test_ok": "✅ اتصال برقرار شد: {server}",
        "test_failed": "❌ اتصال ناموفق: {reason}",
        "confirm_backup_all": "از {n} دیتابیس سرور «{name}» بکاپ گرفته شود؟\n{names}",
        "backup_started": "✅ {n} بکاپ شروع شد. نتیجه را در «بکاپ‌های این سرور» ببینید.",
        "backup_skipped": "⏭ رد شد (در حال اجرا): {names}",
        "databases_title": "🗄 دیتابیس‌های «{name}» — یکی را برای بکاپ انتخاب کنید:\n(✅ = علامت‌خورده)",
        "databases_unreachable": "❌ فهرست دیتابیس‌ها از سرور دریافت نشد: {reason}",
        "databases_empty": "دیتابیسی پیدا نشد.",
        "runs_title": "📜 بکاپ‌ها{scope} — صفحه‌ی {page}:",
        "runs_scope": "ی «{name}»",
        "runs_empty": "هنوز بکاپی وجود ندارد.",
        "run_title": "{icon} بکاپ «{db}» از «{instance}»",
        "run_status": "وضعیت: {status}",
        "run_trigger": "نوع: {trigger}",
        "run_requested": "زمان: {time}",
        "run_duration": "مدت: {duration}",
        "run_size": "حجم: {size} ({compression})",
        "run_checksum": "SHA-256: {checksum}",
        "run_remote": "فضای ابری: {remote}",
        "run_retention": "🧹 فایل محلی در {time} توسط سیاست نگهداری حذف شد.",
        "run_error": "خطا: {error}",
        "btn_download": "📥 دریافت فایل",
        "btn_upload": "☁️ آپلود به فضای ابری",
        "btn_delete": "🗑 حذف",
        "confirm_delete": "بکاپ «{db}» از {time} حذف شود؟",
        "btn_delete_local": "🗑 فقط فایل روی سرور",
        "btn_delete_both": "🗑 فایل روی سرور و نسخه‌ی ابری",
        "btn_delete_remote": "🗑 حذف نسخه‌ی ابری",
        "remote_protected": "🔒 نسخه‌ی ابری تا {time} از حذف محافظت می‌شود (۷ روز پس از آپلود) و تا آن زمان فقط از پنل خود فضای ابری قابل حذف است.",
        "deleted_local_kept_remote": "🗑 فایل روی سرور حذف شد. نسخه‌ی ابری نگه داشته شد و هنوز قابل دریافت است.",
        "deleted": "🗑 بکاپ حذف شد.",
        "upload_queued": "☁️ آپلود شروع شد.",
        "file_disabled": "ارسال فایل از طریق ربات در پنل غیرفعال است.",
        "file_too_large": "حجم فایل ({size}) بیشتر از سقف ارسال ربات ({limit}) است. از پنل وب دانلود کنید.",
        "file_unavailable": "فایل این بکاپ در دسترس نیست.",
        "file_caption": "بکاپ {db} از {instance} — {time}\nSHA-256: {checksum}",
        "schedules_title": "⏰ زمان‌بندی‌ها{scope}:",
        "schedules_empty": "زمان‌بندی‌ای وجود ندارد. از پنل وب اضافه کنید.",
        "schedule_title": "⏰ {name} — {instance}",
        "schedule_when": "زمان: {cron} ({tz})",
        "schedule_scope_all": "محدوده: همه‌ی دیتابیس‌های علامت‌خورده",
        "schedule_scope_single": "محدوده: دیتابیس {db}",
        "schedule_state_on": "وضعیت: 🟢 فعال",
        "schedule_state_off": "وضعیت: ⏸ غیرفعال",
        "schedule_next": "اجرای بعدی: {time}",
        "schedule_last": "آخرین اجرا: {result} — {time}",
        "btn_disable": "⏸ غیرفعال کن",
        "btn_enable": "▶️ فعال کن",
        "btn_run_now": "⚡️ اجرای الان",
        "schedule_fired": "⚡️ اجرا شد: {result}",
        "retention_title": "🧹 سیاست نگهداری (سراسری)",
        "retention_local": "فایل‌های محلی: {policy}",
        "retention_remote": "نسخه‌های ابری: {policy}",
        "retention_keep": "نگه‌داشتن {n} نسخه‌ی آخر",
        "retention_age": "حذف پس از {n} روز",
        "retention_all": "نگه‌داشتن همه",
        "retention_note": "جدیدترین بکاپ هر دیتابیس هیچ‌وقت حذف نمی‌شود. تغییر سیاست از پنل وب.",
        "btn_preview": "🔍 پیش‌نمایش حذف",
        "retention_preview": "این {n} فایل حذف می‌شوند:\n{items}",
        "retention_nothing": "طبق سیاست فعلی چیزی برای حذف وجود ندارد.",
        "btn_apply": "🗑 حذف {n} فایل",
        "retention_applied": "🧹 {deleted} فایل حذف شد، {errors} خطا.",
        "settings_title": "🔔 اعلان‌ها و زبان",
        "on": "روشن",
        "off": "خاموش",
        "btn_language": "🌐 English",
        "settings_level": "سطح اعلان‌ها: {level}",
        "settings_hint": "کدام هشدارها برای شما در این ربات فرستاده شود؟ نوع رویدادها و کانال‌ها در پنل وب (بخش اعلان‌ها) تنظیم می‌شوند.",
        "level_info": "همه (حتی بکاپ‌های موفق)",
        "level_warning": "هشدارها و خطاها",
        "level_error": "فقط خطاها",
        "level_off": "خاموش",
        "event_backup_failed": "بکاپ «{db}» از «{instance}» ناموفق بود:\n{reason}",
        "event_upload_failed": "آپلود بکاپ «{db}» از «{instance}» به فضای ابری ناموفق بود:\n{reason}",
        "event_retention_error": "سیاست نگهداری نتوانست بکاپ قدیمی «{db}» از «{instance}» را حذف کند: {reason}",
        "event_backup_succeeded": "بکاپ «{db}» از «{instance}» موفق بود — {size}، {duration}{remote}",
        "event_remote_suffix": "، ذخیره در فضای ابری",
        "event_stale_backup": "از «{db}» روی «{instance}» در {hours} ساعت گذشته بکاپ موفقی گرفته نشده. آخرین بکاپ موفق: {last}",
        "event_disk_low": "فضای آزاد محل بکاپ‌ها کم است: {percent}٪ ({free} از {total})، کمتر از حد {threshold}٪.",
        "event_recovered_stale": "✅ بکاپ «{db}» روی «{instance}» دوباره به‌روز است.",
        "event_recovered_disk": "✅ فضای آزاد محل بکاپ‌ها دوباره کافی است ({free}).",
        "event_schedule_problem": "زمان‌بندی «{name}» ({instance}) اجرا نشد: {result}",
        "event_daily_summary": "📋 گزارش روزانه‌ی بکاپ‌ها (۲۴ ساعت گذشته)",
        "event_test": "🔔 این یک اعلان آزمایشی از پنل پشتیبان‌گیری است.",
        "summary_runs": "موفق: {ok} — ناموفق: {failed}",
        "summary_failed_list": "ناموفق‌ها: {names}",
        "summary_uploads": "آپلود به فضای ابری: {ok} موفق، {failed} ناموفق",
        "summary_stale": "دیتابیس‌های بدون بکاپ به‌روز: {n}",
        "summary_disk": "فضای آزاد: {free} از {total}",
        "btn_view": "مشاهده",
        "status_queued": "در صف",
        "status_running": "در حال اجرا",
        "status_success": "موفق",
        "status_failed": "ناموفق",
        "trigger_all": "دستی (همه)",
        "trigger_single": "دستی (تکی)",
        "trigger_schedule": "زمان‌بندی‌شده",
        "remote_uploading": "در حال آپلود",
        "remote_success": "ذخیره شده",
        "remote_failed": "ناموفق",
        "remote_deleted": "حذف شده",
        "remote_none": "آپلود نشده",
        "result_queued": "شروع شد",
        "result_partially_queued": "بخشی شروع شد",
        "result_already_in_progress": "رد شد (در حال اجرا)",
        "result_no_databases_selected": "دیتابیسی علامت نخورده",
        "result_instance_not_found": "سرور وجود ندارد",
        "result_error": "خطا",
        "never": "هنوز نه",
        "duration_sub": "کمتر از ۱ ثانیه",
        "duration_s": "{n} ثانیه",
        "duration_m": "{m} دقیقه و {s} ثانیه",
        "duration_h": "{h} ساعت و {m} دقیقه",
    },
    "en": {
        "unauthorized": (
            "⛔️ You are not allowed to use this bot.\n\n"
            "Your numeric ID: {user_id}\n"
            "To get access, a panel admin must add this ID under “Bots”, or give you a link code."
        ),
        "unauthorized_short": "⛔️ Not allowed.",
        "linked": "✅ Your account is now linked to the panel as “{name}”.",
        "link_invalid": "⛔️ The link code is invalid or has expired.",
        "expired_button": "This button has expired; start again from the menu.",
        "error": "⚠️ Error: {message}",
        "working": "⏳ Working…",
        "menu_title": "🗄 MySQL Backup Panel\nChoose an option:",
        "btn_status": "📊 Status",
        "btn_instances": "🖥 Servers",
        "btn_runs": "📜 Latest backups",
        "btn_schedules": "⏰ Schedules",
        "btn_retention": "🧹 Retention",
        "btn_settings": "🔔 Notifications & language",
        "btn_menu": "🏠 Menu",
        "btn_back": "« Back",
        "btn_refresh": "🔄 Refresh",
        "btn_prev": "‹ Previous",
        "btn_next": "Next ›",
        "btn_yes": "✅ Yes",
        "btn_cancel": "✖️ Cancel",
        "status_title": "📊 Overview",
        "status_instances": "🖥 Servers: {n}",
        "status_active": "⏳ Running/queued: {n}",
        "status_24h": "📅 Last 24 hours: {ok} succeeded, {failed} failed",
        "status_last_ok": "✅ Last successful backup: {db} on {instance} — {time}",
        "status_last_ok_none": "✅ Last successful backup: none yet",
        "status_disk": "💽 Free space in the backup area: {free} of {total}",
        "status_remote_on": "☁️ Remote storage: on ({bucket})",
        "status_remote_off": "☁️ Remote storage: off",
        "status_next": "⏰ Next run: {name} ({instance}) — {time}",
        "status_next_none": "⏰ No enabled schedules",
        "instances_title": "🖥 Servers ({n}):",
        "instances_empty": "No servers yet. Add them in the web panel.",
        "instance_title": "🖥 {name}",
        "instance_address": "Address: {address}",
        "instance_server": "Type: {server}",
        "instance_server_unknown": "Type: unknown (not tested yet)",
        "instance_marked": "Marked databases ({n}): {names}",
        "instance_marked_none": "No databases are marked for backup.",
        "instance_last_run": "Last backup: {status} — {time}",
        "btn_test": "🔌 Test connection",
        "btn_backup_all": "💾 Back up all marked ({n})",
        "btn_backup_one": "🗄 Back up one database",
        "btn_instance_runs": "📜 Backups of this server",
        "btn_instance_schedules": "⏰ Schedules of this server",
        "test_ok": "✅ Connected: {server}",
        "test_failed": "❌ Connection failed: {reason}",
        "confirm_backup_all": "Back up {n} database(s) of “{name}”?\n{names}",
        "backup_started": "✅ {n} backup(s) started. See “Backups of this server” for results.",
        "backup_skipped": "⏭ Skipped (already running): {names}",
        "databases_title": "🗄 Databases of “{name}” — pick one to back up:\n(✅ = marked)",
        "databases_unreachable": "❌ Could not list databases from the server: {reason}",
        "databases_empty": "No databases found.",
        "runs_title": "📜 Backups{scope} — page {page}:",
        "runs_scope": " of “{name}”",
        "runs_empty": "No backups yet.",
        "run_title": "{icon} Backup of “{db}” on “{instance}”",
        "run_status": "Status: {status}",
        "run_trigger": "Type: {trigger}",
        "run_requested": "Time: {time}",
        "run_duration": "Duration: {duration}",
        "run_size": "Size: {size} ({compression})",
        "run_checksum": "SHA-256: {checksum}",
        "run_remote": "Remote storage: {remote}",
        "run_retention": "🧹 Local file removed by retention on {time}.",
        "run_error": "Error: {error}",
        "btn_download": "📥 Get file",
        "btn_upload": "☁️ Upload to remote storage",
        "btn_delete": "🗑 Delete",
        "confirm_delete": "Delete the backup of “{db}” from {time}?",
        "btn_delete_local": "🗑 Only the file on the server",
        "btn_delete_both": "🗑 Server file and remote copy",
        "btn_delete_remote": "🗑 Delete the remote copy",
        "remote_protected": "🔒 The remote copy is protected until {time} (7 days after upload); until then it can only be deleted in the storage provider itself.",
        "deleted_local_kept_remote": "🗑 The file on the server was deleted. The remote copy was kept and can still be downloaded.",
        "deleted": "🗑 Backup deleted.",
        "upload_queued": "☁️ Upload started.",
        "file_disabled": "Sending files through the bot is turned off in the panel.",
        "file_too_large": "The file ({size}) is larger than the bot's limit ({limit}). Download it from the web panel.",
        "file_unavailable": "This backup's file is not available.",
        "file_caption": "Backup of {db} on {instance} — {time}\nSHA-256: {checksum}",
        "schedules_title": "⏰ Schedules{scope}:",
        "schedules_empty": "No schedules. Add them in the web panel.",
        "schedule_title": "⏰ {name} — {instance}",
        "schedule_when": "When: {cron} ({tz})",
        "schedule_scope_all": "Scope: all marked databases",
        "schedule_scope_single": "Scope: database {db}",
        "schedule_state_on": "State: 🟢 enabled",
        "schedule_state_off": "State: ⏸ disabled",
        "schedule_next": "Next run: {time}",
        "schedule_last": "Last run: {result} — {time}",
        "btn_disable": "⏸ Disable",
        "btn_enable": "▶️ Enable",
        "btn_run_now": "⚡️ Run now",
        "schedule_fired": "⚡️ Run: {result}",
        "retention_title": "🧹 Retention policy (global)",
        "retention_local": "Local files: {policy}",
        "retention_remote": "Remote copies: {policy}",
        "retention_keep": "keep the last {n}",
        "retention_age": "delete after {n} days",
        "retention_all": "keep all",
        "retention_note": "The newest backup of each database is never deleted. Change the policy in the web panel.",
        "btn_preview": "🔍 Preview deletions",
        "retention_preview": "These {n} file(s) would be deleted:\n{items}",
        "retention_nothing": "Nothing to delete under the current policy.",
        "btn_apply": "🗑 Delete {n} file(s)",
        "retention_applied": "🧹 {deleted} file(s) deleted, {errors} error(s).",
        "settings_title": "🔔 Notifications & language",
        "on": "on",
        "off": "off",
        "btn_language": "🌐 فارسی",
        "settings_level": "Notification level: {level}",
        "settings_hint": "Which alerts this bot sends you. Event types and channels are set in the web panel (Notifications).",
        "level_info": "everything (including successful backups)",
        "level_warning": "warnings and errors",
        "level_error": "errors only",
        "level_off": "off",
        "event_backup_failed": "Backup of “{db}” on “{instance}” failed:\n{reason}",
        "event_upload_failed": "Upload of the backup of “{db}” on “{instance}” failed:\n{reason}",
        "event_retention_error": "Retention could not delete an old backup of “{db}” on “{instance}”: {reason}",
        "event_backup_succeeded": "Backup of “{db}” on “{instance}” succeeded — {size}, {duration}{remote}",
        "event_remote_suffix": ", stored remotely",
        "event_stale_backup": "No successful backup of “{db}” on “{instance}” in the last {hours} hours. Last success: {last}",
        "event_disk_low": "Low free space in the backup area: {percent}% ({free} of {total}), below {threshold}%.",
        "event_recovered_stale": "✅ Backups of “{db}” on “{instance}” are up to date again.",
        "event_recovered_disk": "✅ Free space in the backup area is sufficient again ({free}).",
        "event_schedule_problem": "Schedule “{name}” ({instance}) did not run: {result}",
        "event_daily_summary": "📋 Daily backup report (last 24 hours)",
        "event_test": "🔔 This is a test notification from the backup panel.",
        "summary_runs": "Succeeded: {ok} — failed: {failed}",
        "summary_failed_list": "Failed: {names}",
        "summary_uploads": "Remote uploads: {ok} succeeded, {failed} failed",
        "summary_stale": "Databases without a recent backup: {n}",
        "summary_disk": "Free space: {free} of {total}",
        "btn_view": "View",
        "status_queued": "queued",
        "status_running": "running",
        "status_success": "succeeded",
        "status_failed": "failed",
        "trigger_all": "manual (all)",
        "trigger_single": "manual (single)",
        "trigger_schedule": "scheduled",
        "remote_uploading": "uploading",
        "remote_success": "stored",
        "remote_failed": "failed",
        "remote_deleted": "deleted",
        "remote_none": "not uploaded",
        "result_queued": "started",
        "result_partially_queued": "partly started",
        "result_already_in_progress": "skipped (already running)",
        "result_no_databases_selected": "no databases marked",
        "result_instance_not_found": "server missing",
        "result_error": "error",
        "never": "not yet",
        "duration_sub": "< 1s",
        "duration_s": "{n}s",
        "duration_m": "{m}m {s}s",
        "duration_h": "{h}h {m}m",
    },
}

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def digits(text: str, lang: str) -> str:
    return text.translate(_FA_DIGITS) if lang == "fa" else text


def t(lang: str, key: str, **values) -> str:
    table = TEXTS.get(lang, TEXTS["en"])
    template = table.get(key) or TEXTS["en"].get(key) or key
    if lang == "fa":
        # Bare numbers get Persian digits; names and other text are left as they are.
        values = {
            k: digits(str(v), lang)
            if isinstance(v, int) or (isinstance(v, str) and v.isdigit())
            else v
            for k, v in values.items()
        }
    return template.format(**values)


def gregorian_to_jalali(year: int, month: int, day: int) -> tuple[int, int, int]:
    """Convert a Gregorian date to the Persian (Jalali) calendar."""
    g_days = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = year + 1 if month > 2 else year
    days = (
        355666
        + 365 * year
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        + day
        + g_days[month - 1]
    )
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd


def format_time(value: datetime | None, lang: str, zone: ZoneInfo) -> str:
    if value is None:
        return t(lang, "never")
    local = value.astimezone(zone)
    if lang == "fa":
        y, m, d = gregorian_to_jalali(local.year, local.month, local.day)
        return digits(f"{y}/{m:02d}/{d:02d} {local:%H:%M}", lang)
    return f"{local:%Y-%m-%d %H:%M}"


def format_size(size: int | None, lang: str) -> str:
    if size is None:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    unit = 0
    while value >= 1024 and unit < len(units) - 1:
        value /= 1024
        unit += 1
    text = f"{value:.0f} {units[unit]}" if unit == 0 else f"{value:.1f} {units[unit]}"
    return digits(text, lang)


def format_duration(ms: int | None, lang: str) -> str:
    if ms is None:
        return "—"
    if ms < 1000:
        return t(lang, "duration_sub")
    total = ms // 1000
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    if h:
        return t(lang, "duration_h", h=str(h), m=str(m))
    if m:
        return t(lang, "duration_m", m=str(m), s=str(s))
    return t(lang, "duration_s", n=str(s))
