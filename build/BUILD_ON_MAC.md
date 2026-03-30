# Building Agent Commander on macOS

## Prerequisites

1. **Python 3.11+**
   ```bash
   brew install python@3.11
   ```

2. **Install project dependencies**
   ```bash
   cd agent-commander
   pip3.11 install -e ".[dev]"
   pip3.11 install pyinstaller
   ```

3. **CLIProxyAPI binary for macOS**
   - Build `cli-proxy-api` from the CLIProxyAPI source repo on this Mac
   - Place the binary at: `cliproxyapi/cli-proxy-api`
   - Make it executable: `chmod +x cliproxyapi/cli-proxy-api`

4. **(Optional) App icon in .icns format**
   ```bash
   # Convert logo_w.png → logo_w.icns
   mkdir logo_w.iconset
   sips -z 16 16     logo_w.png --out logo_w.iconset/icon_16x16.png
   sips -z 32 32     logo_w.png --out logo_w.iconset/icon_16x16@2x.png
   sips -z 32 32     logo_w.png --out logo_w.iconset/icon_32x32.png
   sips -z 64 64     logo_w.png --out logo_w.iconset/icon_32x32@2x.png
   sips -z 128 128   logo_w.png --out logo_w.iconset/icon_128x128.png
   sips -z 256 256   logo_w.png --out logo_w.iconset/icon_128x128@2x.png
   sips -z 256 256   logo_w.png --out logo_w.iconset/icon_256x256.png
   sips -z 512 512   logo_w.png --out logo_w.iconset/icon_256x256@2x.png
   sips -z 512 512   logo_w.png --out logo_w.iconset/icon_512x512.png
   sips -z 1024 1024 logo_w.png --out logo_w.iconset/icon_512x512@2x.png
   iconutil -c icns logo_w.iconset
   rm -rf logo_w.iconset
   ```

## Build

```bash
cd agent-commander
pyinstaller build/build_macos.spec --clean
```

Result: `dist/AgentCommander.app`

## Test the build

```bash
open dist/AgentCommander.app
```

## Expected structure inside the .app

```
AgentCommander.app/
  Contents/
    MacOS/
      AgentCommander          ← main executable
      cliproxyapi/
        cli-proxy-api         ← CLIProxyAPI binary (if provided)
        config.yaml
      agent_commander/        ← Python modules
      PySide6/                ← Qt libraries
      ...
    Info.plist
    Resources/
      logo_w.icns             ← app icon
```

## Notes

- **UPX is disabled** — UPX breaks macOS code signing
- **argv_emulation=True** — enables drag-and-drop onto Dock icon
- **Login buttons** will work if `cliproxyapi/cli-proxy-api` is present
  (the app sets `AGENT_COMMANDER_FROZEN=1` automatically on launch)
- For **Apple Silicon (M1/M2/M3)**: build natively on ARM — will produce ARM binary
- For **universal2 fat binary** (Intel + ARM): set `target_arch="universal2"` in spec
  and ensure all deps are built as universal2
