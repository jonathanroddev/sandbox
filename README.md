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
| [`blender_bridge/`](blender_bridge/) | Real-time bridge from an Arduino motion sensor (MPU-6050) to Blender: streams orientation over USB serial and drives an object's rotation. Arduino sketch + Blender Python script. |

## Layout convention

Each project is a top-level folder that can be copied out and used on its own:

```
sandbox/
├── folder_backup/       # backup utility + its README
└── blender_bridge/      # Arduino → Blender orientation bridge
    ├── arduino/         # Arduino sketches (main bridge + I2C diagnostic)
    ├── blender/         # Blender-side Python script + config.env
    ├── tools/           # host-side helper scripts (serial reader)
    ├── docs/            # CONTEXT.md — hardware notes and decisions
    └── backups/         # original board flash/EEPROM dumps
```

Per-project setup, requirements and usage live inside each folder — see
[`folder_backup/README.md`](folder_backup/README.md) and
[`blender_bridge/docs/CONTEXT.md`](blender_bridge/docs/CONTEXT.md).
