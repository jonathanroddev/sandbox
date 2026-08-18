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

## Layout convention

Each project is a top-level folder that can be copied out and used on its own:

```
sandbox/
└── folder_backup/       # backup utility + its README
```

Per-project setup, requirements and usage live inside each folder — see
[`folder_backup/README.md`](folder_backup/README.md).

## Moved out

`motion_bridge/` grew past what a drawer is for and became a product. It
now lives in its own repository, [jonathanroddev/vane](https://github.com/jonathanroddev/vane),
split into firmware, a standalone core and a Blender extension.
