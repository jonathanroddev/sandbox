import schedule
import os
import time
from datetime import datetime
import yagmail
import zipfile
import re

data_dir = r"C:\path\to\data"  # Change this to your data directory
onedrive_backup_folder = r"C:\Users\yourUser\OneDrive\Backups" # Change this to your OneDrive backup folder
backup_prefix = "backup_data_"
backup_extension = ".zip"

EMAIL_USER = "your_mail@gmail.com" # Change this to your email
EMAIL_PASS = "your_password" # Change this to your email password
EMAIL_TO = "your_mail@gmail.com" # Change this to your email

schedule_date = "00:00"

def send_mail(error_msg: str) -> None:
    """
    Sends an email with the provided error message.
    Args:
        error_msg (str): The error message to be sent in the email.
    """
    try:
        yag = yagmail.SMTP(EMAIL_USER, EMAIL_PASS)
        yag.send(to=EMAIL_TO, subject="❌ Error en backup diario", contents=error_msg)
        print("Error mail sent.")
    except Exception as e:
        print(f"Error sending mail: {e}")

def clean_older_backups() -> None:
    """
        Cleans up older backups by deleting files that are older than the 3 most recent backups.
    """
    files = os.listdir(onedrive_backup_folder)
    backups = [f for f in files if f.startswith(backup_prefix) and f.endswith(backup_extension)]

    backups_with_dates = []
    for backup in backups:
        match = re.search(r"(\d{8})", backup)
        if match:
            date = match.group(1)
            backups_with_dates.append((date, backup))

    sorted_backups = sorted(backups_with_dates, key=lambda x: x[0], reverse=True)

    for date, file in sorted_backups[3:]:
        try:
            os.remove(os.path.join(onedrive_backup_folder, file))
            print(f"Deleted oldest backup: {file}")
        except Exception as e:
            send_mail(f"No se pudo eliminar el backup antiguo {file}: {str(e)}")

def do_backup() -> None:
    """
        Creates a backup of the data directory and saves it to the OneDrive backup folder.
    """
    print("Doing backup...")
    try:
        today = datetime.now().strftime("%Y%m%d")
        backup_filename = f"{backup_prefix}{today}{backup_extension}"
        backup_path = os.path.join(onedrive_backup_folder, backup_filename)

        if os.path.exists(backup_path):
            print("Backup already exists")
            return

        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for folder_name, subfolders, filenames in os.walk(data_dir):
                for filename in filenames:
                    filepath = os.path.join(folder_name, filename)
                    arc_name = os.path.relpath(filepath, data_dir)
                    zipf.write(filepath, arc_name)
        print(f"Backup done successfully: {backup_path}")

        clean_older_backups()

    except Exception as e:
        error_msg = f"Error durante el backup:\n\n{str(e)}"
        print(error_msg)
        send_mail(error_msg)


schedule.every().day.at(schedule_date).do(do_backup)

print(f"⏳ Esperando a las {schedule_date} para crear backup del directorio...")
while True:
    schedule.run_pending()
    time.sleep(60)
