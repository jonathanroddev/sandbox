# Backup Script

This script creates a daily backup of the `data_dir` directory and saves it to the `onedrive_backup_folder`. It also cleans up older backups to keep only the 3 most recent ones.

---

## Minimum Requirements

### Python Packages

- **`yagmail`** – for sending error emails  
- **`schedule`** – for scheduling the backup task

---

## Script Variables

- **`EMAIL_USER`**: your email username  
- **`EMAIL_PASS`**: your email password  
- **`EMAIL_TO`**: the recipient’s email address  
- **`onedrive_backup_folder`**: the path to the OneDrive backup folder  
- **`data_dir`**: the path to the directory you want to backup  
- **`backup_prefix`**: the prefix for the backup file name  
- **`backup_extension`**: the file extension for the backup file
- **`schedule_date`**: the date at which the backup task will run

---

## Installation

```bash
pip install yagmail schedule
```

---

## Setup

1. Set the variables mentioned above in the script.  

---

## Usage

Once you’ve set up the script, it will run automatically at the scheduled time and create a backup of the `data_dir` directory.  
If any errors occur during the backup process, an email will be sent to the recipient’s email address.

---

## Note

> ⚠️ Make sure to keep your email credentials secure and do not share them with anyone.
