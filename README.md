# sandbox

A multi-purpose drawer for small, self-contained projects and experiments.

As the name suggests, this repository is not a single application. It's a
collection of independent mini-projects — utilities, prototypes and one-off
tools — that don't warrant a repository of their own. Each lives in its own
top-level folder and is fully self-contained, with its own dependencies,
setup and (where useful) documentation.

## Projects

| Folder | What it does |
| --- | --- |
| [`folder_backup/`](folder_backup/) | Scheduled daily backup of a directory into a ZIP on a OneDrive folder, keeping only the 3 most recent backups and emailing on failure. Python (`schedule`, `yagmail`). |
| [`motion_bridge/`](motion_bridge/) | Real-time bridges from IMU motion sensors to Blender: one sensor over USB serial, and one-or-many sensors over WiFi/UDP (the path to a motion capture suit). Arduino/ESP sketches + Blender Python scripts. |

## Layout convention

Each project is a top-level folder that can be copied out and used on its own:

```
sandbox/
├── folder_backup/       # backup utility + its README
└── motion_bridge/       # IMU sensors → Blender
    ├── docs/            # shared architecture + the sensor frame protocol
    ├── wired/           # 1 sensor  · USB serial (Arduino Uno + MPU-6050)
    └── wifi/            # 1..N sensors · UDP (Arduino/ESP boards, WT901WIFI)
```

`motion_bridge/` is the one project with sub-projects: `wired/` and `wifi/`
are two developments that share conventions and a documented frame format,
but no code. Each subfolder has the usual `firmware/`, `blender/`, `tools/`
and `docs/` split.

Per-project setup, requirements and usage live inside each folder — see
[`folder_backup/README.md`](folder_backup/README.md) and
[`motion_bridge/README.md`](motion_bridge/README.md).
